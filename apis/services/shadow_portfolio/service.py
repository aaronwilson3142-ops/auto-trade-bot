"""Shadow Portfolio Service — Deep-Dive Plan Step 7 (Rec 11 + DEC-034).

Virtual paper portfolios that mirror live risk gates but take rejected ideas,
watch-tier borderline names, stopped-out positions that would have continued,
and parallel alternative-rebalance-weighting A/B shadows (equal / score /
score_invvol).

All writes flow through ``ShadowPortfolioService``.  Every write is
**flag-gated at the call site** — the worker checks
``settings.shadow_portfolio_enabled`` before invoking this service.  When the
flag is OFF, no rows are written; the tables simply exist.

The service shape intentionally mirrors ``PortfolioEngineService`` so future
refactors can share helpers, but it deliberately maintains its own cash,
position, and trade ledger so a shadow never touches live cash.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

import structlog
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from infra.db.models.shadow_portfolio import (
    SHADOW_NAMES,
    ShadowPortfolio,
    ShadowPosition,
    ShadowTrade,
)

_log = structlog.get_logger(__name__)


# Bucket taxonomy — the weekly job keys proposal emission off these tuples
# (``GATE_LOOSEN`` for REJECTION shadows, ``ALLOCATOR_CHANGE`` for REBALANCE
# shadows).  Plan §7.6.
REJECTION_SHADOWS: tuple[str, ...] = (
    "rejected_actions",
    "watch_tier",
    "stopped_out_continued",
)
REBALANCE_SHADOWS: tuple[str, ...] = (
    "rebalance_equal",
    "rebalance_score",
    "rebalance_score_invvol",
)

_DEFAULT_STARTING_CASH = Decimal("100000")


@dataclass(frozen=True)
class ShadowOrderResult:
    """Return value of ``place_virtual_order`` — enough to reconstruct the
    trade without re-querying.
    """

    shadow_portfolio_id: uuid.UUID
    trade_id: uuid.UUID
    ticker: str
    action: str
    shares: Decimal
    price: Decimal
    realized_pnl: Decimal | None
    created_position: bool
    closed_position: bool


@dataclass(frozen=True)
class ShadowPnL:
    """Mark-to-market summary for a shadow portfolio.  Returned by
    :meth:`ShadowPortfolioService.mark_to_market`.
    """

    shadow_name: str
    starting_cash: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    n_open_positions: int
    n_trades: int


class ShadowPortfolioService:
    """Read/write facade for shadow_portfolios, _positions, _trades."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------ ensure
    def ensure_shadow(
        self, name: str, *, starting_cash: Decimal | float | int | None = None
    ) -> ShadowPortfolio:
        """Upsert a named shadow portfolio row.  Idempotent."""
        existing = self._db.execute(
            select(ShadowPortfolio).where(ShadowPortfolio.name == name)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        cash = (
            Decimal(str(starting_cash))
            if starting_cash is not None
            else _DEFAULT_STARTING_CASH
        )
        row = ShadowPortfolio(
            id=uuid.uuid4(),
            name=name,
            starting_cash=cash,
        )
        self._db.add(row)
        self._db.flush()
        _log.info("shadow_portfolio.ensure", name=name, starting_cash=str(cash))
        return row

    def ensure_all_canonical(self) -> dict[str, ShadowPortfolio]:
        """Ensure every name in ``SHADOW_NAMES`` exists.  Returns a map
        ``{name -> ShadowPortfolio}`` in canonical order.
        """
        return {n: self.ensure_shadow(n) for n in SHADOW_NAMES}

    # ------------------------------------------------------------------ writes
    def place_virtual_order(
        self,
        *,
        shadow_name: str,
        ticker: str,
        action: str,
        shares: Decimal | float | int,
        price: Decimal | float | int,
        executed_at: dt.datetime | None = None,
        rejection_reason: str | None = None,
        weighting_mode: str | None = None,
        opened_source: str | None = None,
    ) -> ShadowOrderResult:
        """Place a virtual BUY or SELL against ``shadow_name``.

        BUY upserts into ``shadow_positions`` (new row or shares-weighted
        average cost).  SELL closes the position (deletes row, realized P&L
        recorded on the trade).  A SELL with more shares than are open is
        clamped to the open shares — shadow portfolios can't go short.
        """
        action = action.upper()
        if action not in ("BUY", "SELL"):
            raise ValueError(f"invalid action {action!r} — expected BUY or SELL")

        shares_d = Decimal(str(shares)).quantize(Decimal("0.0001"))
        price_d = Decimal(str(price)).quantize(Decimal("0.0001"))
        if shares_d <= 0:
            raise ValueError(f"shares must be positive, got {shares_d}")
        if price_d <= 0:
            raise ValueError(f"price must be positive, got {price_d}")

        now = executed_at or dt.datetime.now(dt.UTC)
        shadow = self.ensure_shadow(shadow_name)

        pos_row = self._db.execute(
            select(ShadowPosition).where(
                and_(
                    ShadowPosition.shadow_portfolio_id == shadow.id,
                    ShadowPosition.ticker == ticker,
                )
            )
        ).scalar_one_or_none()

        realized_pnl: Decimal | None = None
        created_position = False
        closed_position = False

        if action == "BUY":
            if pos_row is None:
                pos_row = ShadowPosition(
                    id=uuid.uuid4(),
                    shadow_portfolio_id=shadow.id,
                    ticker=ticker,
                    shares=shares_d,
                    avg_cost=price_d,
                    opened_at=now,
                    opened_source=opened_source or rejection_reason or weighting_mode,
                )
                self._db.add(pos_row)
                created_position = True
            else:
                total_cost = (pos_row.shares * pos_row.avg_cost) + (shares_d * price_d)
                total_shares = pos_row.shares + shares_d
                pos_row.avg_cost = (total_cost / total_shares).quantize(
                    Decimal("0.0001")
                )
                pos_row.shares = total_shares
        else:  # SELL
            if pos_row is None:
                _log.warning(
                    "shadow_portfolio.sell_without_position",
                    shadow=shadow_name,
                    ticker=ticker,
                )
                # Record the trade as a zero-shares no-op to preserve audit.
                shares_d = Decimal("0")
            else:
                # Clamp to open shares — shadows can't go short.
                if shares_d > pos_row.shares:
                    shares_d = pos_row.shares
                realized_pnl = ((price_d - pos_row.avg_cost) * shares_d).quantize(
                    Decimal("0.01")
                )
                pos_row.shares = pos_row.shares - shares_d
                if pos_row.shares <= Decimal("0.0001"):
                    self._db.delete(pos_row)
                    closed_position = True

        trade = ShadowTrade(
            id=uuid.uuid4(),
            shadow_portfolio_id=shadow.id,
            ticker=ticker,
            action=action,
            shares=shares_d,
            price=price_d,
            executed_at=now,
            realized_pnl=realized_pnl,
            rejection_reason=rejection_reason,
            weighting_mode=weighting_mode,
        )
        self._db.add(trade)
        self._db.flush()

        _log.info(
            "shadow_portfolio.place_virtual_order",
            shadow=shadow_name,
            ticker=ticker,
            action=action,
            shares=str(shares_d),
            price=str(price_d),
            realized_pnl=None if realized_pnl is None else str(realized_pnl),
        )

        return ShadowOrderResult(
            shadow_portfolio_id=shadow.id,
            trade_id=trade.id,
            ticker=ticker,
            action=action,
            shares=shares_d,
            price=price_d,
            realized_pnl=realized_pnl,
            created_position=created_position,
            closed_position=closed_position,
        )

    # ------------------------------------------------------------------ reads
    def list_shadows(self) -> list[ShadowPortfolio]:
        rows = (
            self._db.execute(select(ShadowPortfolio).order_by(ShadowPortfolio.name))
            .scalars()
            .all()
        )
        return list(rows)

    def get_positions(self, shadow_name: str) -> list[ShadowPosition]:
        shadow = self._db.execute(
            select(ShadowPortfolio).where(ShadowPortfolio.name == shadow_name)
        ).scalar_one_or_none()
        if shadow is None:
            return []
        return list(
            self._db.execute(
                select(ShadowPosition).where(
                    ShadowPosition.shadow_portfolio_id == shadow.id
                )
            )
            .scalars()
            .all()
        )

    def get_trades(
        self,
        shadow_name: str,
        *,
        since: dt.datetime | None = None,
        limit: int | None = None,
    ) -> list[ShadowTrade]:
        shadow = self._db.execute(
            select(ShadowPortfolio).where(ShadowPortfolio.name == shadow_name)
        ).scalar_one_or_none()
        if shadow is None:
            return []
        q = select(ShadowTrade).where(
            ShadowTrade.shadow_portfolio_id == shadow.id
        )
        if since is not None:
            q = q.where(ShadowTrade.executed_at >= since)
        q = q.order_by(ShadowTrade.executed_at)
        if limit is not None:
            q = q.limit(int(limit))
        return list(self._db.execute(q).scalars().all())

    # ---------------------------------------------------------- mark-to-market
    def mark_to_market(
        self,
        shadow_name: str,
        *,
        prices: Mapping[str, Decimal | float | int],
    ) -> ShadowPnL:
        """Compute realized + unrealized P&L for ``shadow_name`` given a
        ticker→price map.  Tickers missing from ``prices`` are marked at
        their avg_cost (zero unrealized contribution).
        """
        shadow = self._db.execute(
            select(ShadowPortfolio).where(ShadowPortfolio.name == shadow_name)
        ).scalar_one_or_none()
        if shadow is None:
            return ShadowPnL(
                shadow_name=shadow_name,
                starting_cash=_DEFAULT_STARTING_CASH,
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                total_pnl=Decimal("0"),
                n_open_positions=0,
                n_trades=0,
            )

        trades = list(
            self._db.execute(
                select(ShadowTrade).where(
                    ShadowTrade.shadow_portfolio_id == shadow.id
                )
            )
            .scalars()
            .all()
        )
        realized = Decimal("0")
        for t in trades:
            if t.realized_pnl is not None:
                realized += Decimal(str(t.realized_pnl))

        positions = list(
            self._db.execute(
                select(ShadowPosition).where(
                    ShadowPosition.shadow_portfolio_id == shadow.id
                )
            )
            .scalars()
            .all()
        )
        unrealized = Decimal("0")
        for p in positions:
            px = prices.get(p.ticker)
            if px is None:
                continue
            px_d = Decimal(str(px))
            unrealized += (px_d - p.avg_cost) * p.shares
        unrealized = unrealized.quantize(Decimal("0.01"))

        return ShadowPnL(
            shadow_name=shadow_name,
            starting_cash=Decimal(str(shadow.starting_cash)),
            realized_pnl=realized.quantize(Decimal("0.01")),
            unrealized_pnl=unrealized,
            total_pnl=(realized + unrealized).quantize(Decimal("0.01")),
            n_open_positions=len(positions),
            n_trades=len(trades),
        )

    # ---------------------------------------------------------- bulk helpers
    def record_rejected_action(
        self,
        *,
        ticker: str,
        shares: Decimal | float | int,
        price: Decimal | float | int,
        rejection_reason: str,
        executed_at: dt.datetime | None = None,
    ) -> ShadowOrderResult:
        """Convenience for the paper_trading hook — pushes a BUY into the
        ``rejected_actions`` shadow with the rejection reason attached.
        """
        return self.place_virtual_order(
            shadow_name="rejected_actions",
            ticker=ticker,
            action="BUY",
            shares=shares,
            price=price,
            rejection_reason=rejection_reason,
            executed_at=executed_at,
        )

    def record_watch_tier(
        self,
        *,
        ticker: str,
        shares: Decimal | float | int,
        price: Decimal | float | int,
        composite_score: float,
        executed_at: dt.datetime | None = None,
    ) -> ShadowOrderResult:
        """BUY into the ``watch_tier`` shadow; ``composite_score`` goes into
        ``rejection_reason`` as a label so dashboards can bucket by composite.
        """
        return self.place_virtual_order(
            shadow_name="watch_tier",
            ticker=ticker,
            action="BUY",
            shares=shares,
            price=price,
            rejection_reason=f"composite={composite_score:.3f}",
            executed_at=executed_at,
        )

    def record_rebalance_shadow(
        self,
        *,
        weighting_mode: str,
        ticker: str,
        action: str,
        shares: Decimal | float | int,
        price: Decimal | float | int,
        executed_at: dt.datetime | None = None,
    ) -> ShadowOrderResult:
        """Push an order into the appropriate ``rebalance_*`` shadow.

        ``weighting_mode`` must be one of ``equal`` / ``score`` /
        ``score_invvol``; the service maps it to the canonical shadow name.
        """
        wm = weighting_mode.strip().lower()
        shadow_name = f"rebalance_{wm}"
        if shadow_name not in REBALANCE_SHADOWS:
            raise ValueError(
                f"unknown weighting_mode {weighting_mode!r} — expected one of "
                f"equal / score / score_invvol"
            )
        return self.place_virtual_order(
            shadow_name=shadow_name,
            ticker=ticker,
            action=action,
            shares=shares,
            price=price,
            weighting_mode=wm,
            executed_at=executed_at,
        )

    def record_stopped_out_continued(
        self,
        *,
        ticker: str,
        shares: Decimal | float | int,
        price: Decimal | float | int,
        stop_reason: str,
        executed_at: dt.datetime | None = None,
    ) -> ShadowOrderResult:
        """BUY into the ``stopped_out_continued`` shadow using the stop
        reason as the opened_source label.
        """
        return self.place_virtual_order(
            shadow_name="stopped_out_continued",
            ticker=ticker,
            action="BUY",
            shares=shares,
            price=price,
            rejection_reason=stop_reason,
            opened_source=stop_reason,
            executed_at=executed_at,
        )
