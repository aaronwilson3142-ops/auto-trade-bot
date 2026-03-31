"""Prometheus-compatible metrics endpoint.

Exposes a ``GET /metrics`` route that returns a plain-text Prometheus scrape
payload covering the key APIS operational observability signals.

No external prometheus_client dependency is required — the metrics are
formatted manually to the Prometheus text exposition format (simple, zero-dep).

Metrics emitted
---------------
``apis_operating_mode``           gauge  1 for the current mode string
``apis_kill_switch_active``       gauge  1=on, 0=off
``apis_portfolio_positions``      gauge  number of open positions
``apis_portfolio_equity_usd``     gauge  total portfolio equity in USD
``apis_portfolio_cash_usd``       gauge  available cash in USD
``apis_latest_ranking_count``     gauge  number of ranked results in state
``apis_paper_loop_active``        gauge  1=active, 0=inactive
``apis_paper_cycle_count``        gauge  number of paper cycle results stored
``apis_improvement_proposal_count`` gauge  number of pending proposals
``apis_evaluation_history_count`` gauge  number of scorecard entries

Spec references
---------------
- APIS_MASTER_SPEC.md § 6.1 (API / Dashboard component)
- 04_APIS_BUILD_RUNBOOK.md § 10 (Tooling — monitoring/observability)
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from apps.api.deps import AppStateDep, SettingsDep

router = APIRouter(tags=["Metrics"])


# ── Prometheus text format helpers ─────────────────────────────────────────────

def _metric(name: str, value: float | int, labels: dict[str, str] | None = None) -> str:
    """Format a single Prometheus gauge metric line."""
    if labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        return f'{name}{{{label_str}}} {value}'
    return f"{name} {value}"


def _comment(text: str) -> str:
    return f"# {text}"


# ── Route ──────────────────────────────────────────────────────────────────────

@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(
    state: AppStateDep,
    settings: SettingsDep,
) -> str:
    """Return a Prometheus text-format scrape payload.

    Compatible with the standard Prometheus text exposition format 0.0.4.
    Use ``prometheus.io/scrape: "true"`` in your Kubernetes or Grafana config.
    """
    lines: list[str] = []
    now_ts = int(dt.datetime.now(dt.UTC).timestamp() * 1000)

    def emit(help_text: str, metric_type: str, name: str, value: float | int,
             labels: dict[str, str] | None = None) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")
        lines.append(f"{_metric(name, value, labels)} {now_ts}")

    # ── Operating mode ────────────────────────────────────────────────────────
    mode = settings.operating_mode.value
    emit(
        "Current APIS operating mode encoded as label",
        "gauge",
        "apis_operating_mode",
        1,
        {"mode": mode},
    )

    # ── Kill switch ───────────────────────────────────────────────────────────
    effective_kill = getattr(state, "kill_switch_active", False) or settings.kill_switch
    emit(
        "Whether the APIS kill switch is active (1=on, 0=off)",
        "gauge",
        "apis_kill_switch_active",
        1 if effective_kill else 0,
    )

    # ── Portfolio ─────────────────────────────────────────────────────────────
    portfolio = state.portfolio_state
    if portfolio is not None:
        try:
            position_count = portfolio.position_count
        except Exception:  # noqa: BLE001
            position_count = len(getattr(portfolio, "positions", {}))

        emit("Number of open portfolio positions", "gauge",
             "apis_portfolio_positions", position_count)

        try:
            equity = float(portfolio.equity)
        except Exception:  # noqa: BLE001
            equity = 0.0
        emit("Total portfolio equity in USD", "gauge",
             "apis_portfolio_equity_usd", equity)

        try:
            cash = float(portfolio.cash)
        except Exception:  # noqa: BLE001
            cash = 0.0
        emit("Available cash in USD", "gauge", "apis_portfolio_cash_usd", cash)
    else:
        emit("Number of open portfolio positions", "gauge",
             "apis_portfolio_positions", 0)
        emit("Total portfolio equity in USD", "gauge",
             "apis_portfolio_equity_usd", 0.0)
        emit("Available cash in USD", "gauge", "apis_portfolio_cash_usd", 0.0)

    # ── Rankings ──────────────────────────────────────────────────────────────
    emit(
        "Number of ranked results currently in ApiAppState",
        "gauge",
        "apis_latest_ranking_count",
        len(state.latest_rankings),
    )

    # ── Paper loop ────────────────────────────────────────────────────────────
    emit(
        "Whether the paper trading loop has been activated (1=yes, 0=no)",
        "gauge",
        "apis_paper_loop_active",
        1 if getattr(state, "paper_loop_active", False) else 0,
    )
    emit(
        "Number of completed paper trading cycle result records",
        "gauge",
        "apis_paper_cycle_count",
        len(getattr(state, "paper_cycle_results", [])),
    )

    # ── Self-improvement ──────────────────────────────────────────────────────
    emit(
        "Number of pending self-improvement proposals",
        "gauge",
        "apis_improvement_proposal_count",
        len(state.improvement_proposals),
    )

    # ── Evaluation history ────────────────────────────────────────────────────
    emit(
        "Number of daily scorecard entries in evaluation history",
        "gauge",
        "apis_evaluation_history_count",
        len(state.evaluation_history),
    )

    # ── Broker auth token expiry ──────────────────────────────────────────────
    emit(
        "1 if broker authentication token has expired and needs manual refresh (0=ok)",
        "gauge",
        "apis_broker_auth_expired",
        1 if getattr(state, "broker_auth_expired", False) else 0,
    )

    # ── Macro regime ──────────────────────────────────────────────────────────
    macro_regime = getattr(state, "current_macro_regime", "NEUTRAL") or "NEUTRAL"
    emit(
        "Current APIS macro regime encoded as label (value always 1)",
        "gauge",
        "apis_macro_regime",
        1,
        {"regime": macro_regime},
    )

    # ── Active policy signals ─────────────────────────────────────────────────
    emit(
        "Number of active policy signals currently in ApiAppState",
        "gauge",
        "apis_active_signals_count",
        len(getattr(state, "latest_policy_signals", [])),
    )

    # ── Active news insights ──────────────────────────────────────────────────
    emit(
        "Number of active news insights currently in ApiAppState",
        "gauge",
        "apis_news_insights_count",
        len(getattr(state, "latest_news_insights", [])),
    )

    # ── Realized / unrealized P&L + daily return ───────────────────────────────
    _closed = getattr(state, "closed_trades", [])
    _realized_pnl = round(sum(float(t.realized_pnl) for t in _closed), 2)
    emit(
        "Total realized P&L in USD from closed trades (session)",
        "gauge",
        "apis_realized_pnl_usd",
        _realized_pnl,
    )

    if portfolio is not None:
        try:
            _unrealized = round(
                sum(float(p.unrealized_pnl) for p in portfolio.positions.values()), 2
            )
        except Exception:  # noqa: BLE001
            _unrealized = 0.0
        try:
            _sod = float(portfolio.start_of_day_equity) if portfolio.start_of_day_equity else float(portfolio.equity)
            _eq = float(portfolio.equity)
            _daily_ret = round(((_eq - _sod) / _sod * 100) if _sod > 0 else 0.0, 4)
        except Exception:  # noqa: BLE001
            _unrealized = 0.0
            _daily_ret = 0.0
    else:
        _unrealized = 0.0
        _daily_ret = 0.0

    emit(
        "Total unrealized P&L in USD from current open positions",
        "gauge",
        "apis_unrealized_pnl_usd",
        _unrealized,
    )
    emit(
        "Daily return percentage vs start-of-day equity",
        "gauge",
        "apis_daily_return_pct",
        _daily_ret,
    )

    return "\n".join(lines) + "\n"
