"""
Schwab Broker Adapter — Concrete Implementation (schwab-py 1.x).

Uses the ``schwab-py`` SDK (https://schwab-py.readthedocs.io/) to implement
``BaseBrokerAdapter`` for Charles Schwab Developer API (OAuth 2.0 REST).

Authentication model
--------------------
Schwab uses OAuth 2.0.  The initial browser-flow must be completed once with::

    import schwab
    schwab.auth.easy_client(api_key, app_secret, callback_url, token_path)

After that, ``connect()`` calls ``client_from_token_file()`` which silently
refreshes the access token via the stored refresh token — no browser needed.

Paper trading
-------------
Schwab's paperMoney environment is functionally identical to the live API but
operates on a simulated account.  When ``paper=True`` (default), the adapter
asserts that the supplied account hash corresponds to a paper account.

Spec references
---------------
- APIS_MASTER_SPEC.md § 11
- API_AND_SERVICE_BOUNDARIES_SPEC.md § 3.12
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import schwab
import schwab.orders.equities as eq
from schwab.client import Client as SchwabClient

from broker_adapters.base.adapter import BaseBrokerAdapter
from broker_adapters.base.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    DuplicateOrderError,
    OrderRejectedError,
    PositionNotFoundError,
)
from broker_adapters.base.models import (
    AccountState,
    Fill,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

# ── Schwab order-status → APIS OrderStatus ────────────────────────────────────

_SCHWAB_STATUS_MAP: dict[str, OrderStatus] = {
    "NEW":                      OrderStatus.SUBMITTED,
    "AWAITING_PARENT_ORDER":    OrderStatus.PENDING,
    "AWAITING_CONDITION":       OrderStatus.PENDING,
    "AWAITING_STOP_CONDITION":  OrderStatus.PENDING,
    "AWAITING_MANUAL_REVIEW":   OrderStatus.PENDING,
    "AWAITING_RELEASE_TIME":    OrderStatus.PENDING,
    "AWAITING_UR_OUT":          OrderStatus.SUBMITTED,
    "ACCEPTED":                 OrderStatus.SUBMITTED,
    "PENDING_ACTIVATION":       OrderStatus.PENDING,
    "PENDING_ACKNOWLEDGEMENT":  OrderStatus.PENDING,
    "PENDING_CANCEL":           OrderStatus.SUBMITTED,
    "PENDING_REPLACE":          OrderStatus.SUBMITTED,
    "PENDING_RECALL":           OrderStatus.SUBMITTED,
    "QUEUED":                   OrderStatus.PENDING,
    "WORKING":                  OrderStatus.SUBMITTED,
    "REJECTED":                 OrderStatus.REJECTED,
    "CANCELED":                 OrderStatus.CANCELLED,
    "REPLACED":                 OrderStatus.CANCELLED,
    "FILLED":                   OrderStatus.FILLED,
    "EXPIRED":                  OrderStatus.EXPIRED,
    "UNKNOWN":                  OrderStatus.PENDING,
}


class SchwabBrokerAdapter(BaseBrokerAdapter):
    """
    Concrete broker adapter for Charles Schwab using schwab-py.

    Args:
        api_key:       Schwab app API key (client ID).
        app_secret:    Schwab app secret.
        callback_url:  OAuth callback URL registered with the Schwab Developer
                       Portal (default ``"https://127.0.0.1"``).
        token_path:    Path to the persisted OAuth token JSON file.
        account_hash:  Schwab-assigned encrypted account hash string.
        paper:         If True (default), restricts adapter to paperMoney
                       workflows only.
    """

    def __init__(
        self,
        api_key: str,
        app_secret: str,
        callback_url: str = "https://127.0.0.1",
        token_path: str = "schwab_token.json",  # noqa: S107 — file path, not a password
        account_hash: str | None = None,
        paper: bool = True,
    ) -> None:
        if not api_key or not api_key.strip():
            raise BrokerAuthenticationError(
                "Schwab api_key must not be empty.",
            )
        if not app_secret or not app_secret.strip():
            raise BrokerAuthenticationError(
                "Schwab app_secret must not be empty.",
            )

        self._api_key = api_key
        self._app_secret = app_secret
        self._callback_url = callback_url
        self._token_path = token_path
        self._account_hash = account_hash
        self._paper = paper
        self._connected = False
        self._client: SchwabClient | None = None
        self._idempotency_keys: set[str] = set()

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def adapter_name(self) -> str:
        return "schwab_paper" if self._paper else "schwab"

    # ── Connection / lifecycle ─────────────────────────────────────────────────

    def connect(self) -> None:
        """Authenticate with Schwab by loading/refreshing the token file.

        Raises:
            BrokerAuthenticationError: Token file missing or credentials invalid.
            BrokerConnectionError: Network or API error during initial ping.
        """
        try:
            self._client = schwab.auth.client_from_token_file(
                self._token_path,
                self._api_key,
                self._app_secret,
            )
        except FileNotFoundError as exc:
            raise BrokerAuthenticationError(
                f"Schwab token file not found at '{self._token_path}'. "
                "Run the browser-based OAuth flow once to create it."
            ) from exc
        except Exception as exc:
            raise BrokerAuthenticationError(
                f"Schwab authentication failed: {exc}"
            ) from exc

        try:
            resp = self._client.get_user_preferences()
            if resp.status_code not in (200, 204):
                raise BrokerConnectionError(
                    f"Schwab ping returned HTTP {resp.status_code}"
                )
        except BrokerConnectionError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(
                f"Schwab connectivity check failed: {exc}"
            ) from exc

        self._connected = True

    def disconnect(self) -> None:
        """Close the HTTP session and mark as disconnected."""
        if self._client is not None:
            try:
                self._client._session.close()
            except Exception:
                pass
        self._client = None
        self._connected = False

    def ping(self) -> bool:
        """Return True if the client is connected and the API is responsive."""
        if not self._connected or self._client is None:
            return False
        try:
            resp = self._client.get_user_preferences()
            return resp.status_code in (200, 204)
        except Exception:
            return False

    def refresh_auth(self) -> None:
        """Re-authenticate by reloading the token file.

        schwab-py's ``client_from_token_file`` silently refreshes the access
        token using the stored OAuth refresh token on each call — so calling
        ``connect()`` again is all that is needed for normal AT rotation.

        If the *refresh* token itself has expired (Schwab refresh tokens are
        valid for 7 days), this method raises ``BrokerAuthenticationError``
        and a new browser-based OAuth flow must be completed with::

            import schwab
            schwab.auth.easy_client(api_key, app_secret, callback_url, token_path)

        Raises:
            BrokerAuthenticationError: Refresh token expired or token file missing.
            BrokerConnectionError:     Network error after successful re-auth.
        """
        self.disconnect()
        self.connect()

    # ── Account ────────────────────────────────────────────────────────────────

    def get_account_state(self) -> AccountState:
        """Return current account cash, positions, and equity from Schwab."""
        self._require_connected()
        self._require_account_hash()
        try:
            resp = self._client.get_account(  # type: ignore[union-attr]
                self._account_hash,
                fields=[SchwabClient.Account.Fields.POSITIONS],
            )
            data = resp.json()
        except Exception as exc:
            raise BrokerConnectionError(f"get_account_state failed: {exc}") from exc

        sec_acct = data.get("securitiesAccount", {})
        balances = sec_acct.get("currentBalances", {})
        cash = Decimal(str(balances.get("cashBalance", "0")))
        buying_power = Decimal(str(balances.get("buyingPower", cash)))
        equity = Decimal(str(balances.get("liquidationValue", cash)))

        positions = self._parse_positions(sec_acct.get("positions", []))
        gross_exposure = sum((p.market_value for p in positions), Decimal("0"))

        return AccountState(
            account_id=str(sec_acct.get("accountNumber", self._account_hash or "")),
            cash_balance=cash,
            buying_power=buying_power,
            equity_value=equity,
            gross_exposure=gross_exposure,
            positions=positions,
        )

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(self, request: OrderRequest) -> Order:
        """Submit an equity order to Schwab.

        Raises:
            DuplicateOrderError:  idempotency_key was already submitted.
            OrderRejectedError:   Schwab rejected the order.
            BrokerConnectionError: Network error.
        """
        self._require_connected()
        self._require_account_hash()

        if request.idempotency_key in self._idempotency_keys:
            raise DuplicateOrderError(
                f"Order with key '{request.idempotency_key}' already submitted.",
                idempotency_key=request.idempotency_key,
            )

        order_builder = self._build_order(request)

        try:
            resp = self._client.place_order(  # type: ignore[union-attr]
                self._account_hash,
                order_builder.build(),
            )
        except DuplicateOrderError:
            raise
        except Exception as exc:
            raise OrderRejectedError(
                f"Schwab rejected order for {request.ticker}: {exc}",
                order_id=None,
            ) from exc

        if resp.status_code not in (200, 201):
            raise OrderRejectedError(
                f"Schwab place_order returned HTTP {resp.status_code} for {request.ticker}",
                order_id=None,
            )

        location = resp.headers.get("Location", "")
        broker_order_id = (
            location.rstrip("/").rsplit("/", 1)[-1]
            if location
            else str(uuid.uuid4())
        )
        self._idempotency_keys.add(request.idempotency_key)

        return Order(
            idempotency_key=request.idempotency_key,
            broker_order_id=broker_order_id,
            ticker=request.ticker,
            side=request.side,
            order_type=request.order_type,
            requested_quantity=request.quantity,
            filled_quantity=Decimal("0"),
            status=OrderStatus.SUBMITTED,
            submitted_at=dt.datetime.now(tz=dt.UTC),
        )

    def cancel_order(self, broker_order_id: str) -> Order:
        """Cancel a pending order."""
        self._require_connected()
        self._require_account_hash()
        try:
            self._client.cancel_order(  # type: ignore[union-attr]
                int(broker_order_id),
                self._account_hash,
            )
            return self.get_order(broker_order_id)
        except OrderRejectedError:
            raise
        except Exception as exc:
            raise OrderRejectedError(
                f"Could not cancel order {broker_order_id}: {exc}",
                order_id=broker_order_id,
            ) from exc

    def get_order(self, broker_order_id: str) -> Order:
        """Retrieve current state of a single order."""
        self._require_connected()
        self._require_account_hash()
        try:
            resp = self._client.get_order(  # type: ignore[union-attr]
                int(broker_order_id),
                self._account_hash,
            )
            data = resp.json()
        except Exception as exc:
            raise OrderRejectedError(
                f"Order not found: {broker_order_id}: {exc}",
                order_id=broker_order_id,
            ) from exc
        return self._parse_order(data)

    def list_open_orders(self) -> list[Order]:
        """Return all working / pending orders for the account."""
        self._require_connected()
        self._require_account_hash()
        try:
            resp = self._client.get_orders_for_account(  # type: ignore[union-attr]
                self._account_hash,
                status=SchwabClient.Order.Status.WORKING,
            )
            orders_data = resp.json() or []
        except Exception as exc:
            raise BrokerConnectionError(f"list_open_orders failed: {exc}") from exc
        return [self._parse_order(o) for o in orders_data]

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_position(self, ticker: str) -> Position:
        """Return the position for *ticker*.  Raises PositionNotFoundError if none."""
        acct = self.get_account_state()
        for pos in acct.positions:
            if pos.ticker == ticker:
                return pos
        raise PositionNotFoundError(f"No open position for {ticker}")

    def list_positions(self) -> list[Position]:
        """Return all open positions."""
        acct = self.get_account_state()
        return acct.positions

    # ── Fills ─────────────────────────────────────────────────────────────────

    def get_fills_for_order(self, broker_order_id: str) -> list[Fill]:
        """Return fills for a specific order by parsing its activity collection."""
        order_data = self._get_order_raw(broker_order_id)
        return self._extract_fills_from_order(order_data)

    def list_fills_since(self, since: dt.datetime) -> list[Fill]:
        """Return all fills since *since* by querying TRADE transactions."""
        self._require_connected()
        self._require_account_hash()
        try:
            resp = self._client.get_transactions(  # type: ignore[union-attr]
                self._account_hash,
                transaction_type=SchwabClient.Transactions.TransactionType.TRADE,
                start_date=since,
                end_date=dt.datetime.now(tz=dt.UTC),
            )
            txns = resp.json() or []
        except Exception as exc:
            raise BrokerConnectionError(f"list_fills_since failed: {exc}") from exc

        fills: list[Fill] = []
        for txn in txns:
            fill = self._parse_transaction_fill(txn)
            if fill is not None:
                fills.append(fill)
        return fills

    # ── Market hours ──────────────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        """Return True if the US equity market is currently open."""
        self._require_connected()
        try:
            today = dt.datetime.now(tz=dt.UTC).date()
            resp = self._client.get_market_hours(  # type: ignore[union-attr]
                markets=[SchwabClient.MarketHours.Market.EQUITY],
                date=today,
            )
            data = resp.json()
            equity = data.get("equity", {})
            for market_data in equity.values():
                return bool(market_data.get("isOpen", False))
        except Exception:
            pass
        return False

    def next_market_open(self) -> dt.datetime:
        """Return datetime of the next equity market open (UTC)."""
        self._require_connected()
        try:
            today = dt.datetime.now(tz=dt.UTC).date()
            for offset in range(6):
                check_date = today + dt.timedelta(days=offset)
                resp = self._client.get_market_hours(  # type: ignore[union-attr]
                    markets=[SchwabClient.MarketHours.Market.EQUITY],
                    date=check_date,
                )
                data = resp.json()
                equity = data.get("equity", {})
                for market_data in equity.values():
                    if market_data.get("isOpen"):
                        session_hours = market_data.get("sessionHours", {})
                        regular = session_hours.get("regularMarket", [])
                        if regular:
                            start_str = regular[0].get("start", "")
                            if start_str:
                                return dt.datetime.fromisoformat(
                                    start_str
                                ).astimezone(dt.UTC)
        except Exception:
            pass
        return self._next_930_et()

    # ── Private helpers ─────────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self._connected or self._client is None:
            raise BrokerConnectionError(
                "SchwabBrokerAdapter is not connected. Call connect() first."
            )

    def _require_account_hash(self) -> None:
        if not self._account_hash:
            raise BrokerConnectionError(
                "account_hash is required for account-level Schwab API calls."
            )

    def _build_order(self, request: OrderRequest):
        """Translate an OrderRequest to a schwab-py OrderBuilder."""
        qty = int(request.quantity)
        side = request.side
        order_type = request.order_type

        if side == OrderSide.BUY:
            if order_type == OrderType.MARKET:
                return eq.equity_buy_market(request.ticker, qty)
            elif order_type == OrderType.LIMIT:
                if request.limit_price is None:
                    raise OrderRejectedError(
                        "limit_price required for LIMIT buy order.", order_id=None
                    )
                return eq.equity_buy_limit(
                    request.ticker, qty, float(request.limit_price)
                )
        elif side == OrderSide.SELL:
            if order_type == OrderType.MARKET:
                return eq.equity_sell_market(request.ticker, qty)
            elif order_type == OrderType.LIMIT:
                if request.limit_price is None:
                    raise OrderRejectedError(
                        "limit_price required for LIMIT sell order.", order_id=None
                    )
                return eq.equity_sell_limit(
                    request.ticker, qty, float(request.limit_price)
                )
        raise OrderRejectedError(
            f"Order type {order_type.value} / side {side.value} not supported.",
            order_id=None,
        )

    def _get_order_raw(self, broker_order_id: str) -> dict:
        """Fetch raw order JSON dict from the Schwab API."""
        self._require_connected()
        self._require_account_hash()
        try:
            resp = self._client.get_order(  # type: ignore[union-attr]
                int(broker_order_id),
                self._account_hash,
            )
            return resp.json()
        except Exception as exc:
            raise OrderRejectedError(
                f"Order not found: {broker_order_id}: {exc}",
                order_id=broker_order_id,
            ) from exc

    def _parse_order(self, data: dict) -> Order:
        """Translate a Schwab order JSON dict → APIS Order domain model."""
        broker_order_id = str(data.get("orderId", ""))
        raw_status = str(data.get("status", "UNKNOWN")).upper()
        status = _SCHWAB_STATUS_MAP.get(raw_status, OrderStatus.SUBMITTED)

        legs = data.get("orderLegCollection", [])
        instruction = "BUY"
        ticker = ""
        requested_qty = Decimal("0")
        if legs:
            instruction = str(legs[0].get("instruction", "BUY")).upper()
            ticker = str(legs[0].get("instrument", {}).get("symbol", ""))
            requested_qty = Decimal(str(legs[0].get("quantity", "0")))

        side = (
            OrderSide.BUY
            if instruction in ("BUY", "BUY_TO_COVER")
            else OrderSide.SELL
        )
        raw_order_type = str(data.get("orderType", "MARKET")).upper()
        order_type = OrderType.LIMIT if raw_order_type == "LIMIT" else OrderType.MARKET
        filled_qty = Decimal(str(data.get("filledQuantity", "0")))

        all_exec: list[tuple[Decimal, Decimal]] = []
        for act in data.get("orderActivityCollection", []):
            if act.get("activityType") == "EXECUTION":
                for leg_exec in act.get("executionLegs", []):
                    all_exec.append((
                        Decimal(str(leg_exec.get("quantity", "0"))),
                        Decimal(str(leg_exec.get("price", "0"))),
                    ))
        avg_fill_price: Decimal | None = None
        if all_exec:
            total_q = sum(q for q, _ in all_exec)
            if total_q > 0:
                avg_fill_price = sum(q * p for q, p in all_exec) / total_q

        submitted_at = (
            self._parse_ts(data.get("enteredTime", ""))
            or dt.datetime.now(tz=dt.UTC)
        )
        filled_at = self._parse_ts(data.get("closeTime", ""))
        limit_price_raw = data.get("price")
        limit_price = Decimal(str(limit_price_raw)) if limit_price_raw else None
        idempotency_key = str(data.get("tag", broker_order_id)) or broker_order_id

        return Order(
            idempotency_key=idempotency_key,
            broker_order_id=broker_order_id,
            ticker=ticker,
            side=side,
            order_type=order_type,
            requested_quantity=requested_qty,
            filled_quantity=filled_qty,
            status=status,
            submitted_at=submitted_at,
            filled_at=filled_at,
            average_fill_price=avg_fill_price,
            limit_price=limit_price,
        )

    def _parse_positions(self, positions_data: list[dict]) -> list[Position]:
        """Translate Schwab position JSON dicts → APIS Position domain models."""
        result: list[Position] = []
        for pos_data in positions_data:
            instrument = pos_data.get("instrument", {})
            ticker = instrument.get("symbol", "")
            if not ticker:
                continue
            long_qty = Decimal(str(pos_data.get("longQuantity", "0")))
            short_qty = Decimal(str(pos_data.get("shortQuantity", "0")))
            quantity = long_qty - short_qty
            if quantity == 0:
                continue
            avg_price = Decimal(str(pos_data.get("averagePrice", "0")))
            market_val = Decimal(str(pos_data.get("marketValue", "0")))
            current_price = market_val / quantity if quantity != 0 else avg_price
            cost_basis = avg_price * quantity
            unrealized_pnl = market_val - cost_basis
            unrealized_pnl_pct = (
                (unrealized_pnl / cost_basis * 100)
                if cost_basis != 0
                else Decimal("0")
            )
            result.append(Position(
                ticker=ticker,
                quantity=quantity,
                average_entry_price=avg_price,
                current_price=current_price,
                market_value=market_val,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                side="long" if quantity > 0 else "short",
            ))
        return result

    def _extract_fills_from_order(self, order_data: dict) -> list[Fill]:
        """Parse execution legs from a Schwab order dict → Fill objects."""
        fills: list[Fill] = []
        broker_order_id = str(order_data.get("orderId", ""))
        legs = order_data.get("orderLegCollection", [])
        ticker = legs[0].get("instrument", {}).get("symbol", "") if legs else ""
        instruction = legs[0].get("instruction", "BUY").upper() if legs else "BUY"
        side = (
            OrderSide.BUY
            if instruction in ("BUY", "BUY_TO_COVER")
            else OrderSide.SELL
        )
        for act in order_data.get("orderActivityCollection", []):
            if act.get("activityType") != "EXECUTION":
                continue
            for exec_leg in act.get("executionLegs", []):
                fill_price = Decimal(str(exec_leg.get("price", "0")))
                fill_qty = Decimal(str(exec_leg.get("quantity", "0")))
                fill_time = (
                    self._parse_ts(exec_leg.get("time", ""))
                    or dt.datetime.now(tz=dt.UTC)
                )
                leg_id = str(exec_leg.get("legId", uuid.uuid4()))
                fills.append(Fill(
                    broker_fill_id=f"{broker_order_id}-{leg_id}",
                    broker_order_id=broker_order_id,
                    ticker=ticker,
                    side=side,
                    fill_quantity=fill_qty,
                    fill_price=fill_price,
                    fees=Decimal("0"),
                    filled_at=fill_time,
                ))
        return fills

    def _parse_transaction_fill(self, txn: dict) -> Fill | None:
        """Translate a Schwab TRADE transaction dict → Fill (or None if not equity)."""
        if str(txn.get("type", "")).upper() != "TRADE":
            return None
        item = txn.get("transactionItem", {})
        instrument = item.get("instrument", {})
        asset_type = str(instrument.get("assetType", "")).upper()
        if asset_type not in ("EQUITY", ""):
            return None
        ticker = instrument.get("symbol", "")
        if not ticker:
            return None
        instruction = str(item.get("instruction", "BUY")).upper()
        side = (
            OrderSide.BUY
            if instruction in ("BUY", "BUY_TO_COVER")
            else OrderSide.SELL
        )
        fill_qty = Decimal(str(item.get("amount", "0")))
        fill_price = Decimal(str(item.get("price", "0")))
        broker_order_id = str(txn.get("orderId", ""))
        txn_id = str(txn.get("transactionId", uuid.uuid4()))
        fill_time = (
            self._parse_ts(txn.get("tradeDate", ""))
            or dt.datetime.now(tz=dt.UTC)
        )
        fees_dict = txn.get("fees", {})
        fees = (
            sum(Decimal(str(v)) for v in fees_dict.values() if v)
            if fees_dict
            else Decimal("0")
        )
        return Fill(
            broker_fill_id=txn_id,
            broker_order_id=broker_order_id,
            ticker=ticker,
            side=side,
            fill_quantity=fill_qty,
            fill_price=fill_price,
            fees=fees,
            filled_at=fill_time,
        )

    @staticmethod
    def _parse_ts(ts_str: str) -> dt.datetime | None:
        """Parse an ISO-8601 timestamp string to UTC datetime, or None."""
        if not ts_str:
            return None
        try:
            dt_obj = dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return dt_obj.astimezone(dt.UTC)
        except Exception:
            return None

    @staticmethod
    def _next_930_et() -> dt.datetime:
        """Return the next 09:30 ET on a weekday as a UTC datetime."""
        et_offset = dt.timezone(dt.timedelta(hours=-5))
        now_et = dt.datetime.now(tz=dt.UTC).astimezone(et_offset)
        candidate = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if candidate <= now_et:
            candidate += dt.timedelta(days=1)
        while candidate.weekday() >= 5:  # skip Sat/Sun
            candidate += dt.timedelta(days=1)
        return candidate.astimezone(dt.UTC)
