"""
APIS Read-Only Operator Dashboard.

A lightweight, zero-dependency HTML dashboard served directly from the
FastAPI process.  Displays live system state drawn from ApiAppState.

Mounted at /dashboard by apps/api/main.py.

Design constraints
------------------
- Read-only: no mutations, no order placement.
- No external template-engine dependencies — all HTML is generated inline.
- No authentication for MVP (localhost / trusted-network only).
- Page content refreshes on each request (no client-side polling).
- Routes:
    GET /dashboard/           — full system overview (auto-refreshes every 60 s)
    GET /dashboard/positions  — per-position detail table
    GET /dashboard/backtest   — strategy comparison results (Phase 34)

Spec reference: APIS_MASTER_SPEC.md § 6.1 (API / Dashboard)
"""
from __future__ import annotations

import html
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from apps.api.deps import AppStateDep, SettingsDep

dashboard_router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _esc(value: object) -> str:
    """HTML-escape any value for safe inline display."""
    return html.escape(str(value))


def _section(title: str, body: str) -> str:
    return (
        f'<section class="card">'
        f'<h2>{_esc(title)}</h2>'
        f'{body}'
        f'</section>'
    )


def _kv(label: str, value: object, highlight: str = "") -> str:
    cls = f' class="{_esc(highlight)}"' if highlight else ""
    return f'<div class="kv"><span class="label">{_esc(label)}</span><span{cls}>{_esc(value)}</span></div>'


def _fmt_usd(val: object) -> str:
    """Format a value as USD string; returns '—' on failure."""
    try:
        return f"${float(val):,.2f}"
    except (TypeError, ValueError, InvalidOperation):
        return "—"


def _fmt_pct(val: object, decimals: int = 2) -> str:
    """Format a value as percentage string; returns '—' on failure."""
    try:
        return f"{float(val) * 100:.{decimals}f}%"
    except (TypeError, ValueError, InvalidOperation):
        return "—"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_system_section(state, settings) -> str:
    mode = settings.operating_mode.value
    kill_switch = "ACTIVE ⚠" if settings.is_kill_switch_active else "off"
    kill_cls = "warn" if settings.is_kill_switch_active else ""
    runtime_ks = getattr(state, "kill_switch_active", False)
    runtime_ks_str = "ACTIVE ⚠" if runtime_ks else "off"
    runtime_ks_cls = "warn" if runtime_ks else ""
    activated_by = getattr(state, "kill_switch_activated_by", None) or "—"
    body = (
        _kv("Operating Mode", mode)
        + _kv("Kill Switch (env)", kill_switch, kill_cls)
        + _kv("Kill Switch (runtime)", runtime_ks_str, runtime_ks_cls)
        + _kv("Activated By", activated_by)
        + _kv("Max Positions", settings.max_positions)
        + _kv("Environment", settings.env.value)
    )
    return _section("System Status", body)


def _render_paper_cycle_section(state) -> str:
    cycle_count = getattr(state, "paper_cycle_count", 0)
    last_cycle = getattr(state, "last_paper_cycle_at", None)
    loop_active = getattr(state, "paper_loop_active", False)
    broker_expired = getattr(state, "broker_auth_expired", False)
    broker_expired_at = getattr(state, "broker_auth_expired_at", None)
    paper_errors = len([r for r in getattr(state, "paper_cycle_results", [])
                        if isinstance(r, dict) and r.get("status", "").startswith("error")])

    loop_str = "yes" if loop_active else "no"
    broker_str = "EXPIRED ⚠" if broker_expired else "ok"
    broker_cls = "warn" if broker_expired else ""
    body = (
        _kv("Cycles Completed", cycle_count)
        + _kv("Last Cycle At", str(last_cycle) if last_cycle else "—")
        + _kv("Loop Active", loop_str)
        + _kv("Broker Auth", broker_str, broker_cls)
        + _kv("Broker Expired At", str(broker_expired_at) if broker_expired_at else "—")
        + _kv("Error Cycles", paper_errors)
    )
    return _section("Paper Cycle", body)


def _render_portfolio_section(state) -> str:
    ps = state.portfolio_state
    if ps is None:
        return _section("Portfolio", '<p class="muted">No portfolio data yet.</p>')
    try:
        cash = _fmt_usd(ps.cash)
        equity = _fmt_usd(ps.equity)
        pos_count = len(ps.positions)
        upnl = _fmt_usd(
            sum((p.unrealized_pnl for p in ps.positions.values()), Decimal("0"))
        )
        sod = _fmt_usd(ps.start_of_day_equity) if getattr(ps, "start_of_day_equity", None) else "—"
        hwm = _fmt_usd(ps.high_water_mark) if getattr(ps, "high_water_mark", None) else "—"
        daily_ret = _fmt_pct(ps.daily_pnl_pct)
        dd = _fmt_pct(ps.drawdown_pct)
    except Exception:
        cash = equity = upnl = sod = hwm = daily_ret = dd = "—"
        pos_count = "—"
    body = (
        _kv("Total Equity", equity)
        + _kv("Cash", cash)
        + _kv("SOD Equity", sod)
        + _kv("High Water Mark", hwm)
        + _kv("Daily Return", daily_ret)
        + _kv("Drawdown from HWM", dd)
        + _kv("Unrealized P&L", upnl)
        + _kv("Open Positions", pos_count)
    )
    return _section("Portfolio", body)


def _render_performance_section(state) -> str:
    """Realized P&L summary computed from in-memory closed_trades."""
    closed = getattr(state, "closed_trades", [])
    if not closed:
        return _section("Realized Performance", '<p class="muted">No closed trades yet.</p>')
    try:
        total_pnl = sum(float(getattr(t, "realized_pnl", 0)) for t in closed)
        winners = [t for t in closed if getattr(t, "is_winner", False)]
        win_rate = len(winners) / len(closed) if closed else 0.0
        avg_winner = (
            sum(float(getattr(t, "realized_pnl_pct", 0)) for t in winners) / len(winners)
            if winners else 0.0
        )
        losers = [t for t in closed if not getattr(t, "is_winner", False)]
        avg_loser = (
            sum(float(getattr(t, "realized_pnl_pct", 0)) for t in losers) / len(losers)
            if losers else 0.0
        )
        body = (
            _kv("Total Realized P&L", _fmt_usd(total_pnl),
                "" if total_pnl >= 0 else "warn")
            + _kv("Trade Count", len(closed))
            + _kv("Winners", len(winners))
            + _kv("Losers", len(losers))
            + _kv("Win Rate", _fmt_pct(win_rate))
            + _kv("Avg Winner Return", _fmt_pct(avg_winner))
            + _kv("Avg Loser Return", _fmt_pct(avg_loser))
        )
    except Exception:
        body = '<p class="muted">Could not compute performance metrics.</p>'
    return _section("Realized Performance", body)


def _render_recent_trades_section(state) -> str:
    closed = getattr(state, "closed_trades", [])
    if not closed:
        return _section("Recent Closed Trades", '<p class="muted">No closed trades yet.</p>')
    recent = list(reversed(closed))[:5]
    rows = ""
    for t in recent:
        ticker = _esc(getattr(t, "ticker", "—"))
        action = _esc(str(getattr(t, "action_type", "—")).split(".")[-1])
        pnl = _fmt_usd(getattr(t, "realized_pnl", 0))
        pnl_pct = _fmt_pct(getattr(t, "realized_pnl_pct", 0))
        reason = _esc(str(getattr(t, "reason", "—"))[:30])
        winner = "W" if getattr(t, "is_winner", False) else "L"
        winner_cls = "" if winner == "W" else "warn"
        rows += (
            f'<tr><td>{ticker}</td><td>{action}</td>'
            f'<td>{pnl} ({pnl_pct})</td>'
            f'<td class="{winner_cls}">{winner}</td>'
            f'<td>{reason}</td></tr>'
        )
    body = (
        '<table><thead><tr>'
        '<th>Ticker</th><th>Type</th><th>P&L</th><th>W/L</th><th>Reason</th>'
        '</tr></thead><tbody>'
        + rows
        + '</tbody></table>'
    )
    return _section("Recent Closed Trades (last 5)", body)


def _render_trade_grades_section(state) -> str:
    grades = getattr(state, "trade_grades", [])
    if not grades:
        return _section("Trade Grades", '<p class="muted">No trade grades yet.</p>')
    dist: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for g in grades:
        letter = str(getattr(g, "grade", "?"))
        if letter in dist:
            dist[letter] += 1
    total = len(grades)
    body = _kv("Total Graded", total)
    for letter, count in dist.items():
        pct = f" ({count / total * 100:.0f}%)" if total else ""
        body += _kv(f"Grade {letter}", f"{count}{pct}")
    return _section("Trade Grades", body)


def _render_intel_section(state) -> str:
    regime = getattr(state, "current_macro_regime", "NEUTRAL")
    policy_count = len(getattr(state, "latest_policy_signals", []))
    news_count = len(getattr(state, "latest_news_insights", []))
    fund_count = len(getattr(state, "latest_fundamentals", {}))
    body = (
        _kv("Macro Regime", regime)
        + _kv("Active Policy Signals", policy_count)
        + _kv("News Insights", news_count)
        + _kv("Fundamentals Loaded", fund_count)
    )
    return _section("Intel Feed", body)


