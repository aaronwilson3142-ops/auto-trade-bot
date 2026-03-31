"""
Live Mode Gate — service layer.

``LiveModeGateService.check_prerequisites()`` evaluates all gate requirements
before the system is promoted from one operating mode to the next.

Supported promotion paths with gate checks
-------------------------------------------
  PAPER → HUMAN_APPROVED        (strict checks: paper cycles, eval history, error rate)
  HUMAN_APPROVED → RESTRICTED_LIVE  (stricter: higher thresholds, rankings required)

All other transitions (RESEARCH → BACKTEST → PAPER) are considered low-risk
config changes and do not require programmatic gate validation.

Spec references
---------------
- APIS_MASTER_SPEC.md §3.1 — Safety rollout discipline
- APIS_MASTER_SPEC.md §3.2 — Live-trading restrictions
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from config.settings import OperatingMode, Settings
from services.live_mode_gate.models import GateRequirement, GateStatus, LiveModeGateResult

if TYPE_CHECKING:
    from apps.api.state import ApiAppState

# ── Gate thresholds ────────────────────────────────────────────────────────────
# These defaults represent the minimum bar for promotion.
# They may be reviewed and revised by the operator via explicit spec update.

_PAPER_TO_HA_CYCLE_MIN: int = 5        # min paper cycles for PAPER → HUMAN_APPROVED
_PAPER_TO_HA_EVAL_MIN: int = 5         # min evaluation history entries
_PAPER_TO_HA_MAX_ERRORS: int = 2       # max error cycles in last 5 for PAPER → HUMAN_APPROVED

_HA_TO_RL_CYCLE_MIN: int = 20          # stricter cycle count for HUMAN_APPROVED → RESTRICTED_LIVE
_HA_TO_RL_EVAL_MIN: int = 10           # stricter eval history for restricted live

# ── Phase 51 gate thresholds ───────────────────────────────────────────────────

# Sharpe estimate thresholds (annualised, from evaluation_history daily returns)
_PAPER_TO_HA_MIN_SHARPE: float = 0.5
_HA_TO_RL_MIN_SHARPE: float = 1.0
_MIN_SHARPE_OBSERVATIONS: int = 10    # fewer obs → WARN instead of FAIL/PASS

# Signal quality thresholds (average win_rate across strategies in SignalQualityReport)
_PAPER_TO_HA_MIN_WIN_RATE: float = 0.40
_HA_TO_RL_MIN_WIN_RATE: float = 0.45


class LiveModeGateService:
    """
    Validates gate prerequisites before operating mode promotion.

    The gate enforces that the system has demonstrated sufficient operational
    stability and history before moving into higher-risk execution modes.

    Each promotion is evaluated independently, producing a ``LiveModeGateResult``
    with per-requirement detail and an overall pass/fail signal.

    The service is advisory only — it does not mutate settings.  Operator
    must update ``APIS_OPERATING_MODE`` environment variable and restart the
    service to actually promote.
    """

    # Valid sequential promotion paths that require gate checks
    _GATED_PROMOTIONS: dict[OperatingMode, OperatingMode] = {
        OperatingMode.PAPER: OperatingMode.HUMAN_APPROVED,
        OperatingMode.HUMAN_APPROVED: OperatingMode.RESTRICTED_LIVE,
    }

    def check_prerequisites(
        self,
        current_mode: OperatingMode,
        target_mode: OperatingMode,
        app_state: ApiAppState,
        settings: Settings,
    ) -> LiveModeGateResult:
        """Evaluate all gate requirements for the current → target mode promotion.

        Args:
            current_mode: The operating mode the system is currently in.
            target_mode:  The requested target operating mode.
            app_state:    Shared ApiAppState providing runtime evidence.
            settings:     Current system settings.

        Returns:
            ``LiveModeGateResult`` with all requirement details and an overall
            ``all_passed`` flag.  If ``all_passed`` is True, a
            ``promotion_advisory`` string is set describing the operator action
            required to complete the promotion.
        """
        result = LiveModeGateResult(
            current_mode=current_mode.value,
            target_mode=target_mode.value,
        )

        # ── Validate the promotion path is sequential ─────────────────────────
        valid_next = self._GATED_PROMOTIONS.get(current_mode)
        if valid_next is None or valid_next != target_mode:
            _expected = valid_next.value if valid_next else "none"
            result.requirements.append(
                GateRequirement(
                    name="valid_promotion_path",
                    description=(
                        f"Mode promotion must be sequential. "
                        f"From '{current_mode.value}' the only gated promotion is "
                        f"to '{_expected}'."
                    ),
                    status=GateStatus.FAIL,
                    actual_value=f"{current_mode.value} -> {target_mode.value}",
                    required_value=f"{current_mode.value} -> {_expected}",
                )
            )
            return result

        # ── Kill switch must be OFF ───────────────────────────────────────────
        # Check both the env-var setting AND the runtime app-state flag (Priority 19).
        effective_kill = settings.kill_switch or getattr(app_state, "kill_switch_active", False)
        result.requirements.append(
            GateRequirement(
                name="kill_switch_off",
                description="Kill switch must be inactive before any mode promotion.",
                status=GateStatus.FAIL if effective_kill else GateStatus.PASS,
                actual_value=effective_kill,
                required_value=False,
                detail="Disable kill switch (env var and runtime flag) before promoting.",
            )
        )

        # ── Dispatch to specific gate checklist ───────────────────────────────
        if target_mode == OperatingMode.HUMAN_APPROVED:
            self._check_paper_to_human_approved(result, app_state)
        elif target_mode == OperatingMode.RESTRICTED_LIVE:
            self._check_human_approved_to_restricted_live(result, app_state)

        # ── Advisory message when all requirements pass ───────────────────────
        if result.all_passed:
            result.promotion_advisory = (
                f"All {len(result.requirements)} gate requirements satisfied. "
                f"Operator may promote from '{current_mode.value}' to '{target_mode.value}'. "
                f"To complete: set APIS_OPERATING_MODE={target_mode.value} in the "
                f"environment and restart the service."
            )

        return result

    # ── Private gate checklists ────────────────────────────────────────────────

    def _check_paper_to_human_approved(
        self,
        result: LiveModeGateResult,
        app_state: ApiAppState,
    ) -> None:
        """Gate requirements for PAPER → HUMAN_APPROVED promotion."""

        # Minimum completed paper trading cycles.
        # Use the durable paper_cycle_count counter (persisted across restarts via
        # system_state DB table, Priority 19).  Fall back to len(paper_cycle_results)
        # for backward compatibility with states that pre-date Priority 19.
        cycle_count = getattr(app_state, "paper_cycle_count", 0)
        if not cycle_count:
            cycle_count = len(getattr(app_state, "paper_cycle_results", []))
        result.requirements.append(
            GateRequirement(
                name="min_paper_cycles",
                description=(
                    f"At least {_PAPER_TO_HA_CYCLE_MIN} paper trading cycles must "
                    f"have completed successfully."
                ),
                status=GateStatus.PASS if cycle_count >= _PAPER_TO_HA_CYCLE_MIN else GateStatus.FAIL,
                actual_value=cycle_count,
                required_value=_PAPER_TO_HA_CYCLE_MIN,
            )
        )

        # Minimum daily evaluation history entries
        eval_count = len(app_state.evaluation_history)
        result.requirements.append(
            GateRequirement(
                name="min_evaluation_history",
                description=(
                    f"At least {_PAPER_TO_HA_EVAL_MIN} daily evaluation scorecard "
                    f"entries must exist."
                ),
                status=GateStatus.PASS if eval_count >= _PAPER_TO_HA_EVAL_MIN else GateStatus.FAIL,
                actual_value=eval_count,
                required_value=_PAPER_TO_HA_EVAL_MIN,
            )
        )

        # Error rate in the last 5 cycles must be acceptable
        recent_cycles = list(app_state.paper_cycle_results[-5:])
        recent_error_count = sum(
            1
            for r in recent_cycles
            if isinstance(r, dict) and len(r.get("errors", [])) > 0
        )
        result.requirements.append(
            GateRequirement(
                name="acceptable_recent_error_rate",
                description=(
                    f"At most {_PAPER_TO_HA_MAX_ERRORS} of the last 5 paper cycles "
                    f"may have errors."
                ),
                status=(
                    GateStatus.PASS
                    if recent_error_count <= _PAPER_TO_HA_MAX_ERRORS
                    else GateStatus.FAIL
                ),
                actual_value=recent_error_count,
                required_value=f"<= {_PAPER_TO_HA_MAX_ERRORS}",
            )
        )

        # Portfolio state must exist (cycle has run at least once)
        result.requirements.append(
            GateRequirement(
                name="portfolio_initialized",
                description="Portfolio state must have been initialized by the paper trading loop.",
                status=GateStatus.PASS if app_state.portfolio_state is not None else GateStatus.FAIL,
                actual_value=(
                    "initialized" if app_state.portfolio_state is not None else "not_initialized"
                ),
                required_value="initialized",
            )
        )

        # Phase 51 gates
        self._check_sharpe_gate(result, app_state, _PAPER_TO_HA_MIN_SHARPE)
        self._check_drawdown_state_gate(result, app_state)
        self._check_signal_quality_gate(result, app_state, _PAPER_TO_HA_MIN_WIN_RATE)

    def _check_human_approved_to_restricted_live(
        self,
        result: LiveModeGateResult,
        app_state: ApiAppState,
    ) -> None:
        """Gate requirements for HUMAN_APPROVED → RESTRICTED_LIVE promotion.

        Uses stricter thresholds than PAPER → HUMAN_APPROVED and adds
        additional evidence requirements.
        """

        # Higher cycle bar for restricted live
        cycle_count = getattr(app_state, "paper_cycle_count", 0)
        if not cycle_count:
            cycle_count = len(getattr(app_state, "paper_cycle_results", []))
        result.requirements.append(
            GateRequirement(
                name="min_cycles_for_restricted_live",
                description=(
                    f"At least {_HA_TO_RL_CYCLE_MIN} paper/human-approved cycles "
                    f"must have completed before restricted live is permitted."
                ),
                status=GateStatus.PASS if cycle_count >= _HA_TO_RL_CYCLE_MIN else GateStatus.FAIL,
                actual_value=cycle_count,
                required_value=_HA_TO_RL_CYCLE_MIN,
            )
        )

        # Higher evaluation history bar
        eval_count = len(app_state.evaluation_history)
        result.requirements.append(
            GateRequirement(
                name="min_evaluation_history_for_restricted_live",
                description=(
                    f"At least {_HA_TO_RL_EVAL_MIN} daily evaluation entries must "
                    f"exist before restricted live is permitted."
                ),
                status=GateStatus.PASS if eval_count >= _HA_TO_RL_EVAL_MIN else GateStatus.FAIL,
                actual_value=eval_count,
                required_value=_HA_TO_RL_EVAL_MIN,
            )
        )

        # Portfolio state must exist
        result.requirements.append(
            GateRequirement(
                name="portfolio_initialized",
                description="Portfolio state must be initialized.",
                status=GateStatus.PASS if app_state.portfolio_state is not None else GateStatus.FAIL,
                actual_value=(
                    "initialized" if app_state.portfolio_state is not None else "not_initialized"
                ),
                required_value="initialized",
            )
        )

        # Rankings must have been generated
        ranking_count = len(app_state.latest_rankings)
        result.requirements.append(
            GateRequirement(
                name="rankings_available",
                description=(
                    "The ranking engine must have produced at least one set of results."
                ),
                status=GateStatus.PASS if ranking_count > 0 else GateStatus.FAIL,
                actual_value=ranking_count,
                required_value=">= 1",
            )
        )

        # Error rate in the last 5 cycles must be acceptable
        recent_cycles = list(app_state.paper_cycle_results[-5:])
        recent_error_count = sum(
            1
            for r in recent_cycles
            if isinstance(r, dict) and len(r.get("errors", [])) > 0
        )
        result.requirements.append(
            GateRequirement(
                name="acceptable_recent_error_rate",
                description=(
                    f"At most {_PAPER_TO_HA_MAX_ERRORS} of the last 5 cycles "
                    f"may have errors."
                ),
                status=(
                    GateStatus.PASS
                    if recent_error_count <= _PAPER_TO_HA_MAX_ERRORS
                    else GateStatus.FAIL
                ),
                actual_value=recent_error_count,
                required_value=f"<= {_PAPER_TO_HA_MAX_ERRORS}",
            )
        )

        # Phase 51 gates
        self._check_sharpe_gate(result, app_state, _HA_TO_RL_MIN_SHARPE)
        self._check_drawdown_state_gate(result, app_state)
        self._check_signal_quality_gate(result, app_state, _HA_TO_RL_MIN_WIN_RATE)

    # ── Phase 51 helper gates ──────────────────────────────────────────────────

    @staticmethod
    def _compute_sharpe_from_history(evaluation_history: list) -> tuple[float, int]:
        """Compute annualised Sharpe estimate from evaluation_history daily returns.

        Returns:
            (sharpe_estimate, observation_count) — sharpe is 0.0 when < 2 obs.

        Only accepts numeric types (int, float, Decimal) — Mock/sentinel objects
        that happen to satisfy ``float()`` conversion are intentionally excluded
        so test fixtures that don't configure daily_return_pct produce 0 observations
        rather than spurious Sharpe values.
        """
        from decimal import Decimal as _Decimal

        returns: list[float] = []
        for scorecard in evaluation_history:
            ret = getattr(scorecard, "daily_return_pct", None)
            if ret is None:
                continue
            if not isinstance(ret, (int, float, _Decimal)):
                continue
            try:
                returns.append(float(ret))
            except (TypeError, ValueError):
                pass

        n = len(returns)
        if n < 2:
            return 0.0, n

        mean_r = sum(returns) / n
        variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0.0
        if std_r == 0:
            return 0.0, n

        sharpe = (mean_r / std_r) * math.sqrt(252)
        return round(sharpe, 4), n

    def _check_sharpe_gate(
        self,
        result: LiveModeGateResult,
        app_state: ApiAppState,
        min_sharpe: float,
    ) -> None:
        """Require minimum annualised Sharpe from evaluation history daily returns.

        WARN when fewer than _MIN_SHARPE_OBSERVATIONS are available (not enough
        history to compute a reliable estimate).  PASS / FAIL otherwise.
        """
        sharpe, obs_count = self._compute_sharpe_from_history(
            getattr(app_state, "evaluation_history", [])
        )

        if obs_count < _MIN_SHARPE_OBSERVATIONS:
            status = GateStatus.WARN
            detail = (
                f"Only {obs_count} daily return observations available "
                f"(minimum {_MIN_SHARPE_OBSERVATIONS} for a reliable estimate). "
                f"Current Sharpe estimate: {sharpe:.4f}. "
                f"Accumulate more evaluation history before relying on this gate."
            )
        else:
            status = GateStatus.PASS if sharpe >= min_sharpe else GateStatus.FAIL
            detail = ""

        result.requirements.append(
            GateRequirement(
                name="min_sharpe_estimate",
                description=(
                    f"Annualised Sharpe estimate (from daily evaluation returns) "
                    f"must be >= {min_sharpe:.2f}."
                ),
                status=status,
                actual_value=sharpe,
                required_value=f">= {min_sharpe:.2f}",
                detail=detail,
            )
        )

    @staticmethod
    def _check_drawdown_state_gate(
        result: LiveModeGateResult,
        app_state: ApiAppState,
    ) -> None:
        """Require drawdown state is not RECOVERY before promotion.

        NORMAL → PASS; CAUTION → WARN (advisory, does not block);
        RECOVERY → FAIL (blocks all promotions).
        """
        drawdown_state: str = getattr(app_state, "drawdown_state", "NORMAL")

        if drawdown_state == "RECOVERY":
            status = GateStatus.FAIL
            detail = (
                "Portfolio is in RECOVERY drawdown mode. "
                "Resolve the drawdown (return to NORMAL or CAUTION) before promoting."
            )
        elif drawdown_state == "CAUTION":
            status = GateStatus.WARN
            detail = (
                "Portfolio is in CAUTION drawdown mode. "
                "Promotion is permitted but the operator should monitor drawdown closely."
            )
        else:
            status = GateStatus.PASS
            detail = ""

        result.requirements.append(
            GateRequirement(
                name="drawdown_state_acceptable",
                description=(
                    "Portfolio drawdown state must not be RECOVERY before promotion. "
                    "NORMAL=PASS, CAUTION=WARN (advisory), RECOVERY=FAIL."
                ),
                status=status,
                actual_value=drawdown_state,
                required_value="NORMAL or CAUTION",
                detail=detail,
            )
        )

    @staticmethod
    def _check_signal_quality_gate(
        result: LiveModeGateResult,
        app_state: ApiAppState,
        min_win_rate: float,
    ) -> None:
        """Require minimum average win rate across strategies in SignalQualityReport.

        WARN when no quality report is available yet.  PASS / FAIL otherwise.
        """
        quality_report = getattr(app_state, "latest_signal_quality", None)

        if quality_report is None:
            result.requirements.append(
                GateRequirement(
                    name="min_signal_quality_win_rate",
                    description=(
                        f"Average strategy win rate across all tracked strategies "
                        f"must be >= {min_win_rate:.0%}."
                    ),
                    status=GateStatus.WARN,
                    actual_value="no_data",
                    required_value=f">= {min_win_rate:.0%}",
                    detail=(
                        "No SignalQualityReport available yet (run_signal_quality_update "
                        "has not completed). Accumulate closed trades to enable this gate."
                    ),
                )
            )
            return

        strategy_results = getattr(quality_report, "strategy_results", [])
        if not strategy_results:
            result.requirements.append(
                GateRequirement(
                    name="min_signal_quality_win_rate",
                    description=(
                        f"Average strategy win rate across all tracked strategies "
                        f"must be >= {min_win_rate:.0%}."
                    ),
                    status=GateStatus.WARN,
                    actual_value="no_strategies",
                    required_value=f">= {min_win_rate:.0%}",
                    detail=(
                        "SignalQualityReport exists but contains no strategy results. "
                        "Close trades and re-run quality update to populate this gate."
                    ),
                )
            )
            return

        win_rates = [
            getattr(s, "win_rate", 0.0) for s in strategy_results
        ]
        avg_win_rate = sum(win_rates) / len(win_rates)

        result.requirements.append(
            GateRequirement(
                name="min_signal_quality_win_rate",
                description=(
                    f"Average strategy win rate across all tracked strategies "
                    f"must be >= {min_win_rate:.0%}."
                ),
                status=GateStatus.PASS if avg_win_rate >= min_win_rate else GateStatus.FAIL,
                actual_value=round(avg_win_rate, 4),
                required_value=f">= {min_win_rate:.0%}",
            )
        )
