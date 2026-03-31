"""
Portfolio Stress Testing + Scenario Analysis — Phase 44.

StressTestService applies discrete historical shock scenarios to the current
portfolio to estimate P&L under extreme market conditions.  Unlike VaR
(which is a statistical backward-looking metric), stress tests ask:
"what would happen to THIS portfolio if THAT crisis happened again?"

Four built-in scenarios use sector-level return shocks calibrated to the
actual peak-to-trough drawdowns of each sector during the named episode.

Design rules
------------
- Stateless: every method is pure (no side-effects, no DB access).
- Shock fractions are applied to each position's market_value using the
  sector tag from config.universe.TICKER_SECTOR; tickers absent from that
  map fall into "other".
- filter_for_stress_limit() applies to OPEN actions only — CLOSE and TRIM
  actions are never blocked.
- Uses dataclasses.replace() when adjusting PortfolioAction objects.
- structlog only — no print() calls.
- no_positions=True when portfolio is empty; callers treat this as
  "no stress signal".

Scenario calibration notes
--------------------------
Financial Crisis (2008-09)
  Peak-to-trough (S&P 500: -55%).  Financials were the epicentre (-78%);
  energy dropped sharply on the demand collapse (-45%); technology fell
  hard but less than the market (-55%); healthcare and consumer staples
  were defensive (-25%).

COVID Crash (Feb-Mar 2020)
  Peak-to-trough (S&P 500: -34%, 33 trading days).  Energy was crushed by
  the demand shock (-60%); consumer/travel/hospitality hardest hit (-45%);
  tech sold off but recovered quickly (-25%); healthcare was defensive (-15%).

Rate Shock / Growth Sell-off (2022)
  Peak-to-trough (Nasdaq: -33%, S&P: -25%).  Technology / high-multiple
  growth stocks bore the brunt (-35%); energy was the only winner (+25% on
  commodity supply shock); financials were mildly positive on higher NIM;
  consumer/discretionary fell on earnings compression (-20%).

Dotcom Bust (2000-02)
  Peak-to-trough (Nasdaq: -78%).  Technology / internet names collapsed
  (-75%); financials, energy, and consumer were relatively defensive;
  healthcare was neutral.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from config.settings import Settings
    from services.portfolio_engine.models import PortfolioAction

log = structlog.get_logger(__name__)

# Sector label for tickers absent from the universe registry
_UNKNOWN_SECTOR = "other"

# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

#: Shock fractions per sector (negative = loss, positive = gain).
#: All values are fractions of position market value (e.g. -0.55 = -55%).
SCENARIO_SHOCKS: dict[str, dict[str, float]] = {
    "financial_crisis_2008": {
        "technology": -0.55,
        "healthcare":  -0.25,
        "financials":  -0.78,
        "energy":      -0.45,
        "consumer":    -0.35,
        "other":       -0.50,
    },
    "covid_crash_2020": {
        "technology":  -0.25,
        "healthcare":  -0.15,
        "financials":  -0.40,
        "energy":      -0.60,
        "consumer":    -0.45,
        "other":       -0.35,
    },
    "rate_shock_2022": {
        "technology":  -0.35,
        "healthcare":  -0.15,
        "financials":  -0.05,
        "energy":      +0.25,
        "consumer":    -0.20,
        "other":       -0.20,
    },
    "dotcom_bust_2001": {
        "technology":  -0.75,
        "healthcare":  -0.10,
        "financials":  -0.20,
        "energy":      -0.15,
        "consumer":    -0.20,
        "other":       -0.30,
    },
}

#: Human-readable scenario labels
SCENARIO_LABELS: dict[str, str] = {
    "financial_crisis_2008": "Financial Crisis (2008–09)",
    "covid_crash_2020":      "COVID Crash (Feb–Mar 2020)",
    "rate_shock_2022":       "Rate Shock / Growth Sell-Off (2022)",
    "dotcom_bust_2001":      "Dotcom Bust (2000–02)",
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    """P&L impact of applying a single shock scenario to the portfolio.

    All ``_pnl_pct`` fields are fractions of equity (e.g. -0.30 = -30%).
    All ``_pnl_dollar`` / ``_pnl`` fields are USD amounts
    (negative = portfolio loss).
    """

    scenario_name: str                        # machine key, e.g. "financial_crisis_2008"
    scenario_label: str                       # human-readable name
    portfolio_shocked_pnl: float              # total portfolio P&L in USD (negative = loss)
    portfolio_shocked_pnl_pct: float          # portfolio P&L as fraction of equity (negative = loss)
    equity: float                             # equity used in the computation
    positions_count: int
    ticker_shocked_pnl: dict = field(default_factory=dict)      # ticker → USD P&L
    ticker_shocked_pnl_pct: dict = field(default_factory=dict)  # ticker → fraction-of-equity P&L


@dataclass
class StressTestResult:
    """Aggregated result from running all four scenarios.

    ``worst_case_loss_pct`` is a positive fraction representing the largest
    potential loss across all scenarios.  The paper cycle gates new OPENs
    when this exceeds ``settings.max_stress_loss_pct``.
    """

    computed_at: dt.datetime
    equity: float
    positions_count: int
    scenarios: list[ScenarioResult] = field(default_factory=list)
    worst_case_scenario: str = ""           # scenario_name of the worst result
    worst_case_loss_pct: float = 0.0        # positive fraction (e.g. 0.45 = 45% loss)
    worst_case_loss_dollar: float = 0.0     # USD (positive = magnitude of loss)
    no_positions: bool = False              # True when portfolio is empty


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class StressTestService:
    """Apply historical-scenario stress shocks to the current portfolio.

    All methods are classmethods / staticmethods — no instance state.
    """

    # ── Sector lookup ──────────────────────────────────────────────────────

    @staticmethod
    def _get_sector(ticker: str) -> str:
        """Return the sector tag for *ticker*; falls back to 'other'."""
        try:
            from config.universe import TICKER_SECTOR  # noqa: PLC0415
            return TICKER_SECTOR.get(ticker, _UNKNOWN_SECTOR)
        except Exception:  # noqa: BLE001
            return _UNKNOWN_SECTOR

    # ── Single scenario ────────────────────────────────────────────────────

    @classmethod
    def apply_scenario(
        cls,
        positions: dict,     # ticker → position with market_value attr
        equity: float,
        scenario_name: str,
    ) -> ScenarioResult:
        """Apply a named shock scenario to the portfolio.

        For each position the shocked P&L is:
            shocked_pnl_i = market_value_i × sector_shock_fraction_i

        The portfolio-level shocked P&L is the sum across all positions.

        Args:
            positions:     Dict of ticker → position object (needs market_value).
            equity:        Total portfolio equity (used for weight computation).
            scenario_name: Key from SCENARIO_SHOCKS, e.g. 'financial_crisis_2008'.

        Returns:
            ScenarioResult with per-ticker and portfolio-level shocked P&L.
            If scenario_name is unknown, all shocks default to -0.30.
        """
        shocks = SCENARIO_SHOCKS.get(scenario_name, {s: -0.30 for s in [
            "technology", "healthcare", "financials", "energy", "consumer", "other"
        ]})
        label = SCENARIO_LABELS.get(scenario_name, scenario_name)

        ticker_pnl: dict[str, float] = {}
        ticker_pnl_pct: dict[str, float] = {}
        total_pnl = 0.0

        for ticker, pos in positions.items():
            mv = float(getattr(pos, "market_value", 0.0))
            sector = cls._get_sector(ticker)
            shock = shocks.get(sector, shocks.get("other", -0.30))
            pnl = mv * shock
            ticker_pnl[ticker] = round(pnl, 2)
            ticker_pnl_pct[ticker] = round(pnl / equity, 6) if equity > 0.0 else 0.0
            total_pnl += pnl

        portfolio_pnl_pct = total_pnl / equity if equity > 0.0 else 0.0

        return ScenarioResult(
            scenario_name=scenario_name,
            scenario_label=label,
            portfolio_shocked_pnl=round(total_pnl, 2),
            portfolio_shocked_pnl_pct=round(portfolio_pnl_pct, 6),
            equity=equity,
            positions_count=len(positions),
            ticker_shocked_pnl=ticker_pnl,
            ticker_shocked_pnl_pct=ticker_pnl_pct,
        )

    # ── All scenarios ──────────────────────────────────────────────────────

    @classmethod
    def run_all_scenarios(
        cls,
        positions: dict,
        equity: float,
    ) -> StressTestResult:
        """Run all four built-in scenarios and identify the worst case.

        Args:
            positions: Dict of ticker → position (needs market_value).
            equity:    Total portfolio equity.

        Returns:
            StressTestResult with all scenario results and worst-case summary.
            When positions is empty, returns a no_positions=True result.
        """
        now = dt.datetime.now(dt.timezone.utc)

        if not positions or equity <= 0.0:
            return StressTestResult(
                computed_at=now,
                equity=equity,
                positions_count=0,
                scenarios=[],
                worst_case_scenario="",
                worst_case_loss_pct=0.0,
                worst_case_loss_dollar=0.0,
                no_positions=True,
            )

        scenario_results: list[ScenarioResult] = []
        for scenario_name in SCENARIO_SHOCKS:
            result = cls.apply_scenario(positions, equity, scenario_name)
            scenario_results.append(result)
            log.info(
                "stress_scenario_computed",
                scenario=scenario_name,
                portfolio_shocked_pnl_pct=round(result.portfolio_shocked_pnl_pct * 100, 2),
            )

        # Identify worst case (most negative P&L)
        worst = min(scenario_results, key=lambda r: r.portfolio_shocked_pnl)
        worst_loss_pct = max(0.0, -worst.portfolio_shocked_pnl_pct)
        worst_loss_dollar = max(0.0, -worst.portfolio_shocked_pnl)

        log.info(
            "stress_test_complete",
            positions_count=len(positions),
            worst_scenario=worst.scenario_name,
            worst_case_loss_pct=round(worst_loss_pct * 100, 2),
        )

        return StressTestResult(
            computed_at=now,
            equity=equity,
            positions_count=len(positions),
            scenarios=scenario_results,
            worst_case_scenario=worst.scenario_name,
            worst_case_loss_pct=worst_loss_pct,
            worst_case_loss_dollar=worst_loss_dollar,
            no_positions=False,
        )

    # ── Paper cycle gate ───────────────────────────────────────────────────

    @staticmethod
    def filter_for_stress_limit(
        actions: list,                   # list[PortfolioAction]
        stress_result: "StressTestResult",
        settings: "Settings",
    ) -> tuple[list, int]:
        """Block OPEN actions when worst-case stress loss exceeds the limit.

        CLOSE and TRIM actions always pass through — the gate must never
        block risk-reducing exits.  When no positions exist or the limit is
        not configured, all actions pass through unchanged.

        Args:
            actions:       Proposed list of PortfolioAction objects.
            stress_result: Latest StressTestResult from run_stress_test.
            settings:      Settings instance carrying max_stress_loss_pct.

        Returns:
            Tuple of (filtered_actions, blocked_count).
        """
        from services.portfolio_engine.models import ActionType  # noqa: PLC0415

        max_loss: float = float(getattr(settings, "max_stress_loss_pct", 0.25))

        # No positions or gate disabled → pass through all
        if stress_result.no_positions or max_loss <= 0.0:
            return actions, 0

        # Limit not breached → pass through all
        if stress_result.worst_case_loss_pct <= max_loss:
            return actions, 0

        log.warning(
            "stress_gate_applied",
            worst_case_scenario=stress_result.worst_case_scenario,
            worst_case_loss_pct=round(stress_result.worst_case_loss_pct * 100, 2),
            max_stress_loss_pct=round(max_loss * 100, 2),
        )

        filtered: list = []
        blocked = 0
        for action in actions:
            if action.action_type == ActionType.OPEN:
                blocked += 1
                log.info(
                    "stress_gate_open_blocked",
                    ticker=action.ticker,
                    worst_case_loss_pct=round(stress_result.worst_case_loss_pct * 100, 2),
                )
            else:
                filtered.append(action)

        return filtered, blocked
