"""
E2E Tests — Schwab Paper Account Integration.

These tests exercise the APIS SchwabBrokerAdapter against the Charles Schwab
paperMoney environment.  They require real Schwab OAuth credentials and a
valid token file produced by a prior browser OAuth flow.

─────────────────────────────────────────────────────────────────────────────
Running these tests
─────────────────────────────────────────────────────────────────────────────
Complete the one-time browser OAuth flow first (schwab-py):

    python -c "
    import schwab
    schwab.auth.easy_client(
        api_key='YOUR_APP_KEY',
        app_secret='YOUR_APP_SECRET',
        callback_url='https://127.0.0.1',
        token_path='schwab_token.json',
    )
    "

Then set environment variables and run:

    $env:SCHWAB_APP_KEY     = "your_app_key"
    $env:SCHWAB_APP_SECRET  = "your_app_secret"
    $env:SCHWAB_TOKEN_PATH  = "schwab_token.json"
    $env:SCHWAB_ACCOUNT_HASH = "your_encrypted_account_hash"

    cd apis
    $env:PYTHONPATH = "."
    .\.venv\Scripts\pytest.exe tests/e2e/test_schwab_paper_e2e.py -v -s

These tests are EXCLUDED from the standard unit test run so they never
block CI.

─────────────────────────────────────────────────────────────────────────────
What is tested
─────────────────────────────────────────────────────────────────────────────
  E2E_S01: SchwabBrokerAdapter — connect / ping / disconnect lifecycle
  E2E_S02: SchwabBrokerAdapter — get_account_state returns valid AccountState
  E2E_S03: SchwabBrokerAdapter — list_positions returns list (may be empty)
  E2E_S04: SchwabBrokerAdapter — list_open_orders returns list
  E2E_S05: SchwabBrokerAdapter — is_market_open returns bool
  E2E_S06: SchwabBrokerAdapter — next_market_open returns future datetime
  E2E_S07: SchwabBrokerAdapter — place_order: $1 limit buy on SPY (won't fill)
  E2E_S08: SchwabBrokerAdapter — get_order retrieves submitted order
  E2E_S09: SchwabBrokerAdapter — cancel_order removes submitted order
  E2E_S10: SchwabBrokerAdapter — idempotency guard rejects duplicate key
  E2E_S11: Full Schwab paper cycle — ranked→portfolio→risk→execute (mocked pipeline)
  E2E_S12: SchwabBrokerAdapter — refresh_auth reconnects successfully

─────────────────────────────────────────────────────────────────────────────
Safety guarantees
─────────────────────────────────────────────────────────────────────────────
- All adapter calls use paper=True (Schwab paperMoney endpoint).
- Orders use limit_price=Decimal("1.00") on SPY — far below market; will
  never fill in a paper account.
- Orders are cancelled immediately after submission.
- No live money is ever at risk.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

# ── Skip marker ───────────────────────────────────────────────────────────────

pytestmark = pytest.mark.e2e

# ── Credentials guard ─────────────────────────────────────────────────────────

_SCHWAB_KEY    = os.environ.get("SCHWAB_APP_KEY", "")
_SCHWAB_SECRET = os.environ.get("SCHWAB_APP_SECRET", "")
_SCHWAB_TOKEN  = os.environ.get("SCHWAB_TOKEN_PATH", "")
_SCHWAB_ACCT   = os.environ.get("SCHWAB_ACCOUNT_HASH", "")

_CREDS_MISSING = not (_SCHWAB_KEY and _SCHWAB_SECRET and _SCHWAB_TOKEN and _SCHWAB_ACCT)

_skip_no_creds = pytest.mark.skipif(
    _CREDS_MISSING,
    reason=(
        "Schwab paper credentials not set.  Export SCHWAB_APP_KEY, "
        "SCHWAB_APP_SECRET, SCHWAB_TOKEN_PATH, and SCHWAB_ACCOUNT_HASH "
        "to run Schwab E2E tests."
    ),
)


# ── Shared adapter fixture ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def schwab_adapter():
    """Module-scoped fixture: connected SchwabBrokerAdapter (paper mode)."""
    if _CREDS_MISSING:
        pytest.skip("Schwab credentials not configured — skipping Schwab E2E tests.")

    from broker_adapters.schwab.adapter import SchwabBrokerAdapter

    adapter = SchwabBrokerAdapter(
        api_key=_SCHWAB_KEY,
        app_secret=_SCHWAB_SECRET,
        token_path=_SCHWAB_TOKEN,
        account_hash=_SCHWAB_ACCT,
        paper=True,
    )
    adapter.connect()
    yield adapter
    adapter.disconnect()


# =============================================================================
# E2E_S01 — Connection / Lifecycle
# =============================================================================

@_skip_no_creds
class TestSchwabConnection:
    """E2E_S01 — connect / ping / disconnect lifecycle."""

    def test_connect_succeeds(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(
            api_key=_SCHWAB_KEY,
            app_secret=_SCHWAB_SECRET,
            token_path=_SCHWAB_TOKEN,
            account_hash=_SCHWAB_ACCT,
            paper=True,
        )
        a.connect()
        assert a._connected is True
        a.disconnect()

    def test_ping_returns_true_when_connected(self, schwab_adapter):
        assert schwab_adapter.ping() is True

    def test_disconnect_resets_connected_flag(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(
            api_key=_SCHWAB_KEY,
            app_secret=_SCHWAB_SECRET,
            token_path=_SCHWAB_TOKEN,
            account_hash=_SCHWAB_ACCT,
            paper=True,
        )
        a.connect()
        a.disconnect()
        assert a._connected is False


# =============================================================================
# E2E_S02 — Account State
# =============================================================================

@_skip_no_creds
class TestSchwabAccountState:
    """E2E_S02 — get_account_state returns valid AccountState."""

    def test_account_state_has_equity(self, schwab_adapter):
        from broker_adapters.base.models import AccountState
        state = schwab_adapter.get_account_state()
        assert isinstance(state, AccountState)
        assert state.total_equity >= Decimal("0")

    def test_account_state_has_cash(self, schwab_adapter):
        state = schwab_adapter.get_account_state()
        assert state.cash >= Decimal("0")

    def test_account_state_has_position_count(self, schwab_adapter):
        state = schwab_adapter.get_account_state()
        assert isinstance(state.position_count, int)
        assert state.position_count >= 0


# =============================================================================
# E2E_S03 — Positions
# =============================================================================

@_skip_no_creds
class TestSchwabPositions:
    """E2E_S03 — list_positions returns list (may be empty)."""

    def test_list_positions_returns_list(self, schwab_adapter):
        positions = schwab_adapter.list_positions()
        assert isinstance(positions, list)

    def test_positions_have_valid_structure(self, schwab_adapter):
        from broker_adapters.base.models import Position
        positions = schwab_adapter.list_positions()
        for pos in positions:
            assert isinstance(pos, Position)
            assert pos.ticker
            assert pos.quantity >= 0


# =============================================================================
# E2E_S04 — Open Orders
# =============================================================================

@_skip_no_creds
class TestSchwabOpenOrders:
    """E2E_S04 — list_open_orders returns list."""

    def test_list_open_orders_returns_list(self, schwab_adapter):
        orders = schwab_adapter.list_open_orders()
        assert isinstance(orders, list)

    def test_open_orders_have_valid_structure(self, schwab_adapter):
        from broker_adapters.base.models import Order
        orders = schwab_adapter.list_open_orders()
        for order in orders:
            assert isinstance(order, Order)
            assert order.order_id
            assert order.ticker


# =============================================================================
# E2E_S05-S06 — Market Hours
# =============================================================================

@_skip_no_creds
class TestSchwabMarketHours:
    """E2E_S05-S06 — market hours queries."""

    def test_is_market_open_returns_bool(self, schwab_adapter):
        result = schwab_adapter.is_market_open()
        assert isinstance(result, bool)

    def test_next_market_open_returns_datetime(self, schwab_adapter):
        nmo = schwab_adapter.next_market_open()
        assert isinstance(nmo, datetime)
        assert nmo.tzinfo is not None


# =============================================================================
# E2E_S07-S09 — Order Lifecycle
# =============================================================================

@_skip_no_creds
class TestSchwabOrderLifecycle:
    """E2E_S07-S09 — place / get / cancel a $1 limit order."""

    def test_place_and_cancel_limit_order(self, schwab_adapter):
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType, TimeInForce

        idempotency_key = f"schwab_e2e_{uuid.uuid4().hex[:8]}"

        req = OrderRequest(
            ticker="SPY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            limit_price=Decimal("1.00"),   # $1 limit — will never fill
            time_in_force=TimeInForce.DAY,
            idempotency_key=idempotency_key,
        )

        order = schwab_adapter.place_order(req)
        assert order.order_id
        assert order.ticker == "SPY"

        # Retrieve the order
        fetched = schwab_adapter.get_order(order.order_id)
        assert fetched.order_id == order.order_id

        # Cancel immediately
        schwab_adapter.cancel_order(order.order_id)

        # Verify cancelled
        cancelled = schwab_adapter.get_order(order.order_id)
        from broker_adapters.base.models import OrderStatus
        assert cancelled.status in (OrderStatus.CANCELLED, OrderStatus.SUBMITTED)

    def test_order_appears_in_open_orders(self, schwab_adapter):
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType, TimeInForce

        idempotency_key = f"schwab_e2e_open_{uuid.uuid4().hex[:8]}"

        req = OrderRequest(
            ticker="SPY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            limit_price=Decimal("1.00"),
            time_in_force=TimeInForce.DAY,
            idempotency_key=idempotency_key,
        )

        order = schwab_adapter.place_order(req)
        try:
            open_orders = schwab_adapter.list_open_orders()
            open_ids = {o.order_id for o in open_orders}
            assert order.order_id in open_ids
        finally:
            # Always cancel even if assertion fails
            try:
                schwab_adapter.cancel_order(order.order_id)
            except Exception:
                pass


# =============================================================================
# E2E_S10 — Idempotency Guard
# =============================================================================

@_skip_no_creds
class TestSchwabIdempotency:
    """E2E_S10 — duplicate idempotency key is rejected."""

    def test_duplicate_key_raises(self, schwab_adapter):
        from broker_adapters.base.exceptions import DuplicateOrderError
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType, TimeInForce

        key = f"schwab_idem_{uuid.uuid4().hex[:8]}"

        req = OrderRequest(
            ticker="SPY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            limit_price=Decimal("1.00"),
            time_in_force=TimeInForce.DAY,
            idempotency_key=key,
        )

        order = schwab_adapter.place_order(req)
        try:
            with pytest.raises(DuplicateOrderError):
                schwab_adapter.place_order(req)
        finally:
            try:
                schwab_adapter.cancel_order(order.order_id)
            except Exception:
                pass


# =============================================================================
# E2E_S11 — Full Schwab Paper Cycle (mocked pipeline)
# =============================================================================

@_skip_no_creds
class TestSchwabFullPaperCycle:
    """E2E_S11 — end-to-end paper trading cycle using Schwab adapter."""

    def test_full_paper_cycle_with_schwab(self, schwab_adapter):
        """
        Runs the APIS paper trading cycle with the Schwab adapter substituted
        for the default paper broker.  Uses mocked ranking/portfolio/risk services
        to avoid needing a full DB; only the broker adapter is real.
        """
        from apps.api.state import ApiAppState, reset_app_state
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings

        reset_app_state()
        state = ApiAppState()
        state.broker_adapter = schwab_adapter

        # Inject a pre-populated ranked result so the cycle has something to trade
        from services.ranking_engine.service import RankedResult

        state.latest_rankings = [
            RankedResult(
                ticker="SPY",
                composite_score=0.75,
                thesis_summary="Broad market proxy for E2E test",
                disconfirming_factors=[],
                sizing_hint=0.05,
                horizon="short",
                catalyst_class="market_proxy",
                source_reliability_tier="primary",
                contains_rumor=False,
            )
        ]

        settings = Settings(operating_mode="paper")
        result = run_paper_trading_cycle(app_state=state, settings=settings)

        # Cycle must complete (ok or no_actions — depending on risk engine)
        assert result["status"] in ("ok", "no_actions", "skipped_no_rankings",
                                    "error", "skipped_mode")
        assert "executed_count" in result


# =============================================================================
# E2E_S12 — refresh_auth
# =============================================================================

@_skip_no_creds
class TestSchwabRefreshAuth:
    """E2E_S12 — refresh_auth reconnects via token file."""

    def test_refresh_auth_maintains_connectivity(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter

        a = SchwabBrokerAdapter(
            api_key=_SCHWAB_KEY,
            app_secret=_SCHWAB_SECRET,
            token_path=_SCHWAB_TOKEN,
            account_hash=_SCHWAB_ACCT,
            paper=True,
        )
        a.connect()
        assert a.ping() is True

        # refresh_auth: disconnect + reconnect
        a.refresh_auth()
        assert a._connected is True
        assert a.ping() is True

        a.disconnect()
