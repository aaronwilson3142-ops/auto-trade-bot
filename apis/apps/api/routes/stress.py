"""
Portfolio Stress Testing API routes (Phase 44).

GET /api/v1/portfolio/stress-test
    Returns the latest stress-test result across all four built-in historical
    scenarios (2008 crisis, COVID 2020, rate shock 2022, dotcom bust 2001)
    computed by run_stress_test at 06:21 ET.

GET /api/v1/portfolio/stress-test/{scenario}
    Returns the detailed result for a single named scenario.

Both endpoints serve from in-memory app_state — no DB access on the request
path.  Data is populated by the run_stress_test job at 06:21 ET.
"""
from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.stress import (
    ScenarioResultSchema,
    StressScenarioDetailResponse,
    StressTestSummaryResponse,
)
from services.risk_engine.stress_test import SCENARIO_LABELS

stress_router = APIRouter(prefix="/portfolio", tags=["Stress Test"])


@stress_router.get(
    "/stress-test",
    response_model=StressTestSummaryResponse,
    summary="Portfolio stress-test summary across all scenarios",
    description=(
        "Returns the latest stress-test result across all four built-in historical "
        "shock scenarios.  The worst_case fields identify which scenario imposes the "
        "largest estimated loss on the current portfolio.  "
        "Data is populated by run_stress_test at 06:21 ET.  "
        "Returns an empty/zeroed response when no stress test has run yet."
    ),
)
def get_portfolio_stress_test(
    state: AppStateDep,
    settings: SettingsDep,
) -> StressTestSummaryResponse:
    """Return portfolio stress-test summary from in-memory app_state."""
    stress_result = getattr(state, "latest_stress_result", None)
    max_loss_pct: float = float(getattr(settings, "max_stress_loss_pct", 0.25))

    if stress_result is None:
        return StressTestSummaryResponse(
            computed_at=None,
            equity=0.0,
            positions_count=0,
            no_positions=True,
            worst_case_scenario="",
            worst_case_scenario_label="",
            worst_case_loss_pct=0.0,
            worst_case_loss_dollar=0.0,
            max_stress_loss_pct=round(max_loss_pct * 100, 2),
            stress_limit_breached=False,
            scenarios=[],
        )

    worst_label = SCENARIO_LABELS.get(
        stress_result.worst_case_scenario,
        stress_result.worst_case_scenario,
    )

    stress_limit_breached = (
        not stress_result.no_positions
        and max_loss_pct > 0.0
        and stress_result.worst_case_loss_pct > max_loss_pct
    )

    scenario_schemas: list[ScenarioResultSchema] = []
    for sr in stress_result.scenarios:
        scenario_schemas.append(
            ScenarioResultSchema(
                scenario_name=sr.scenario_name,
                scenario_label=sr.scenario_label,
                portfolio_shocked_pnl=sr.portfolio_shocked_pnl,
                portfolio_shocked_pnl_pct=round(sr.portfolio_shocked_pnl_pct * 100, 4),
                positions_count=sr.positions_count,
                ticker_shocked_pnl=sr.ticker_shocked_pnl,
                ticker_shocked_pnl_pct={
                    t: round(v * 100, 4) for t, v in sr.ticker_shocked_pnl_pct.items()
                },
            )
        )

    return StressTestSummaryResponse(
        computed_at=stress_result.computed_at,
        equity=stress_result.equity,
        positions_count=stress_result.positions_count,
        no_positions=stress_result.no_positions,
        worst_case_scenario=stress_result.worst_case_scenario,
        worst_case_scenario_label=worst_label,
        worst_case_loss_pct=round(stress_result.worst_case_loss_pct * 100, 4),
        worst_case_loss_dollar=round(stress_result.worst_case_loss_dollar, 2),
        max_stress_loss_pct=round(max_loss_pct * 100, 2),
        stress_limit_breached=stress_limit_breached,
        scenarios=scenario_schemas,
    )


@stress_router.get(
    "/stress-test/{scenario}",
    response_model=StressScenarioDetailResponse,
    summary="Single-scenario stress-test detail",
    description=(
        "Returns the detailed stressed P&L for a named scenario "
        "(e.g. 'financial_crisis_2008', 'covid_crash_2020', "
        "'rate_shock_2022', 'dotcom_bust_2001').  "
        "A 200 with data_available=False is returned when no stress data "
        "exists for the scenario — 404 is NOT raised."
    ),
)
def get_stress_scenario_detail(
    scenario: str,
    state: AppStateDep,
) -> StressScenarioDetailResponse:
    """Return stress detail for a single named scenario."""
    scenario = scenario.lower()
    stress_result = getattr(state, "latest_stress_result", None)

    if stress_result is None:
        return StressScenarioDetailResponse(
            scenario_name=scenario,
            data_available=False,
            computed_at=None,
        )

    # Find the matching scenario result
    matched = None
    for sr in stress_result.scenarios:
        if sr.scenario_name == scenario:
            matched = sr
            break

    if matched is None:
        return StressScenarioDetailResponse(
            scenario_name=scenario,
            data_available=False,
            computed_at=stress_result.computed_at,
            worst_case_scenario=stress_result.worst_case_scenario,
        )

    return StressScenarioDetailResponse(
        scenario_name=matched.scenario_name,
        data_available=True,
        computed_at=stress_result.computed_at,
        scenario_label=matched.scenario_label,
        portfolio_shocked_pnl=matched.portfolio_shocked_pnl,
        portfolio_shocked_pnl_pct=round(matched.portfolio_shocked_pnl_pct * 100, 4),
        equity=matched.equity,
        positions_count=matched.positions_count,
        ticker_shocked_pnl=matched.ticker_shocked_pnl,
        worst_case_scenario=stress_result.worst_case_scenario,
    )
