"""Unit tests for Deep-Dive Plan Step 7 — Shadow Portfolio Scorer (Rec 11 + DEC-034).

Covers:
  - Settings integration: APIS_SHADOW_PORTFOLIO_ENABLED default OFF, watch band
    defaults, shadow_rebalance_modes default list, stopped-out max age default.
  - Shadow-name constants: SHADOW_NAMES contains the 6 DEC-034 buckets and
    REJECTION_SHADOWS / REBALANCE_SHADOWS split correctly.
  - ShadowOrderResult / ShadowPnL dataclass shape.
  - ShadowPortfolioService.place_virtual_order validation guards (action /
    shares / price) and BUY/SELL flows against a stateful in-memory fake
    session (new position, add-to-position, partial sell, full close, clamped
    over-sell, sell-without-position).
  - ensure_shadow / ensure_all_canonical idempotency.
  - Convenience writers record_rejected_action / record_watch_tier /
    record_rebalance_shadow / record_stopped_out_continued route to the right
    shadow and attach the right labels.
  - record_rebalance_shadow rejects unknown weighting modes.
  - mark_to_market realized + unrealized math on a synthetic price move.
  - Worker job flag-off returns a no-op summary dict.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Settings integration
# ---------------------------------------------------------------------------


class TestSettingsIntegration:
    def test_shadow_portfolio_flag_default_false(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert hasattr(s, "shadow_portfolio_enabled")
        assert s.shadow_portfolio_enabled is False

    def test_watch_composite_band_defaults_match_plan(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert s.shadow_watch_composite_low == pytest.approx(0.55)
        assert s.shadow_watch_composite_high == pytest.approx(0.65)

    def test_shadow_rebalance_modes_default_list(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert s.shadow_rebalance_modes == ["equal", "score", "score_invvol"]

    def test_shadow_stopped_out_max_age_default(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert s.shadow_stopped_out_max_age_days == 30


# ---------------------------------------------------------------------------
# Shadow-name constants
# ---------------------------------------------------------------------------


class TestShadowNameConstants:
    def test_shadow_names_contains_all_dec034_buckets(self) -> None:
        from infra.db.models.shadow_portfolio import SHADOW_NAMES

        assert set(SHADOW_NAMES) == {
            "rejected_actions",
            "watch_tier",
            "stopped_out_continued",
            "rebalance_equal",
            "rebalance_score",
            "rebalance_score_invvol",
        }

    def test_rejection_vs_rebalance_taxonomy_split(self) -> None:
        # Every canonical name must belong to exactly one bucket kind.
        from infra.db.models.shadow_portfolio import SHADOW_NAMES
        from services.shadow_portfolio import REBALANCE_SHADOWS, REJECTION_SHADOWS

        for name in SHADOW_NAMES:
            assert (name in REJECTION_SHADOWS) ^ (name in REBALANCE_SHADOWS), (
                f"{name!r} must be either a rejection or a rebalance shadow (exclusive)"
            )
        assert set(REJECTION_SHADOWS) | set(REBALANCE_SHADOWS) == set(SHADOW_NAMES)

    def test_rebalance_shadows_cover_all_methods(self) -> None:
        from services.shadow_portfolio import REBALANCE_SHADOWS

        assert set(REBALANCE_SHADOWS) == {
            "rebalance_equal",
            "rebalance_score",
            "rebalance_score_invvol",
        }


# ---------------------------------------------------------------------------
# In-memory stateful fake session (enough to exercise the service's SQL)
# ---------------------------------------------------------------------------


class _FakeQuery:
    """Captures .where() criteria as (column_key, value) predicate tuples."""

    def __init__(self, entity_name: str) -> None:
        self.entity_name = entity_name
        self.predicates: list[tuple[str, Any]] = []
        self.limit_n: int | None = None
        self.ordered_by_name: bool = False

    def where(self, *criteria) -> _FakeQuery:
        for c in criteria:
            self.predicates.extend(self._unpack(c))
        return self

    def order_by(self, *_a, **_kw) -> _FakeQuery:
        # Remember that the query requested ordering — for list_shadows this
        # asks for alphabetical; for get_trades this is by executed_at.
        self.ordered_by_name = True
        return self

    def limit(self, n: int) -> _FakeQuery:
        self.limit_n = int(n)
        return self

    @staticmethod
    def _unpack(criterion) -> list[tuple[str, Any]]:
        """Convert a BinaryExpression or BooleanClauseList into (key, value)
        pairs the in-memory backend can filter by.
        """
        # ``and_(a, b)`` yields a BooleanClauseList with ``.clauses``
        if hasattr(criterion, "clauses"):
            out: list[tuple[str, Any]] = []
            for sub in criterion.clauses:
                out.extend(_FakeQuery._unpack(sub))
            return out
        # BinaryExpression has .left (column), .right (value/BindParameter)
        left = getattr(criterion, "left", None)
        right = getattr(criterion, "right", None)
        if left is None or right is None:
            return []
        col_key = getattr(left, "key", None) or str(left)
        val = getattr(right, "value", right)
        # Resolve callable defaults (UUIDs wrapped in BindParameter)
        if callable(val):
            try:
                val = val()
            except Exception:  # noqa: BLE001
                pass
        return [(col_key, val)]


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self):
        if not self._rows:
            return None
        return self._rows[0]

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """In-memory ORM-ish session just rich enough for ShadowPortfolioService.

    Stores rows keyed by entity type + id.  ``execute(select(X).where(...))``
    inspects the where-clause for simple ``col == value`` / ``and_(...)``
    predicates and returns matching rows.
    """

    def __init__(self) -> None:
        self._portfolios: dict[uuid.UUID, Any] = {}
        self._positions: dict[uuid.UUID, Any] = {}
        self._trades: dict[uuid.UUID, Any] = {}
        self.flush_count = 0

    # ---- adder / deleter
    def add(self, row: Any) -> None:
        tbl = getattr(row, "__tablename__", "")
        if tbl == "shadow_portfolios":
            self._portfolios[row.id] = row
        elif tbl == "shadow_positions":
            self._positions[row.id] = row
        elif tbl == "shadow_trades":
            self._trades[row.id] = row

    def delete(self, row: Any) -> None:
        self._positions.pop(row.id, None)

    def flush(self) -> None:
        self.flush_count += 1

    # ---- execute / select
    def execute(self, stmt) -> _FakeResult:
        # Introspect the Select → entity + where predicates
        # ``stmt.column_descriptions[0]["entity"]`` is the mapper class
        try:
            entity = stmt.column_descriptions[0]["entity"]
            entity_name = entity.__tablename__
        except Exception:  # noqa: BLE001
            entity_name = ""

        fq = _FakeQuery(entity_name)
        where = stmt.whereclause
        if where is not None:
            fq.predicates = _FakeQuery._unpack(where)

        bucket: dict[uuid.UUID, Any]
        if entity_name == "shadow_portfolios":
            bucket = self._portfolios
        elif entity_name == "shadow_positions":
            bucket = self._positions
        elif entity_name == "shadow_trades":
            bucket = self._trades
        else:
            return _FakeResult([])

        rows = list(bucket.values())
        for key, val in fq.predicates:
            rows = [r for r in rows if getattr(r, key, None) == val]

        # Detect the real Select's order_by clauses — our _FakeQuery shim
        # never gets called by the service (it goes through SQLAlchemy
        # ``select().order_by(...)`` directly), so we introspect the
        # Select's ``_order_by_clauses`` tuple to decide how to sort.
        ordered_cols: list[str] = []
        for c in getattr(stmt, "_order_by_clauses", ()) or ():
            ck = getattr(c, "key", None)
            if ck:
                ordered_cols.append(ck)
        if entity_name == "shadow_portfolios" and "name" in ordered_cols:
            rows.sort(key=lambda r: r.name)
        if entity_name == "shadow_trades" and "executed_at" in ordered_cols:
            rows.sort(key=lambda r: r.executed_at)
        return _FakeResult(rows)


# ---------------------------------------------------------------------------
# place_virtual_order validation guards
# ---------------------------------------------------------------------------


class TestPlaceVirtualOrderValidation:
    def test_rejects_unknown_action(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        svc = ShadowPortfolioService(FakeSession())
        with pytest.raises(ValueError, match="invalid action"):
            svc.place_virtual_order(
                shadow_name="rejected_actions",
                ticker="AAPL",
                action="HOLD",
                shares=10,
                price=150.0,
            )

    def test_rejects_zero_or_negative_shares(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        svc = ShadowPortfolioService(FakeSession())
        with pytest.raises(ValueError, match="shares must be positive"):
            svc.place_virtual_order(
                shadow_name="rejected_actions",
                ticker="AAPL",
                action="BUY",
                shares=0,
                price=150.0,
            )
        with pytest.raises(ValueError, match="shares must be positive"):
            svc.place_virtual_order(
                shadow_name="rejected_actions",
                ticker="AAPL",
                action="BUY",
                shares=-5,
                price=150.0,
            )

    def test_rejects_zero_or_negative_price(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        svc = ShadowPortfolioService(FakeSession())
        with pytest.raises(ValueError, match="price must be positive"):
            svc.place_virtual_order(
                shadow_name="rejected_actions",
                ticker="AAPL",
                action="BUY",
                shares=10,
                price=0,
            )
        with pytest.raises(ValueError, match="price must be positive"):
            svc.place_virtual_order(
                shadow_name="rejected_actions",
                ticker="AAPL",
                action="BUY",
                shares=10,
                price=-1,
            )


# ---------------------------------------------------------------------------
# place_virtual_order BUY / SELL flows
# ---------------------------------------------------------------------------


class TestPlaceVirtualOrderFlows:
    def test_buy_opens_new_position_and_records_trade(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        result = svc.place_virtual_order(
            shadow_name="rejected_actions",
            ticker="AAPL",
            action="BUY",
            shares=10,
            price=150.0,
            rejection_reason="test_reason",
        )
        assert result.created_position is True
        assert result.closed_position is False
        assert result.realized_pnl is None
        # One position + one trade row added
        assert len(sess._positions) == 1
        assert len(sess._trades) == 1
        # The shadow portfolio row was also auto-created by ensure_shadow.
        assert len(sess._portfolios) == 1
        portfolio = next(iter(sess._portfolios.values()))
        assert portfolio.name == "rejected_actions"

    def test_buy_adds_to_existing_position_weighted_avg_cost(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        svc.place_virtual_order(
            shadow_name="watch_tier",
            ticker="MSFT",
            action="BUY",
            shares=10,
            price=100.0,
        )
        svc.place_virtual_order(
            shadow_name="watch_tier",
            ticker="MSFT",
            action="BUY",
            shares=10,
            price=200.0,
        )
        # Weighted average cost = (10*100 + 10*200) / 20 = 150
        pos = next(iter(sess._positions.values()))
        assert pos.ticker == "MSFT"
        assert pos.shares == Decimal("20.0000")
        assert pos.avg_cost == Decimal("150.0000")
        assert len(sess._trades) == 2

    def test_sell_fully_closes_position_and_records_pnl(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        svc.place_virtual_order(
            shadow_name="rejected_actions",
            ticker="GOOG",
            action="BUY",
            shares=5,
            price=100.0,
        )
        result = svc.place_virtual_order(
            shadow_name="rejected_actions",
            ticker="GOOG",
            action="SELL",
            shares=5,
            price=120.0,
        )
        assert result.closed_position is True
        assert result.realized_pnl == Decimal("100.00")
        # Position row removed, two trade rows remain.
        assert len(sess._positions) == 0
        assert len(sess._trades) == 2

    def test_sell_partial_keeps_position_and_records_partial_pnl(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        svc.place_virtual_order(
            shadow_name="rejected_actions",
            ticker="TSLA",
            action="BUY",
            shares=10,
            price=200.0,
        )
        result = svc.place_virtual_order(
            shadow_name="rejected_actions",
            ticker="TSLA",
            action="SELL",
            shares=3,
            price=220.0,
        )
        assert result.closed_position is False
        assert result.realized_pnl == Decimal("60.00")
        pos = next(iter(sess._positions.values()))
        # Remaining shares = 10 - 3 = 7; avg_cost unchanged by SELL.
        assert pos.shares == Decimal("7.0000")

    def test_sell_clamps_to_open_shares(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        svc.place_virtual_order(
            shadow_name="rejected_actions",
            ticker="NVDA",
            action="BUY",
            shares=4,
            price=100.0,
        )
        result = svc.place_virtual_order(
            shadow_name="rejected_actions",
            ticker="NVDA",
            action="SELL",
            shares=999,  # Way more than open
            price=110.0,
        )
        # Clamped to 4 shares → realized = (110-100)*4 = 40
        assert result.closed_position is True
        assert result.realized_pnl == Decimal("40.00")
        assert len(sess._positions) == 0

    def test_sell_without_position_is_recorded_as_noop_trade(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        result = svc.place_virtual_order(
            shadow_name="rejected_actions",
            ticker="AMZN",
            action="SELL",
            shares=5,
            price=130.0,
        )
        # No position existed; no realized PnL; trade row recorded with zero shares.
        assert result.closed_position is False
        assert result.realized_pnl is None
        assert len(sess._positions) == 0
        assert len(sess._trades) == 1


# ---------------------------------------------------------------------------
# ensure_shadow idempotency
# ---------------------------------------------------------------------------


class TestEnsureShadow:
    def test_ensure_shadow_is_idempotent(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        p1 = svc.ensure_shadow("rejected_actions")
        p2 = svc.ensure_shadow("rejected_actions")
        assert p1.id == p2.id
        assert len(sess._portfolios) == 1

    def test_ensure_all_canonical_creates_every_bucket(self) -> None:
        from infra.db.models.shadow_portfolio import SHADOW_NAMES
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        mapping = svc.ensure_all_canonical()
        assert set(mapping.keys()) == set(SHADOW_NAMES)
        assert len(sess._portfolios) == len(SHADOW_NAMES)

    def test_ensure_shadow_honors_custom_starting_cash(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        p = svc.ensure_shadow("watch_tier", starting_cash=50000)
        assert p.starting_cash == Decimal("50000")


# ---------------------------------------------------------------------------
# Convenience writers
# ---------------------------------------------------------------------------


class TestConvenienceWriters:
    def test_record_rejected_action_targets_rejection_shadow(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        result = svc.record_rejected_action(
            ticker="AAPL",
            shares=5,
            price=170.0,
            rejection_reason="concentration_limit",
        )
        # Trade row tagged with rejection_reason, pointing at rejected_actions.
        trade = next(iter(sess._trades.values()))
        assert trade.rejection_reason == "concentration_limit"
        portfolio = next(iter(sess._portfolios.values()))
        assert portfolio.name == "rejected_actions"
        assert result.created_position is True

    def test_record_watch_tier_labels_with_composite(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        svc.record_watch_tier(
            ticker="MSFT",
            shares=3,
            price=300.0,
            composite_score=0.612,
        )
        trade = next(iter(sess._trades.values()))
        assert "composite=" in (trade.rejection_reason or "")
        assert "0.612" in (trade.rejection_reason or "")

    def test_record_rebalance_shadow_routes_to_correct_bucket(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        svc.record_rebalance_shadow(
            weighting_mode="score_invvol",
            ticker="AAPL",
            action="BUY",
            shares=10,
            price=180.0,
        )
        portfolio = next(iter(sess._portfolios.values()))
        assert portfolio.name == "rebalance_score_invvol"
        trade = next(iter(sess._trades.values()))
        assert trade.weighting_mode == "score_invvol"

    def test_record_rebalance_shadow_rejects_unknown_mode(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        svc = ShadowPortfolioService(FakeSession())
        with pytest.raises(ValueError, match="unknown weighting_mode"):
            svc.record_rebalance_shadow(
                weighting_mode="bogus",
                ticker="AAPL",
                action="BUY",
                shares=1,
                price=1,
            )

    def test_record_stopped_out_continued_uses_stop_reason_as_source(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        svc.record_stopped_out_continued(
            ticker="TSLA",
            shares=8,
            price=190.0,
            stop_reason="trailing_stop",
        )
        portfolio = next(iter(sess._portfolios.values()))
        assert portfolio.name == "stopped_out_continued"
        pos = next(iter(sess._positions.values()))
        assert pos.opened_source == "trailing_stop"


# ---------------------------------------------------------------------------
# mark_to_market
# ---------------------------------------------------------------------------


class TestMarkToMarket:
    def test_realized_and_unrealized_pnl(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        # Buy 10 @ $100, sell 4 @ $110 → realized = +40
        # Remaining 6 @ $100; mark at $120 → unrealized = +120
        svc.place_virtual_order(
            shadow_name="watch_tier",
            ticker="AAPL",
            action="BUY",
            shares=10,
            price=100.0,
        )
        svc.place_virtual_order(
            shadow_name="watch_tier",
            ticker="AAPL",
            action="SELL",
            shares=4,
            price=110.0,
        )
        pnl = svc.mark_to_market("watch_tier", prices={"AAPL": Decimal("120.00")})
        assert pnl.shadow_name == "watch_tier"
        assert pnl.realized_pnl == Decimal("40.00")
        assert pnl.unrealized_pnl == Decimal("120.00")
        assert pnl.total_pnl == Decimal("160.00")
        assert pnl.n_open_positions == 1
        assert pnl.n_trades == 2

    def test_mark_to_market_missing_shadow_returns_zeros(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        svc = ShadowPortfolioService(FakeSession())
        pnl = svc.mark_to_market("rebalance_equal", prices={"AAPL": 150})
        assert pnl.n_trades == 0
        assert pnl.n_open_positions == 0
        assert pnl.total_pnl == Decimal("0")

    def test_mark_to_market_missing_price_treats_as_flat(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        svc.place_virtual_order(
            shadow_name="watch_tier",
            ticker="AAPL",
            action="BUY",
            shares=5,
            price=100.0,
        )
        pnl = svc.mark_to_market("watch_tier", prices={})  # No price given
        assert pnl.unrealized_pnl == Decimal("0.00")
        assert pnl.realized_pnl == Decimal("0")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestReads:
    def test_list_shadows_sorted_by_name(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        sess = FakeSession()
        svc = ShadowPortfolioService(sess)
        svc.ensure_shadow("watch_tier")
        svc.ensure_shadow("rejected_actions")
        svc.ensure_shadow("rebalance_equal")
        names = [p.name for p in svc.list_shadows()]
        assert names == sorted(names)

    def test_get_positions_empty_for_unknown_shadow(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        svc = ShadowPortfolioService(FakeSession())
        assert svc.get_positions("does_not_exist") == []

    def test_get_trades_empty_for_unknown_shadow(self) -> None:
        from services.shadow_portfolio import ShadowPortfolioService

        svc = ShadowPortfolioService(FakeSession())
        assert svc.get_trades("does_not_exist") == []


# ---------------------------------------------------------------------------
# Worker job flag-off
# ---------------------------------------------------------------------------


class TestWorkerJobFlagOff:
    def test_flag_off_returns_noop_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flag-OFF path must short-circuit without touching the DB.

        The job module imports ``SessionLocal`` at module scope — and
        ``infra.db.session`` creates the engine on import, which requires
        a live Postgres driver in this environment.  To keep this a pure
        unit test we inject a stub ``infra.db.session`` module into
        ``sys.modules`` before the job module is imported.
        """
        import sys
        import types

        if "apps.worker.jobs.shadow_performance_assessment" in sys.modules:
            del sys.modules["apps.worker.jobs.shadow_performance_assessment"]

        fake_session_mod = types.ModuleType("infra.db.session")

        class _FakeSessionLocal:
            def __enter__(self):  # pragma: no cover - flag-off never enters
                raise AssertionError(
                    "SessionLocal must not be opened when the shadow flag is OFF"
                )

            def __exit__(self, *a):  # pragma: no cover
                return False

        fake_session_mod.SessionLocal = lambda: _FakeSessionLocal()
        monkeypatch.setitem(sys.modules, "infra.db.session", fake_session_mod)

        from apps.worker.jobs import shadow_performance_assessment as job_mod

        class _FakeSettings:
            shadow_portfolio_enabled = False

        monkeypatch.setattr(job_mod, "get_settings", lambda: _FakeSettings())
        summary = job_mod.run_shadow_performance_assessment()
        assert summary["flag_off"] is True
        assert summary["shadows"] == {}
        assert summary["proposals_emitted"] == 0