def _render_signal_runs_section(state) -> str:
    sig_id = getattr(state, "last_signal_run_id", None)
    rank_id = getattr(state, "last_ranking_run_id", None)
    sig_str = (sig_id[:18] + "…") if sig_id else "—"
    rank_str = (rank_id[:18] + "…") if rank_id else "—"
    body = (
        _kv("Last Signal Run", sig_str)
        + _kv("Last Ranking Run", rank_str)
    )
    return _section("Signal & Ranking Runs", body)


def _render_rankings_section(state) -> str:
    rankings = state.latest_rankings[:5]
    if not rankings:
        return _section("Top Rankings (latest)", '<p class="muted">No rankings available yet.</p>')
    rows = "".join(
        f'<tr><td>{i + 1}</td><td>{_esc(getattr(r, "ticker", "—"))}</td>'
        f'<td>{_esc(getattr(r, "composite_score", "—"))}</td>'
        f'<td>{_esc(getattr(r, "recommended_action", "—"))}</td>'
        f'<td>{_esc(str(getattr(r, "thesis_summary", "—"))[:60])}</td></tr>'
        for i, r in enumerate(rankings)
    )
    body = (
        '<table><thead><tr>'
        '<th>#</th><th>Ticker</th><th>Score</th><th>Action</th><th>Thesis</th>'
        '</tr></thead><tbody>'
        + rows
        + '</tbody></table>'
    )
    return _section("Top Rankings (latest)", body)


def _render_scorecard_section(state) -> str:
    sc = state.latest_scorecard
    if sc is None:
        return _section("Latest Scorecard", '<p class="muted">No scorecard available yet.</p>')
    try:
        scorecard_date = str(getattr(sc, "scorecard_date", "—"))
        net_pnl = _fmt_usd(getattr(sc, "net_pnl", 0))
        hit_rate = _fmt_pct(getattr(sc, "hit_rate", 0))
        mode = getattr(sc, "mode", "—")
        daily_ret = _fmt_pct(getattr(sc, "daily_return_pct", 0))
    except Exception:
        scorecard_date = net_pnl = hit_rate = mode = daily_ret = "—"
    body = (
        _kv("Date", scorecard_date)
        + _kv("Net P&L", net_pnl)
        + _kv("Daily Return", daily_ret)
        + _kv("Hit Rate", hit_rate)
        + _kv("Mode", mode)
    )
    return _section("Latest Scorecard", body)


def _render_alert_section(state) -> str:
    svc = getattr(state, "alert_service", None)
    configured = "yes" if svc is not None else "no"
    body = _kv("Webhook Configured", configured)
    return _section("Alert Service", body)


def _render_improvement_section(state) -> str:
    proposals = state.improvement_proposals
    body = _kv("Pending Proposals", len(proposals))
    return _section("Self-Improvement", body)


def _render_auto_execution_section(state) -> str:
    """Phase 35/36 — auto-execution status, confidence threshold, and recent applied proposals."""
    applied = getattr(state, "applied_executions", [])
    last_run = getattr(state, "last_auto_execute_at", None)
    overrides = getattr(state, "runtime_overrides", {})

    active = [r for r in applied if getattr(r, "status", "") == "applied"]
    rolled_back = [r for r in applied if getattr(r, "status", "") == "rolled_back"]

    # Phase 36: read confidence threshold from config
    try:
        from services.self_improvement.config import SelfImprovementConfig
        _conf_threshold = SelfImprovementConfig().min_auto_execute_confidence
    except Exception:  # noqa: BLE001
        _conf_threshold = None

    body = _kv("Total Executions", len(applied))
    body += _kv("Currently Active", len(active))
    body += _kv("Rolled Back", len(rolled_back))
    body += _kv("Runtime Override Keys", len(overrides))
    body += _kv(
        "Confidence Threshold",
        f"{_conf_threshold:.0%}" if _conf_threshold is not None else "—",
    )
    body += _kv("Last Auto-Execute", last_run.strftime("%H:%M:%S UTC") if last_run else "—")

    # Most recent 3 applied executions
    recent = list(reversed(applied))[:3]
    if recent:
        rows = "".join(
            f"<tr><td>{_esc(r.target_component)}</td>"
            f"<td>{_esc(r.proposal_type)}</td>"
            f"<td>{_esc(r.status)}</td>"
            f"<td>{_esc(getattr(r, 'notes', '')[:40])}</td></tr>"
            for r in recent
        )
        body += (
            "<table><thead><tr><th>Component</th><th>Type</th>"
            "<th>Status</th><th>Notes</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        body += '<p class="muted">No executions yet.</p>'

    return _section("Auto-Execution (Phase 35/36)", body)


def _render_alternative_data_section(state) -> str:
    """Phase 36 — alternative data ingestion status."""
    records = getattr(state, "latest_alternative_data", [])
    if not records:
        return _section(
            "Alternative Data (Phase 36)",
            '<p class="muted">No alternative data ingested yet.</p>',
        )

    # Aggregate by source
    sources: dict[str, int] = {}
    bullish = bearish = neutral = 0
    for r in records:
        src = getattr(r, "source", "unknown")
        src_str = src.value if hasattr(src, "value") else str(src)
        sources[src_str] = sources.get(src_str, 0) + 1
        score = getattr(r, "sentiment_score", 0.0)
        if score > 0.1:
            bullish += 1
        elif score < -0.1:
            bearish += 1
        else:
            neutral += 1

    body = _kv("Total Records", len(records))
    body += _kv("Sources", ", ".join(f"{k}({v})" for k, v in sources.items()))
    body += _kv("Bullish", bullish)
    body += _kv("Bearish", bearish)
    body += _kv("Neutral", neutral)

    # Most recent 5 records
    recent = records[:5]
    rows = "".join(
        f"<tr><td>{_esc(r.ticker)}</td>"
        f"<td>{_esc(getattr(r.source, 'value', str(r.source)))}</td>"
        f"<td>{r.sentiment_score:+.3f}</td>"
        f"<td>{r.mention_count}</td></tr>"
        for r in recent
    )
    body += (
        "<table><thead><tr><th>Ticker</th><th>Source</th>"
        "<th>Sentiment</th><th>Mentions</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return _section("Alternative Data (Phase 36)", body)


def _render_weight_profile_section(state) -> str:
    """Render the active strategy weight profile."""
    profile = getattr(state, "active_weight_profile", None)
    if profile is None:
        body = '<p class="muted">No active weight profile. Run POST /api/v1/signals/weights/optimize to derive weights from backtest data, or equal weighting is in effect.</p>'
        return _section("Strategy Weights (Phase 37)", body)

    weights = getattr(profile, "weights", {})
    sharpe = getattr(profile, "sharpe_metrics", {})
    source = getattr(profile, "source", "unknown")
    name = getattr(profile, "profile_name", "—")
    created = getattr(profile, "created_at", None)

    rows = "".join(
        f'<tr><td>{_esc(k)}</td>'
        f'<td>{v:.4f}</td>'
        f'<td>{sharpe.get(k, "—") if sharpe else "—"}</td></tr>'
        for k, v in sorted(weights.items())
    )
    table = (
        '<table><thead><tr>'
        '<th>Strategy</th><th>Weight</th><th>Sharpe</th>'
        '</tr></thead><tbody>' + rows + '</tbody></table>'
    ) if rows else '<p class="muted">No weight data available.</p>'

    try:
        created_str = created.strftime("%Y-%m-%d %H:%M") if created else "—"
    except Exception:
        created_str = str(created) if created else "—"

    meta = (
        f'<div class="kv"><span class="label">Profile</span><span>{_esc(name)}</span></div>'
        f'<div class="kv"><span class="label">Source</span><span>{_esc(source)}</span></div>'
        f'<div class="kv"><span class="label">Created</span><span>{_esc(created_str)}</span></div>'
    )
    body = meta + table
    return _section("Strategy Weights (Phase 37)", body)


def _render_regime_section(state) -> str:
    """Phase 38 — market regime detection status."""
    result = getattr(state, "current_regime_result", None)
    history: list = getattr(state, "regime_history", [])

    if result is None:
        body = '<p class="muted">No regime detection has run yet. Awaiting 06:20 ET job cycle.</p>'
        return _section("Market Regime (Phase 38)", body)

    try:
        regime_str = result.regime.value if hasattr(result.regime, "value") else str(result.regime)
    except Exception:
        regime_str = str(getattr(result, "regime", "UNKNOWN"))

    confidence = getattr(result, "confidence", 0.0)
    is_override = getattr(result, "is_manual_override", False)
    override_reason = getattr(result, "override_reason", None)
    detected_at = getattr(result, "detected_at", None)

    regime_colour_map = {
        "BULL_TREND": "#4caf50",
        "BEAR_TREND": "#f44336",
        "SIDEWAYS":   "#9e9e9e",
        "HIGH_VOL":   "#ff9800",
    }
    colour = regime_colour_map.get(regime_str, "#4fc3f7")

    try:
        detected_str = detected_at.strftime("%Y-%m-%d %H:%M") if detected_at else "—"
    except Exception:
        detected_str = str(detected_at) if detected_at else "—"

    override_badge = " &nbsp;<span style='color:#ff9800'>[MANUAL OVERRIDE]</span>" if is_override else ""
    meta = (
        f'<div class="kv"><span class="label">Regime</span>'
        f'<span style="color:{_esc(colour)};font-weight:bold">{_esc(regime_str)}{override_badge}</span></div>'
        f'<div class="kv"><span class="label">Confidence</span><span>{confidence:.1%}</span></div>'
        f'<div class="kv"><span class="label">Detected At</span><span>{_esc(detected_str)}</span></div>'
    )
    if is_override and override_reason:
        meta += f'<div class="kv"><span class="label">Override Reason</span><span>{_esc(override_reason)}</span></div>'

    history_note = f'<p style="color:#546e7a;font-size:.8rem;margin-top:.5rem">{len(history)} regime event(s) recorded this session.</p>'

    body = meta + history_note
    return _section("Market Regime (Phase 38)", body)


def _render_correlation_section(state) -> str:
    """Phase 39 — correlation matrix cache status and top portfolio pairs."""
    matrix: dict = getattr(state, "correlation_matrix", {})
    tickers: list = getattr(state, "correlation_tickers", [])
    computed_at = getattr(state, "correlation_computed_at", None)

    if not matrix:
        body = (
            '<p class="muted">No correlation matrix yet. '
            'Awaiting 06:16 ET job cycle.</p>'
        )
        return _section("Correlation Risk (Phase 39)", body)

    try:
        computed_str = computed_at.strftime("%Y-%m-%d %H:%M") if computed_at else "—"
    except Exception:
        computed_str = str(computed_at) if computed_at else "—"

    pair_count = len(matrix) // 2
    meta = (
        _kv("Computed At", computed_str)
        + _kv("Tickers in Matrix", len(tickers))
        + _kv("Unique Pairs", pair_count)
    )

    # Show top-5 highest-correlation pairs from the portfolio positions
    ps = getattr(state, "portfolio_state", None)
    portfolio_tickers: list = list(ps.positions.keys()) if ps and getattr(ps, "positions", None) else []

    if len(portfolio_tickers) >= 2:
        # Collect all pairwise correlations within current portfolio
        seen: set = set()
        portfolio_pairs: list = []
        for a in portfolio_tickers:
            for b in portfolio_tickers:
                if a == b:
                    continue
                key = (min(a, b), max(a, b))
                if key in seen:
                    continue
                seen.add(key)
                val = matrix.get((a, b)) or matrix.get((b, a))
                if val is not None:
                    portfolio_pairs.append((a, b, val))

        if portfolio_pairs:
            portfolio_pairs.sort(key=lambda x: -abs(x[2]))
            rows = ""
            for a, b, corr in portfolio_pairs[:5]:
                colour = "#f44336" if abs(corr) > 0.75 else ("#ff9800" if abs(corr) > 0.50 else "#4caf50")
                rows += (
                    f'<tr><td>{_esc(a)}</td><td>{_esc(b)}</td>'
                    f'<td style="color:{colour}">{corr:+.3f}</td></tr>'
                )
            table = (
                '<table><thead><tr><th>Ticker A</th><th>Ticker B</th>'
                '<th>Corr</th></tr></thead><tbody>'
                + rows + '</tbody></table>'
            )
            meta += table
        else:
            meta += '<p class="muted">No matrix coverage for current positions.</p>'
    else:
        meta += '<p class="muted">Portfolio has &lt;2 positions — no pair analysis.</p>'

    return _section("Correlation Risk (Phase 39)", meta)


def _render_sector_section(state, settings) -> str:
    """Phase 40 — sector allocation table with limit indicators."""
    sector_weights: dict = getattr(state, "sector_weights", {})
    filtered_count: int = getattr(state, "sector_filtered_count", 0)

    try:
        max_pct: float = float(getattr(settings, "max_sector_pct", 0.40))
    except Exception:
        max_pct = 0.40

    if not sector_weights:
        body = (
            '<p class="muted">No sector data yet. '
            "Populated on first paper trading cycle.</p>"
        )
        return _section("Sector Exposure (Phase 40)", body)

    meta = _kv("Max Sector Limit", f"{max_pct * 100:.0f}%")
    if filtered_count:
        meta += _kv("Actions Dropped This Cycle", filtered_count, "warn")

    rows = ""
    for sector in sorted(sector_weights.keys()):
        w = sector_weights[sector]
        pct = w * 100
        at_limit = w >= max_pct
        colour = "#f44336" if at_limit else ("#ff9800" if pct >= max_pct * 80 else "#4caf50")
        flag = " ⚠" if at_limit else ""
        rows += (
            f'<tr><td>{_esc(sector)}</td>'
            f'<td style="color:{colour}">{pct:.1f}%{flag}</td>'
            f'<td>{_esc(f"{max_pct * 100:.0f}%")}</td></tr>'
        )

    table = (
        "<table><thead><tr><th>Sector</th><th>Weight</th><th>Limit</th></tr></thead>"
        "<tbody>" + rows + "</tbody></table>"
    )
    return _section("Sector Exposure (Phase 40)", meta + table)


def _render_liquidity_section(state, settings) -> str:
    """Phase 41 — liquidity screen: gate status and ADV caps per ticker."""
    dollar_volumes: dict = getattr(state, "latest_dollar_volumes", {})
    filtered_count: int = getattr(state, "liquidity_filtered_count", 0)
    computed_at = getattr(state, "liquidity_computed_at", None)

    try:
        min_dv: float = float(getattr(settings, "min_liquidity_dollar_volume", 1_000_000.0))
        max_pct: float = float(getattr(settings, "max_position_as_pct_of_adv", 0.10))
    except Exception:
        min_dv = 1_000_000.0
        max_pct = 0.10

    if not dollar_volumes:
        body = (
            '<p class="muted">No liquidity data yet. '
            "Awaiting 06:17 ET job cycle.</p>"
        )
        return _section("Liquidity Filter (Phase 41)", body)

    try:
        computed_str = computed_at.strftime("%Y-%m-%d %H:%M") if computed_at else "—"
    except Exception:
        computed_str = str(computed_at) if computed_at else "—"

    liquid_count = sum(1 for dv in dollar_volumes.values() if dv >= min_dv)
    illiquid_count = len(dollar_volumes) - liquid_count

    meta = (
        _kv("Computed At", computed_str)
        + _kv("Min ADV Threshold", f"${min_dv:,.0f}")
        + _kv("Max Position % of ADV", f"{max_pct * 100:.0f}%")
        + _kv("Tickers Tracked", len(dollar_volumes))
        + _kv("Liquid", liquid_count)
    )
    if illiquid_count:
        meta += _kv("Illiquid (gated)", illiquid_count, "warn")
    if filtered_count:
        meta += _kv("Actions Dropped This Cycle", filtered_count, "warn")

    # Show bottom-10 by ADV (most likely to be gated)
    sorted_tickers = sorted(dollar_volumes.items(), key=lambda x: x[1])
    rows = ""
    for ticker, dv in sorted_tickers[:10]:
        liquid = dv >= min_dv
        colour = "#4caf50" if liquid else "#f44336"
        flag = "" if liquid else " ✗"
        cap = dv * max_pct
        rows += (
            f'<tr><td>{_esc(ticker)}</td>'
            f'<td style="color:{colour}">${dv:,.0f}{flag}</td>'
            f'<td>${cap:,.0f}</td></tr>'
        )

    table = (
        "<table><thead><tr><th>Ticker</th><th>ADV (20d)</th>"
        "<th>Notional Cap</th></tr></thead><tbody>"
        + rows + "</tbody></table>"
    )
    return _section("Liquidity Filter (Phase 41)", meta + table)


def _render_var_section(state, settings) -> str:
    """Phase 43 — portfolio VaR & CVaR summary with per-ticker breakdown."""
    var_result = getattr(state, "latest_var_result", None)
    var_filtered_count: int = getattr(state, "var_filtered_count", 0)

    try:
        max_var_pct: float = float(getattr(settings, "max_portfolio_var_pct", 0.03))
    except Exception:
        max_var_pct = 0.03

    if var_result is None:
        body = (
            '<p class="muted">No VaR data yet. '
            "Awaiting 06:19 ET job cycle (requires an open portfolio).</p>"
        )
        return _section("Portfolio VaR (Phase 43)", body)

    try:
        computed_str = var_result.computed_at.strftime("%Y-%m-%d %H:%M") if var_result.computed_at else "—"
    except Exception:
        computed_str = str(getattr(var_result, "computed_at", "—"))

    var_95 = float(getattr(var_result, "portfolio_var_95_pct", 0.0))
    var_99 = float(getattr(var_result, "portfolio_var_99_pct", 0.0))
    cvar_95 = float(getattr(var_result, "portfolio_cvar_95_pct", 0.0))
    insufficient = getattr(var_result, "insufficient_data", True)
    lookback = getattr(var_result, "lookback_days", 0)
    positions_count = getattr(var_result, "positions_count", 0)

    limit_breached = (not insufficient) and max_var_pct > 0.0 and var_95 > max_var_pct
    var_colour = "#f44336" if limit_breached else ("#ff9800" if var_95 >= max_var_pct * 0.8 else "#4caf50")
    limit_flag = " ⚠ LIMIT BREACHED" if limit_breached else ""

    meta = (
        _kv("Computed At", computed_str)
        + _kv("Positions Included", positions_count)
        + _kv("Lookback (trading days)", lookback)
        + _kv("Max VaR Limit", f"{max_var_pct * 100:.1f}%")
    )

    if insufficient:
        meta += '<p class="muted" style="margin-top:.5rem">Insufficient data (&lt;30 observations) — VaR estimate not available.</p>'
    else:
        meta += (
            f'<div class="kv"><span class="label">1-Day VaR 95%</span>'
            f'<span style="color:{_esc(var_colour)}">{var_95 * 100:.3f}%{_esc(limit_flag)}</span></div>'
            + _kv("1-Day VaR 99%", f"{var_99 * 100:.3f}%")
            + _kv("1-Day CVaR 95%", f"{cvar_95 * 100:.3f}%")
        )
        if var_filtered_count:
            meta += _kv("OPENs Blocked This Cycle", var_filtered_count, "warn")

    # Per-ticker standalone VaR table
    ticker_var: dict = getattr(var_result, "ticker_var_95", {})
    if ticker_var and not insufficient:
        rows = ""
        for ticker in sorted(ticker_var, key=lambda t: -ticker_var[t]):
            tv = ticker_var[ticker] * 100
            rows += (
                f'<tr><td>{_esc(ticker)}</td>'
                f'<td>{tv:.3f}%</td></tr>'
            )
        table = (
            "<table><thead><tr><th>Ticker</th>"
            "<th>Standalone VaR 95%</th></tr></thead>"
            "<tbody>" + rows + "</tbody></table>"
        )
        meta += table

    return _section("Portfolio VaR (Phase 43)", meta)


def _render_stress_section(state, settings) -> str:
    """Phase 44 — portfolio stress-test scenario summary."""
    stress_result = getattr(state, "latest_stress_result", None)
    stress_blocked: int = getattr(state, "stress_blocked_count", 0)

    try:
        max_loss_pct: float = float(getattr(settings, "max_stress_loss_pct", 0.25))
    except Exception:
        max_loss_pct = 0.25

    if stress_result is None:
        body = (
            '<p class="muted">No stress-test data yet. '
            "Awaiting 06:21 ET job cycle (requires an open portfolio).</p>"
        )
        return _section("Portfolio Stress Test (Phase 44)", body)

    try:
        computed_str = stress_result.computed_at.strftime("%Y-%m-%d %H:%M") if stress_result.computed_at else "—"
    except Exception:
        computed_str = str(getattr(stress_result, "computed_at", "—"))

    no_pos = getattr(stress_result, "no_positions", True)
    if no_pos:
        body = (
            _kv("Computed At", computed_str)
            + '<p class="muted" style="margin-top:.5rem">No open positions — stress test skipped.</p>'
        )
        return _section("Portfolio Stress Test (Phase 44)", body)

    worst_scenario = getattr(stress_result, "worst_case_scenario", "")
    worst_loss_pct = float(getattr(stress_result, "worst_case_loss_pct", 0.0))
    worst_loss_dollar = float(getattr(stress_result, "worst_case_loss_dollar", 0.0))
    positions_count = getattr(stress_result, "positions_count", 0)

    limit_breached = max_loss_pct > 0.0 and worst_loss_pct > max_loss_pct
    loss_colour = "#f44336" if limit_breached else ("#ff9800" if worst_loss_pct >= max_loss_pct * 0.8 else "#4caf50")
    limit_flag = " ⚠ LIMIT BREACHED" if limit_breached else ""

    try:
        from services.risk_engine.stress_test import SCENARIO_LABELS  # noqa: PLC0415
        worst_label = SCENARIO_LABELS.get(worst_scenario, worst_scenario)
    except Exception:
        worst_label = worst_scenario

    meta = (
        _kv("Computed At", computed_str)
        + _kv("Positions Included", positions_count)
        + _kv("Stress Loss Limit", f"{max_loss_pct * 100:.1f}%")
        + _kv("Worst-Case Scenario", worst_label)
        + (
            f'<div class="kv"><span class="label">Worst-Case Loss</span>'
            f'<span style="color:{_esc(loss_colour)}">'
            f'{worst_loss_pct * 100:.1f}%  ({_fmt_usd(-worst_loss_dollar)}){_esc(limit_flag)}'
            f'</span></div>'
        )
    )
    if stress_blocked:
        meta += _kv("OPENs Blocked This Cycle", stress_blocked, "warn")

    # Per-scenario breakdown table
    scenarios = getattr(stress_result, "scenarios", [])
    if scenarios:
        rows = ""
        for sr in scenarios:
            pnl_pct = float(getattr(sr, "portfolio_shocked_pnl_pct", 0.0))
            pnl_dollar = float(getattr(sr, "portfolio_shocked_pnl", 0.0))
            colour = "#f44336" if pnl_pct < -0.20 else ("#ff9800" if pnl_pct < -0.10 else "#4caf50")
            label = _esc(getattr(sr, "scenario_label", getattr(sr, "scenario_name", "")))
            rows += (
                f'<tr><td>{label}</td>'
                f'<td style="color:{colour}">{pnl_pct * 100:.1f}%</td>'
                f'<td style="color:{colour}">{_fmt_usd(pnl_dollar)}</td></tr>'
            )
        table = (
            "<table><thead><tr><th>Scenario</th>"
            "<th>Portfolio Shock %</th><th>Shock USD</th></tr></thead>"
            "<tbody>" + rows + "</tbody></table>"
        )
        meta += table

    return _section("Portfolio Stress Test (Phase 44)", meta)


def _render_earnings_section(state, settings) -> str:
    """Phase 45 — earnings calendar proximity summary."""
    cal = getattr(state, "latest_earnings_calendar", None)
    earnings_filtered: int = getattr(state, "earnings_filtered_count", 0)
    computed_at = getattr(state, "earnings_computed_at", None)

    try:
        max_days: int = int(getattr(settings, "max_earnings_proximity_days", 2))
    except Exception:
        max_days = 2

    if cal is None:
        meta = (
            _kv("Proximity Window", f"{max_days} days" if max_days > 0 else "disabled")
            + _kv("Last Refresh", str(computed_at) if computed_at else "—")
            + '<p class="muted">No earnings calendar data yet (run_earnings_refresh at 06:23 ET).</p>'
        )
        return _section("Earnings Calendar (Phase 45)", meta)

    at_risk = getattr(cal, "at_risk_tickers", [])
    tickers_checked = len(getattr(cal, "entries", {}))
    at_risk_str = ", ".join(sorted(at_risk)) if at_risk else "none"
    gate_active = max_days > 0 and len(at_risk) > 0
    gate_str = f"ACTIVE — {len(at_risk)} ticker(s) blocked" if gate_active else "clear"
    gate_cls = "warn" if gate_active else ""

    meta = (
        _kv("Proximity Window", f"{max_days} calendar days" if max_days > 0 else "disabled")
        + _kv("Last Refresh", str(computed_at)[:19] if computed_at else "—")
        + _kv("Tickers Checked", tickers_checked)
        + _kv("At-Risk Tickers", at_risk_str, gate_cls)
        + _kv("Earnings Gate", gate_str, gate_cls)
    )
    if earnings_filtered:
        meta += _kv("OPENs Blocked This Cycle", earnings_filtered, "warn")

    # At-risk ticker detail table
    if at_risk:
        rows = ""
        entries = getattr(cal, "entries", {})
        for ticker in sorted(at_risk):
            entry = entries.get(ticker)
            if entry is None:
                continue
            edate = str(getattr(entry, "earnings_date", "—"))
            days = getattr(entry, "days_to_earnings", None)
            days_str = str(days) if days is not None else "—"
            rows += (
                f'<tr><td>{_esc(ticker)}</td>'
                f'<td>{_esc(edate)}</td>'
                f'<td style="color:#f44336">{_esc(days_str)} days</td></tr>'
            )
        if rows:
            table = (
                "<table><thead><tr>"
                "<th>Ticker</th><th>Earnings Date</th><th>Days Away</th>"
                "</tr></thead><tbody>" + rows + "</tbody></table>"
            )
            meta += table

    return _section("Earnings Calendar (Phase 45)", meta)


def _render_signal_quality_section(state) -> str:
    """Phase 46 — per-strategy signal quality statistics."""
    report = getattr(state, "latest_signal_quality", None)
    computed_at = getattr(state, "signal_quality_computed_at", None)

    if report is None:
        meta = (
            _kv("Last Update", str(computed_at) if computed_at else "—")
            + '<p class="muted">No signal quality data yet (run_signal_quality_update at 17:20 ET).</p>'
        )
        return _section("Signal Quality (Phase 46)", meta)

    total_outcomes = getattr(report, "total_outcomes_recorded", 0)
    strategies = getattr(report, "strategies_with_data", [])

    meta = (
        _kv("Last Update", str(computed_at)[:19] if computed_at else "—")
        + _kv("Total Outcome Records", total_outcomes)
        + _kv("Strategies Tracked", len(strategies))
    )

    results = getattr(report, "strategy_results", [])
    if results:
        rows = ""
        for r in results:
            win_pct = f"{r.win_rate * 100:.1f}%"
            avg_ret = f"{r.avg_return_pct * 100:+.2f}%"
            sharpe = f"{r.sharpe_estimate:.2f}"
            count = str(r.prediction_count)
            hold = f"{r.avg_hold_days:.1f}d"
            win_cls = "warn" if r.win_rate < 0.40 else ""
            rows += (
                f'<tr>'
                f'<td>{_esc(r.strategy_name)}</td>'
                f'<td>{_esc(count)}</td>'
                f'<td class="{win_cls}">{_esc(win_pct)}</td>'
                f'<td>{_esc(avg_ret)}</td>'
                f'<td>{_esc(sharpe)}</td>'
                f'<td>{_esc(hold)}</td>'
                f'</tr>'
            )
        table = (
            "<table><thead><tr>"
            "<th>Strategy</th><th>Predictions</th><th>Win Rate</th>"
            "<th>Avg Return</th><th>Sharpe Est.</th><th>Avg Hold</th>"
            "</tr></thead><tbody>" + rows + "</tbody></table>"
        )
        meta += table

    return _section("Signal Quality (Phase 46)", meta)


def _render_drawdown_section(state, settings) -> str:
    """Phase 47 — drawdown recovery mode status."""
    drawdown_state: str = getattr(state, "drawdown_state", "NORMAL")
    changed_at = getattr(state, "drawdown_state_changed_at", None)

    try:
        caution_pct: float = float(getattr(settings, "drawdown_caution_pct", 0.05))
        recovery_pct: float = float(getattr(settings, "drawdown_recovery_pct", 0.10))
        size_mult: float = float(getattr(settings, "recovery_mode_size_multiplier", 0.50))
        block_new: bool = bool(getattr(settings, "recovery_mode_block_new_positions", False))
    except Exception:
        caution_pct = 0.05
        recovery_pct = 0.10
        size_mult = 0.50
        block_new = False

    # Compute live drawdown from portfolio state
    ps = getattr(state, "portfolio_state", None)
    current_equity = float(ps.equity) if ps is not None else 0.0
    hwm_raw = getattr(ps, "high_water_mark", None) if ps is not None else None
    hwm = float(hwm_raw) if hwm_raw is not None else current_equity
    if hwm > 0 and current_equity > 0:
        drawdown_pct_live = max(0.0, (hwm - current_equity) / hwm)
    else:
        drawdown_pct_live = 0.0

    state_colour_map = {
        "NORMAL": "#4caf50",
        "CAUTION": "#ff9800",
        "RECOVERY": "#f44336",
    }
    state_colour = state_colour_map.get(drawdown_state, "#4fc3f7")

    try:
        changed_str = changed_at.strftime("%Y-%m-%d %H:%M") if changed_at else "—"
    except Exception:
        changed_str = str(changed_at) if changed_at else "—"

    block_str = "YES — new OPENs blocked" if block_new else "no"
    block_cls = "warn" if block_new and drawdown_state == "RECOVERY" else ""

    meta = (
        f'<div class="kv"><span class="label">Drawdown State</span>'
        f'<span style="color:{_esc(state_colour)};font-weight:bold">{_esc(drawdown_state)}</span></div>'
        + _kv("Current Drawdown", f"{drawdown_pct_live * 100:.2f}%")
        + _kv("High-Water Mark", f"${hwm:,.2f}")
        + _kv("Current Equity", f"${current_equity:,.2f}")
        + _kv("CAUTION Threshold", f"{caution_pct * 100:.1f}%")
        + _kv("RECOVERY Threshold", f"{recovery_pct * 100:.1f}%")
        + _kv("Size Multiplier (RECOVERY)", f"{size_mult * 100:.0f}%")
        + _kv("Block New Positions", block_str, block_cls)
        + _kv("State Changed At", changed_str)
    )
    return _section("Drawdown Recovery (Phase 47)", meta)


def _render_universe_section(state, settings) -> str:
    """Phase 48 — dynamic universe management status."""
    from config.universe import UNIVERSE_TICKERS

    active: list[str] = list(getattr(state, "active_universe", []))
    computed_at = getattr(state, "universe_computed_at", None)
    override_count: int = int(getattr(state, "universe_override_count", 0))
    min_quality: float = float(getattr(settings, "min_universe_signal_quality_score", 0.0))

    try:
        computed_str = computed_at.strftime("%Y-%m-%d %H:%M") if computed_at else "not yet run"
    except Exception:
        computed_str = str(computed_at) if computed_at else "not yet run"

    base_count = len(UNIVERSE_TICKERS)
    active_count = len(active) if active else base_count
    base_set = {t.upper() for t in UNIVERSE_TICKERS}
    active_set = {t.upper() for t in active} if active else base_set

    removed = sorted(base_set - active_set)
    added = sorted(active_set - base_set)

    quality_str = f"{min_quality:.2f}" if min_quality > 0.0 else "disabled"
    diff_cls = "warn" if removed or added else ""
    diff_str = f"+{len(added)} added / −{len(removed)} removed" if (added or removed) else "unchanged"

    body = (
        _kv("Base Universe Size", base_count)
        + _kv("Active Universe Size", active_count)
        + _kv("Active Overrides", override_count)
        + _kv("Quality Pruning", quality_str)
        + _kv("Net Change vs Base", diff_str, diff_cls)
        + _kv("Last Refreshed", computed_str)
    )

    if removed:
        rows = "".join(
            f"<tr><td>{_esc(t)}</td><td>REMOVED</td></tr>" for t in removed
        )
        body += (
            "<details><summary>Removed tickers</summary>"
            f"<table><thead><tr><th>Ticker</th><th>Status</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></details>"
        )
    if added:
        rows = "".join(
            f"<tr><td>{_esc(t)}</td><td>ADDED</td></tr>" for t in added
        )
        body += (
            "<details><summary>Added tickers</summary>"
            f"<table><thead><tr><th>Ticker</th><th>Status</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></details>"
        )

    return _section("Dynamic Universe (Phase 48)", body)


def _render_rebalancing_section(state, settings) -> str:
    """Phase 49 — portfolio rebalancing engine status."""
    enabled: bool = bool(getattr(settings, "enable_rebalancing", True))
    threshold_pct: float = float(getattr(settings, "rebalance_threshold_pct", 0.05))
    min_trade_usd: float = float(getattr(settings, "rebalance_min_trade_usd", 500.0))
    computed_at = getattr(state, "rebalance_computed_at", None)
    drift_count: int = int(getattr(state, "rebalance_drift_count", 0))
    target_weights: dict = getattr(state, "rebalance_targets", {}) or {}

    try:
        computed_str = computed_at.strftime("%Y-%m-%d %H:%M") if computed_at else "not yet run"
    except Exception:
        computed_str = str(computed_at) if computed_at else "not yet run"

    enabled_str = "enabled" if enabled else "disabled"
    drift_cls = "warn" if drift_count > 0 else ""

    body = (
        _kv("Rebalancing", enabled_str)
        + _kv("Drift Threshold", f"{threshold_pct * 100:.1f}%")
        + _kv("Min Trade Size", _fmt_usd(min_trade_usd))
        + _kv("Target Positions", len(target_weights))
        + _kv("Actionable Drifts", drift_count, drift_cls)
        + _kv("Last Checked", computed_str)
    )

    if target_weights:
        # Live drift table from portfolio state
        portfolio_state = getattr(state, "portfolio_state", None)
        positions = getattr(portfolio_state, "positions", {}) if portfolio_state else {}
        equity = float(getattr(portfolio_state, "equity", 0) or 0) if portfolio_state else 0.0

        if equity > 0:
            try:
                from services.risk_engine.rebalancing import RebalancingService
                drift_entries = RebalancingService.compute_drift(
                    positions=positions,
                    target_weights=target_weights,
                    equity=equity,
                    threshold_pct=threshold_pct,
                    min_trade_usd=min_trade_usd,
                )
                rows = "".join(
                    f"<tr>"
                    f"<td>{_esc(e.ticker)}</td>"
                    f"<td>{_fmt_pct(e.target_weight)}</td>"
                    f"<td>{_fmt_pct(e.current_weight)}</td>"
                    f"<td>{_fmt_pct(e.drift_pct, 2)}</td>"
                    f"<td>{_fmt_usd(e.drift_usd)}</td>"
                    f"<td>{_esc(e.action_suggested)}</td>"
                    f"</tr>"
                    for e in sorted(drift_entries, key=lambda x: abs(x.drift_pct), reverse=True)
                )
                body += (
                    "<table><thead><tr>"
                    "<th>Ticker</th><th>Target</th><th>Current</th>"
                    "<th>Drift</th><th>Drift USD</th><th>Action</th>"
                    "</tr></thead>"
                    f"<tbody>{rows}</tbody></table>"
                )
            except Exception:
                pass

    return _section("Portfolio Rebalancing (Phase 49)", body)


def _render_factor_section(state) -> str:
    """Phase 50 — portfolio factor exposure summary."""
    result = getattr(state, "latest_factor_exposure", None)
    computed_at = getattr(state, "factor_exposure_computed_at", None)

    try:
        computed_str = computed_at.strftime("%Y-%m-%d %H:%M") if computed_at else "not yet run"
    except Exception:
        computed_str = str(computed_at) if computed_at else "not yet run"

    if result is None:
        return _section(
            "Factor Exposure (Phase 50)",
            _kv("Status", "No data yet — computed each paper trading cycle")
            + _kv("Last Computed", computed_str),
        )

    fw = result.portfolio_factor_weights
    dominant = _esc(result.dominant_factor)

    def _bar(score: float) -> str:
        """Render a simple text progress bar for a factor score."""
        filled = int(round(score * 20))
        empty = 20 - filled
        bar = "█" * filled + "░" * empty
        return f"{bar} {score:.2f}"

    body = (
        _kv("Last Computed", computed_str)
        + _kv("Positions Analysed", result.position_count)
        + _kv("Dominant Factor", dominant, "ok" if dominant != "UNKNOWN" else "warn")
        + _kv("MOMENTUM", _bar(fw.get("MOMENTUM", 0.5)))
        + _kv("VALUE", _bar(fw.get("VALUE", 0.5)))
        + _kv("GROWTH", _bar(fw.get("GROWTH", 0.5)))
        + _kv("QUALITY", _bar(fw.get("QUALITY", 0.5)))
        + _kv("LOW_VOL", _bar(fw.get("LOW_VOL", 0.5)))
    )

    # Per-ticker breakdown table
    ticker_records = getattr(result, "ticker_scores", [])
    if ticker_records:
        rows = "".join(
            f"<tr>"
            f"<td>{_esc(t.ticker)}</td>"
            f"<td>{t.scores.get('MOMENTUM', 0.5):.2f}</td>"
            f"<td>{t.scores.get('VALUE', 0.5):.2f}</td>"
            f"<td>{t.scores.get('GROWTH', 0.5):.2f}</td>"
            f"<td>{t.scores.get('QUALITY', 0.5):.2f}</td>"
            f"<td>{t.scores.get('LOW_VOL', 0.5):.2f}</td>"
            f"<td>{_esc(t.dominant_factor)}</td>"
            f"</tr>"
            for t in sorted(ticker_records, key=lambda x: x.market_value, reverse=True)
        )
        body += (
            "<table><thead><tr>"
            "<th>Ticker</th><th>MOM</th><th>VAL</th><th>GRW</th><th>QLT</th><th>LVL</th><th>Dominant</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    return _section("Factor Exposure (Phase 50)", body)


def _render_factor_tilt_section(state) -> str:
    """Phase 54 — factor tilt alert event history."""
    events = list(getattr(state, "factor_tilt_events", []))
    last_dominant = getattr(state, "last_dominant_factor", None)

    if not events:
        return _section(
            "Factor Tilt Alerts (Phase 54)",
            _kv("Status", "No tilt events yet — detected each paper trading cycle")
            + _kv("Current Dominant Factor", last_dominant or "—"),
        )

    last_event = events[-1]
    try:
        last_ts = last_event.event_time.strftime("%Y-%m-%d %H:%M")
    except Exception:
        last_ts = str(last_event.event_time)

    body = (
        _kv("Current Dominant Factor", last_dominant or "—", "ok" if last_dominant else "warn")
        + _kv("Total Tilt Events", len(events))
        + _kv("Last Tilt Type", last_event.tilt_type)
        + _kv("Last Tilt Time", last_ts)
        + _kv("Last: Previous Factor", last_event.previous_factor or "—")
        + _kv("Last: New Factor", last_event.new_factor)
        + _kv("Last: Δ Weight", f"{last_event.delta_weight:.3f}")
    )

    # Table of up to 10 most recent events
    recent = list(reversed(events[-10:]))
    if recent:
        rows = ""
        for ev in recent:
            try:
                ts_str = ev.event_time.strftime("%m-%d %H:%M")
            except Exception:
                ts_str = str(ev.event_time)
            rows += (
                f"<tr>"
                f"<td>{_esc(ts_str)}</td>"
                f"<td>{_esc(ev.tilt_type)}</td>"
                f"<td>{_esc(ev.previous_factor or '—')}</td>"
                f"<td>{_esc(ev.new_factor)}</td>"
                f"<td>{ev.delta_weight:.3f}</td>"
                f"</tr>"
            )
        body += (
            "<table><thead><tr>"
            "<th>Time</th><th>Type</th><th>Prev Factor</th><th>New Factor</th><th>Δ Weight</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    return _section("Factor Tilt Alerts (Phase 54)", body)


def _render_fill_quality_section(state) -> str:
    """Phase 52 — order fill quality / slippage summary."""
    summary = getattr(state, "fill_quality_summary", None)
    records = getattr(state, "fill_quality_records", [])
    updated_at = getattr(state, "fill_quality_updated_at", None)

    try:
        updated_str = updated_at.strftime("%Y-%m-%d %H:%M") if updated_at else "not yet run"
    except Exception:
        updated_str = str(updated_at) if updated_at else "not yet run"

    if not records and summary is None:
        return _section(
            "Fill Quality / Slippage (Phase 52)",
            _kv("Status", "No fills captured yet — fills recorded each paper trading cycle")
            + _kv("Last Updated", updated_str),
        )

    # Compute live summary if evening job hasn't run
    if summary is None:
        try:
            from services.fill_quality.service import FillQualityService
            summary = FillQualityService.compute_fill_summary(list(records))
        except Exception:
            summary = None

    body = _kv("Last Updated", updated_str)
    body += _kv("Total Fills Captured", len(records))

    if summary is not None:
        slip_cls = "warn" if float(summary.avg_slippage_usd) > 0 else "ok"
        body += _kv("Buy Fills / Sell Fills", f"{summary.buy_fills} / {summary.sell_fills}")
        body += _kv("Avg Slippage (USD)", _fmt_usd(summary.avg_slippage_usd), slip_cls)
        body += _kv("Median Slippage (USD)", _fmt_usd(summary.median_slippage_usd))
        body += _kv("Worst Slippage (USD)", _fmt_usd(summary.worst_slippage_usd), "warn")
        body += _kv("Best Slippage (USD)", _fmt_usd(summary.best_slippage_usd))
        body += _kv("Avg Slippage (%)", _fmt_pct(summary.avg_slippage_pct, 4))
        if summary.avg_buy_slippage_usd is not None:
            body += _kv("Avg BUY Slippage", _fmt_usd(summary.avg_buy_slippage_usd))
        if summary.avg_sell_slippage_usd is not None:
            body += _kv("Avg SELL Slippage", _fmt_usd(summary.avg_sell_slippage_usd))
        body += _kv("Tickers Covered", ", ".join(summary.tickers_covered) or "—")

    # Recent 10 fills table
    recent = list(records)[-10:]
    if recent:
        rows = "".join(
            f"<tr>"
            f"<td>{_esc(r.ticker)}</td>"
            f"<td>{_esc(r.direction)}</td>"
            f"<td>{_fmt_usd(r.expected_price)}</td>"
            f"<td>{_fmt_usd(r.fill_price)}</td>"
            f"<td>{_fmt_usd(r.slippage_usd)}</td>"
            f"<td>{_fmt_pct(r.slippage_pct, 4)}</td>"
            f"</tr>"
            for r in recent
        )
        body += (
            "<table><thead><tr>"
            "<th>Ticker</th><th>Dir</th><th>Expected</th>"
            "<th>Fill</th><th>Slip $</th><th>Slip %</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    # Phase 55: Alpha-decay attribution addendum
    attr_summary = getattr(state, "fill_quality_attribution_summary", None)
    if attr_summary is not None and getattr(attr_summary, "records_with_alpha", 0) > 0:
        body += (
            _kv("Alpha: Records Enriched", attr_summary.records_with_alpha)
            + _kv(
                "Alpha: Avg N-Day Return",
                f"{attr_summary.avg_alpha_captured_pct:.2%}" if attr_summary.avg_alpha_captured_pct is not None else "—",
            )
            + _kv(
                "Alpha: Avg Slippage/Move",
                f"{attr_summary.avg_slippage_as_pct_of_move:.2%}" if attr_summary.avg_slippage_as_pct_of_move is not None else "—",
            )
            + _kv("Alpha: Positive Trades", attr_summary.positive_alpha_count)
            + _kv("Alpha: Negative Trades", attr_summary.negative_alpha_count)
        )

    return _section("Fill Quality / Slippage (Phase 52+55)", body)


def _render_exit_levels_section(state, settings) -> str:
    """Phase 42 — trailing stop and take-profit exit levels per position."""
    portfolio_state = getattr(state, "portfolio_state", None)
    peak_prices: dict = getattr(state, "position_peak_prices", {})

    try:
        trailing_stop_pct: float = float(getattr(settings, "trailing_stop_pct", 0.0))
        trailing_stop_activation_pct: float = float(getattr(settings, "trailing_stop_activation_pct", 0.03))
        take_profit_pct: float = float(getattr(settings, "take_profit_pct", 0.0))
        stop_loss_pct: float = float(getattr(settings, "stop_loss_pct", 0.07))
    except Exception:
        trailing_stop_pct = 0.0
        trailing_stop_activation_pct = 0.03
        take_profit_pct = 0.0
        stop_loss_pct = 0.07

    meta = (
        _kv("Trailing Stop", f"{trailing_stop_pct * 100:.1f}%" if trailing_stop_pct > 0 else "disabled")
        + _kv("TS Activation Threshold", f"{trailing_stop_activation_pct * 100:.1f}%")
        + _kv("Take-Profit", f"{take_profit_pct * 100:.1f}%" if take_profit_pct > 0 else "disabled")
        + _kv("Stop-Loss", f"{stop_loss_pct * 100:.1f}%")
    )

    if portfolio_state is None or not getattr(portfolio_state, "positions", {}):
        return _section("Exit Levels (Phase 42)", meta + '<p class="muted">No open positions.</p>')

    rows = ""
    for ticker, pos in portfolio_state.positions.items():
        try:
            current = float(pos.current_price)
            entry = float(pos.avg_entry_price)
            pnl_pct = float(pos.unrealized_pnl_pct) if entry > 0 else 0.0
            peak = peak_prices.get(ticker)
            if peak is None:
                peak = max(current, entry)

            stop_level = entry * (1 - stop_loss_pct) if stop_loss_pct > 0 else None
            trailing_level = peak * (1 - trailing_stop_pct) if trailing_stop_pct > 0 else None
            tp_level = entry * (1 + take_profit_pct) if take_profit_pct > 0 else None
            ts_active = pnl_pct >= trailing_stop_activation_pct

            pnl_colour = "#4caf50" if pnl_pct >= 0 else "#f44336"
            ts_active_str = "Y" if ts_active else "N"
            ts_active_colour = "#4caf50" if ts_active else "#9e9e9e"

            rows += (
                f'<tr>'
                f'<td>{_esc(ticker)}</td>'
                f'<td>{_fmt_usd(current)}</td>'
                f'<td>{_fmt_usd(entry)}</td>'
                f'<td style="color:{pnl_colour}">{pnl_pct * 100:+.2f}%</td>'
                f'<td>{_fmt_usd(peak)}</td>'
                f'<td>{_fmt_usd(stop_level) if stop_level is not None else "—"}</td>'
                f'<td>{_fmt_usd(trailing_level) if trailing_level is not None else "—"}</td>'
                f'<td>{_fmt_usd(tp_level) if tp_level is not None else "—"}</td>'
                f'<td style="color:{ts_active_colour}">{ts_active_str}</td>'
                f'</tr>'
            )
        except Exception:
            rows += f'<tr><td>{_esc(ticker)}</td><td colspan="8">—</td></tr>'

    table = (
        "<table><thead><tr>"
        "<th>Ticker</th><th>Current</th><th>Entry</th><th>P&L %</th>"
        "<th>Peak</th><th>Stop-Loss Level</th><th>Trailing Stop Level</th>"
        "<th>Take-Profit Level</th><th>TS Active</th>"
        "</tr></thead><tbody>"
        + rows + "</tbody></table>"
    )
    return _section("Exit Levels (Phase 42)", meta + table)


def _render_readiness_history_table() -> str:
    """Render a trend table of the last 10 readiness snapshots from DB — Phase 56.

    Degrades gracefully to empty string when DB is unavailable.
    """
    try:
        import sqlalchemy as sa
        from infra.db.models.readiness import ReadinessSnapshot
        from infra.db.session import SessionLocal

        with SessionLocal() as session:
            rows = (
                session.execute(
                    sa.select(ReadinessSnapshot)
                    .order_by(ReadinessSnapshot.captured_at.desc())
                    .limit(10)
                )
                .scalars()
                .all()
            )

        if not rows:
            return ""

        _STATUS_COLOR = {"PASS": "#4caf50", "WARN": "#ff9800", "FAIL": "#f44336", "NO_GATE": "#78909c"}
        rows_html = ""
        for snap in rows:
            sc = _STATUS_COLOR.get(snap.overall_status, "#ccc")
            cap = snap.captured_at.strftime("%Y-%m-%d %H:%M") if snap.captured_at else "—"
            rows_html += (
                f'<tr>'
                f'<td style="color:{_esc(sc)};font-weight:bold">{_esc(snap.overall_status)}</td>'
                f'<td>{_esc(cap)}</td>'
                f'<td>{_esc(snap.current_mode)} → {_esc(snap.target_mode)}</td>'
                f'<td style="color:#4caf50">{_esc(snap.pass_count)}</td>'
                f'<td style="color:#ff9800">{_esc(snap.warn_count)}</td>'
                f'<td style="color:#f44336">{_esc(snap.fail_count)}</td>'
                f'</tr>'
            )

        heading = '<p style="font-size:.85rem;font-weight:bold;margin-top:.8rem;color:#90a4ae">Readiness History (last 10 snapshots)</p>'
        table = (
            '<table><thead><tr>'
            '<th>Status</th><th>Captured</th><th>Mode Path</th>'
            '<th>Pass</th><th>Warn</th><th>Fail</th>'
            '</tr></thead><tbody>' + rows_html + '</tbody></table>'
        )
        return heading + table

    except Exception:  # noqa: BLE001
        return ""


def _render_readiness_section(state) -> str:
    """Readiness report section — Phase 53+56."""
    report = getattr(state, "latest_readiness_report", None)
    computed_at = getattr(state, "readiness_report_computed_at", None)

    if report is None:
        return _section(
            "Live-Mode Readiness Report",
            '<p class="muted">No readiness report yet (runs at 18:45 ET weekdays).</p>',
        )

    _STATUS_COLOR = {"PASS": "#4caf50", "WARN": "#ff9800", "FAIL": "#f44336", "NO_GATE": "#78909c"}
    status_color = _STATUS_COLOR.get(report.overall_status, "#ccc")

    header = (
        f'<div style="padding:.4rem 0;font-size:1.1rem;font-weight:bold;color:{_esc(status_color)}">'
        f'{_esc(report.overall_status)}: {_esc(report.current_mode)} → {_esc(report.target_mode)}'
        f'</div>'
        f'<p style="font-size:.85rem;color:#90a4ae;margin:.2rem 0">{_esc(report.recommendation)}</p>'
    )

    counts = (
        f'<div style="font-size:.82rem;color:#90a4ae;margin-bottom:.5rem">'
        f'Pass: <span style="color:#4caf50">{_esc(report.pass_count)}</span> &nbsp;'
        f'Warn: <span style="color:#ff9800">{_esc(report.warn_count)}</span> &nbsp;'
        f'Fail: <span style="color:#f44336">{_esc(report.fail_count)}</span> &nbsp;'
        f'(total {_esc(report.gate_count)} gates)'
        f'</div>'
    )

    if report.gate_rows:
        rows_html = ""
        for row in report.gate_rows:
            rc = _STATUS_COLOR.get(row.status, "#ccc")
            rows_html += (
                f'<tr>'
                f'<td style="color:{_esc(rc)};font-weight:bold">{_esc(row.status)}</td>'
                f'<td>{_esc(row.gate_name)}</td>'
                f'<td>{_esc(row.actual_value)}</td>'
                f'<td>{_esc(row.required_value)}</td>'
                f'</tr>'
            )
        gate_table = (
            '<table><thead><tr>'
            '<th>Status</th><th>Gate</th><th>Actual</th><th>Required</th>'
            '</tr></thead><tbody>' + rows_html + '</tbody></table>'
        )
    else:
        gate_table = '<p class="muted">No gate rows.</p>'

    ts = _esc(computed_at.strftime("%Y-%m-%d %H:%M UTC") if computed_at else "—")
    footer = f'<p style="font-size:.75rem;color:#444;margin-top:.4rem">Generated: {ts}</p>'

    history_html = _render_readiness_history_table()
    body = header + counts + gate_table + footer + history_html
    return _section("Live-Mode Readiness Report (Phase 53+56)", body)


def _render_promoted_versions_section(state) -> str:
    if state.promoted_versions:
        version_rows = "".join(
            f'<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>'
            for k, v in state.promoted_versions.items()
        )
        body = (
            '<table><thead><tr><th>Component</th><th>Version</th></tr></thead>'
            '<tbody>' + version_rows + '</tbody></table>'
        )
    else:
        body = '<p class="muted">No promoted versions recorded.</p>'
    return _section("Promoted Versions", body)


# ---------------------------------------------------------------------------
# CSS + page chrome
# ---------------------------------------------------------------------------

_CSS = """
  body  {font-family: system-ui, sans-serif; background: #0f1117; color: #e0e0e0;
          margin: 0; padding: 1rem 2rem;}
  h1    {color: #4fc3f7; border-bottom: 1px solid #333; padding-bottom: .5rem;}
  h2    {color: #90caf9; font-size: 1rem; margin-bottom: .5rem;}
  .grid {display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 1rem; margin-top: 1rem;}
  .card {background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 6px;
          padding: 1rem;}
  .kv   {display: flex; justify-content: space-between; padding: .2rem 0;
          border-bottom: 1px solid #23253a;}
  .label{color: #90a4ae; font-size: .85rem;}
  .warn {color: #ff5252; font-weight: bold;}
  .muted{color: #555; font-style: italic;}
  table {width: 100%; border-collapse: collapse; font-size: .85rem;}
  th, td{text-align: left; padding: .3rem .4rem; border-bottom: 1px solid #2a2d3a;}
  th    {color: #90a4ae;}
  footer{margin-top: 2rem; color: #444; font-size: .75rem; text-align: center;}
  nav   {margin-bottom: 1rem; font-size: .85rem;}
  nav a {color: #4fc3f7; text-decoration: none; margin-right: 1rem;}
  nav a:hover {text-decoration: underline;}
"""


def _page_wrap(title: str, mode: str, body_html: str, refresh: int = 0) -> str:
    refresh_tag = f'<meta http-equiv="refresh" content="{refresh}">' if refresh > 0 else ""
    nav = (
        '<nav>'
        '<a href="/dashboard/">Overview</a>'
        '<a href="/dashboard/positions">Positions</a>'
        '<a href="/dashboard/backtest">Backtest</a>'
        '</nav>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{refresh_tag}
<title>APIS — {_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>APIS — Autonomous Portfolio Intelligence System</h1>
<p style="color:#546e7a;font-size:.85rem">Read-only operator view &nbsp;·&nbsp;
Mode: <strong style="color:#4fc3f7">{_esc(mode)}</strong></p>
{nav}
<div class="grid">
{body_html}
</div>
<footer>APIS MVP &nbsp;|&nbsp; All values are in-memory state. Data refreshes on each page load.</footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Full overview page renderer
# ---------------------------------------------------------------------------

def _render_page(state, settings) -> str:
    """Build the full overview HTML page from current application state."""
    mode = settings.operating_mode.value
    content = (
        _render_system_section(state, settings)
        + _render_paper_cycle_section(state)
        + _render_portfolio_section(state)
        + _render_performance_section(state)
        + _render_recent_trades_section(state)
        + _render_trade_grades_section(state)
        + _render_rankings_section(state)
        + _render_scorecard_section(state)
        + _render_intel_section(state)
        + _render_signal_runs_section(state)
        + _render_alert_section(state)
        + _render_improvement_section(state)
        + _render_auto_execution_section(state)
        + _render_alternative_data_section(state)
        + _render_weight_profile_section(state)
        + _render_regime_section(state)
        + _render_correlation_section(state)
        + _render_sector_section(state, settings)
        + _render_liquidity_section(state, settings)
        + _render_var_section(state, settings)
        + _render_stress_section(state, settings)
        + _render_earnings_section(state, settings)
        + _render_signal_quality_section(state)
        + _render_drawdown_section(state, settings)
        + _render_universe_section(state, settings)
        + _render_rebalancing_section(state, settings)
        + _render_factor_section(state)
        + _render_factor_tilt_section(state)
        + _render_fill_quality_section(state)
        + _render_readiness_section(state)
        + _render_exit_levels_section(state, settings)
        + _render_promoted_versions_section(state)
    )
    return _page_wrap("Operator Dashboard", mode, content, refresh=60)


# ---------------------------------------------------------------------------
# Positions sub-page renderer
# ---------------------------------------------------------------------------

def _render_positions_page(state, settings) -> str:
    """Build the per-position detail HTML page."""
    mode = settings.operating_mode.value
    ps = state.portfolio_state
    if ps is None or not getattr(ps, "positions", {}):
        content = _section(
            "Open Positions",
            '<p class="muted">No open positions.</p>'
        )
        return _page_wrap("Positions", mode, content, refresh=60)

    rows = ""
    for ticker, pos in ps.positions.items():
        qty = _esc(getattr(pos, "quantity", "—"))
        entry = _fmt_usd(getattr(pos, "avg_entry_price", None))
        price = _fmt_usd(getattr(pos, "current_price", None))
        mv = _fmt_usd(getattr(pos, "market_value", None))
        upnl = _fmt_usd(getattr(pos, "unrealized_pnl", None))
        upnl_pct = _fmt_pct(getattr(pos, "unrealized_pnl_pct", None))
        opened = _esc(str(getattr(pos, "opened_at", "—")))
        rows += (
            f'<tr><td>{_esc(ticker)}</td><td>{qty}</td>'
            f'<td>{entry}</td><td>{price}</td>'
            f'<td>{mv}</td>'
            f'<td>{upnl} ({upnl_pct})</td>'
            f'<td>{opened}</td></tr>'
        )

    table = (
        '<table><thead><tr>'
        '<th>Ticker</th><th>Qty</th><th>Avg Entry</th><th>Price</th>'
        '<th>Market Value</th><th>Unrealized P&L</th><th>Opened At</th>'
        '</tr></thead><tbody>'
        + rows
        + '</tbody></table>'
    )
    content = _section(f"Open Positions ({len(ps.positions)})", table)
    return _page_wrap("Positions", mode, content, refresh=60)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@dashboard_router.get(
    "/",
    response_class=HTMLResponse,
    summary="Read-only operator dashboard overview",
    description=(
        "Returns a self-contained HTML page showing current APIS system state: "
        "portfolio, rankings, scorecard, paper cycle stats, intel feed, "
        "signal runs, trade grades, and closed trade history. "
        "Auto-refreshes every 60 seconds. Read-only — no mutations."
    ),
)
async def dashboard_home(state: AppStateDep, settings: SettingsDep) -> str:
    """Render and return the operator dashboard HTML page."""
    return _render_page(state, settings)


@dashboard_router.get(
    "/positions",
    response_class=HTMLResponse,
    summary="Per-position detail view",
    description=(
        "Returns a self-contained HTML page showing the current open positions "
        "with quantity, entry price, current price, market value, and unrealized P&L. "
        "Auto-refreshes every 60 seconds. Read-only — no mutations."
    ),
)
async def dashboard_positions(state: AppStateDep, settings: SettingsDep) -> str:
    """Render and return the per-position detail HTML page."""
    return _render_positions_page(state, settings)


# ---------------------------------------------------------------------------
# Backtest comparison sub-page renderer
# ---------------------------------------------------------------------------

def _render_backtest_page(state, settings) -> str:
    """Build the strategy backtest comparison HTML page.

    Queries the DB for recent comparison groups (newest 5) and renders a
    table of per-strategy metrics for each.  Degrades gracefully when the
    DB is unavailable.
    """
    mode = settings.operating_mode.value
    session_factory = getattr(state, "_session_factory", None)
    if session_factory is None:
        content = _section(
            "Strategy Backtest Comparisons",
            '<p class="muted">DB unavailable — no backtest data to display.</p>'
            '<p class="muted">Use POST /api/v1/backtest/compare to run a comparison.</p>',
        )
        return _page_wrap("Backtest", mode, content)

    try:
        import sqlalchemy as sa
        from infra.db.models.backtest import BacktestRun

        with session_factory() as session:
            # Latest 5 comparison groups by newest created_at
            subq = (
                sa.select(
                    BacktestRun.comparison_id,
                    sa.func.max(BacktestRun.created_at).label("max_ts"),
                )
                .group_by(BacktestRun.comparison_id)
                .order_by(sa.func.max(BacktestRun.created_at).desc())
                .limit(5)
                .subquery()
            )
            rows = session.execute(
                sa.select(BacktestRun).where(
                    BacktestRun.comparison_id.in_(
                        sa.select(subq.c.comparison_id)
                    )
                ).order_by(BacktestRun.created_at.desc())
            ).scalars().all()

        if not rows:
            content = _section(
                "Strategy Backtest Comparisons",
                '<p class="muted">No comparison runs yet.</p>'
                '<p class="muted">Use POST /api/v1/backtest/compare to run a comparison.</p>',
            )
            return _page_wrap("Backtest", mode, content)

        # Group rows by comparison_id preserving newest-first order
        groups: dict[str, list] = {}
        order: list[str] = []
        for row in rows:
            if row.comparison_id not in groups:
                groups[row.comparison_id] = []
                order.append(row.comparison_id)
            groups[row.comparison_id].append(row)

        sections = ""
        for cid in order:
            group = groups[cid]
            rep = group[0]
            cid_short = cid[:8]
            created = str(rep.created_at)[:16] if rep.created_at else "—"
            table_rows = ""
            for r in sorted(group, key=lambda x: x.strategy_name):
                ret = f"{r.total_return_pct:+.2f}%" if r.total_return_pct is not None else "—"
                sharpe = f"{r.sharpe_ratio:.2f}" if r.sharpe_ratio is not None else "—"
                dd = f"{r.max_drawdown_pct:.2f}%" if r.max_drawdown_pct is not None else "—"
                wr = f"{r.win_rate * 100:.1f}%" if r.win_rate is not None else "—"
                trades = str(r.total_trades)
                status = _esc(r.status)
                table_rows += (
                    f'<tr><td>{_esc(r.strategy_name)}</td>'
                    f'<td>{_esc(ret)}</td>'
                    f'<td>{_esc(sharpe)}</td>'
                    f'<td>{_esc(dd)}</td>'
                    f'<td>{_esc(wr)}</td>'
                    f'<td>{_esc(trades)}</td>'
                    f'<td>{status}</td></tr>'
                )
            table = (
                '<table><thead><tr>'
                '<th>Strategy</th><th>Return</th><th>Sharpe</th>'
                '<th>Max DD</th><th>Win Rate</th><th>Trades</th><th>Status</th>'
                '</tr></thead><tbody>'
                + table_rows
                + '</tbody></table>'
            )
            title = (
                f"Comparison {cid_short}… &nbsp;·&nbsp; "
                f"{_esc(str(rep.start_date))} → {_esc(str(rep.end_date))} &nbsp;·&nbsp; "
                f"{rep.ticker_count} tickers &nbsp;·&nbsp; {created}"
            )
            sections += f'<section class="card"><h2>{title}</h2>{table}</section>'

        return _page_wrap("Backtest Comparisons", mode, sections)

    except Exception:  # noqa: BLE001
        content = _section(
            "Strategy Backtest Comparisons",
            '<p class="muted">Could not load backtest data from DB.</p>',
        )
        return _page_wrap("Backtest", mode, content)


@dashboard_router.get(
    "/backtest",
    response_class=HTMLResponse,
    summary="Strategy backtest comparison results",
    description=(
        "Returns a self-contained HTML page showing recent strategy backtest "
        "comparison results (return, Sharpe, drawdown, win rate per strategy). "
        "Read-only — no mutations."
    ),
)
async def dashboard_backtest(state: AppStateDep, settings: SettingsDep) -> str:
    """Render and return the backtest comparison HTML page."""
    return _render_backtest_page(state, settings)
