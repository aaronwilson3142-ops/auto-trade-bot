"""
Worker job: generate and auto-execute controlled self-improvement proposals.

Functions
---------
run_generate_improvement_proposals — derive proposals from latest scorecard
run_auto_execute_proposals         — auto-execute all PROMOTED proposals

Design rules
------------
- run_generate_improvement_proposals reads app_state.latest_scorecard and
  app_state.promoted_versions; writes to app_state.improvement_proposals
  (replaces the list each cycle so stale proposals don't accumulate).
- run_auto_execute_proposals runs after proposal generation (18:15 ET);
  calls AutoExecutionService.auto_execute_promoted on the current proposal list.
- Neither function self-promotes: promotion decisions must go through
  SelfImprovementService.promote_or_reject first.
- Exceptions are caught so the scheduler thread never dies.

Phase 35 — Self-Improvement Proposal Auto-Execution
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# run_generate_improvement_proposals
# ---------------------------------------------------------------------------

def run_generate_improvement_proposals(
    app_state: ApiAppState,
    settings: Settings | None = None,
    self_improvement_service: Any | None = None,
) -> dict[str, Any]:
    """Generate improvement proposals from the latest scorecard.

    Reads app_state.latest_scorecard and app_state.promoted_versions, then
    calls SelfImprovementService.generate_proposals.  The resulting proposals
    are written to app_state.improvement_proposals.

    Note: no proposals are promoted here.  Promotion requires an explicit
    evaluate_proposal + promote_or_reject call.

    Args:
        app_state:                  Shared ApiAppState (read + write).
        settings:                   Settings instance.
        self_improvement_service:   SelfImprovementService for injection/testing.

    Returns:
        dict with keys: status, proposals_generated, scorecard_grade, run_at.
    """
    from services.self_improvement.service import SelfImprovementService

    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)
    svc = self_improvement_service or SelfImprovementService()

    logger.info("self_improvement_job_starting", run_at=run_at.isoformat())

    try:
        scorecard = app_state.latest_scorecard

        # Derive a letter grade for the proposal engine
        grade = _scorecard_to_grade(scorecard)

        # Build an attribution summary from the scorecard's attribution data
        attribution_summary = _build_attribution_summary(scorecard)

        current_versions = dict(app_state.promoted_versions)

        proposals = svc.generate_proposals(
            scorecard_grade=grade,
            attribution_summary=attribution_summary,
            current_versions=current_versions,
        )

        # Replace proposals from previous cycle
        app_state.improvement_proposals = proposals

        logger.info(
            "self_improvement_job_complete",
            scorecard_grade=grade,
            proposals_generated=len(proposals),
        )
        return {
            "status": "ok",
            "proposals_generated": len(proposals),
            "scorecard_grade": grade,
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("self_improvement_job_failed", error=str(exc))
        return {
            "status": "error",
            "proposals_generated": 0,
            "scorecard_grade": None,
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scorecard_to_grade(scorecard: Any) -> str:
    """Derive a single letter grade from a DailyScorecard.

    Uses daily_return_pct mapped against the standard evaluation thresholds:
      A >= +5%  |  B >= +2%  |  C >= 0%  |  D >= -3%  |  F < -3%
    """
    if scorecard is None:
        return "C"

    ret = getattr(scorecard, "daily_return_pct", None)
    if ret is None:
        return "C"

    ret = Decimal(str(ret))
    if ret >= Decimal("0.05"):
        return "A"
    if ret >= Decimal("0.02"):
        return "B"
    if ret >= Decimal("0"):
        return "C"
    if ret >= Decimal("-0.03"):
        return "D"
    return "F"


def _build_attribution_summary(scorecard: Any) -> dict[str, Any]:
    """Extract a minimal attribution_summary dict from a DailyScorecard."""
    summary: dict[str, Any] = {}
    if scorecard is None:
        return summary

    attribution = getattr(scorecard, "attribution", None)
    if attribution is None:
        return summary

    # Worst-performing strategy
    by_strategy = getattr(attribution, "by_strategy", [])
    if by_strategy:
        worst = min(by_strategy, key=lambda r: r.realized_pnl)
        summary["worst_strategy"] = worst.key

    # Hit rate from scorecard
    hit_rate = getattr(scorecard, "hit_rate", None)
    if hit_rate is not None:
        summary["hit_rate"] = Decimal(str(hit_rate))

    # Average loser P&L
    avg_loser = getattr(scorecard, "avg_loser_pct", None)
    if avg_loser is not None:
        summary["avg_loss_pct"] = Decimal(str(avg_loser))

    return summary


# ---------------------------------------------------------------------------
# run_auto_execute_proposals
# ---------------------------------------------------------------------------

def run_auto_execute_proposals(
    app_state: Any,
    settings: Settings | None = None,
    session_factory: Any | None = None,
    auto_execution_service: Any | None = None,
) -> dict[str, Any]:
    """Auto-execute all PROMOTED proposals from the current improvement cycle.

    Runs at 18:15 ET — 15 minutes after run_generate_improvement_proposals so
    proposals have been generated before this job fires.

    Reads app_state.improvement_proposals, passes PROMOTED ones to
    AutoExecutionService.auto_execute_promoted, and updates
    app_state.last_auto_execute_at.

    Phase 58 safety gates (all evaluated BEFORE any proposal is applied):
      1. ``settings.self_improvement_auto_execute_enabled`` — master kill
         switch.  When False, the job is a no-op returning
         ``status="skipped_disabled"``.  This is the default; the operator
         must explicitly flip the flag once the system has accumulated
         enough real trading history for confidence scoring to be meaningful.
      2. Signal-quality observation floor — the latest SignalQualityReport
         must contain at least
         ``settings.self_improvement_min_signal_quality_observations``
         total outcomes.  Below that floor the confidence_score on any
         proposal is statistically noise, so the entire batch is skipped
         with ``status="skipped_insufficient_history"``.
      3. Per-proposal confidence gate —
         ``settings.self_improvement_min_auto_execute_confidence`` is passed
         through to ``AutoExecutionService.auto_execute_promoted`` so that
         only proposals meeting the threshold are applied.  (Prior to
         Phase 58 this argument was never passed, so the 0.70 default in
         ``SelfImprovementConfig`` was dead code in production.)

    Args:
        app_state:               Shared ApiAppState (read + write).
        settings:                Settings instance.  Defaults to get_settings().
        session_factory:         SQLAlchemy session factory for DB persist.
        auto_execution_service:  AutoExecutionService for injection/testing.

    Returns:
        dict with keys: status, executed_count, skipped_count,
        skipped_low_confidence, error_count, run_at.  The ``status`` field
        is one of ``ok``, ``skipped_disabled``, ``skipped_insufficient_history``,
        or ``error``.
    """
    from services.self_improvement.execution import AutoExecutionService

    run_at = dt.datetime.now(dt.UTC)
    svc = auto_execution_service or AutoExecutionService()
    cfg = settings or get_settings()

    logger.info("auto_execute_job_starting", run_at=run_at.isoformat())

    # ── Gate 1: master kill switch ─────────────────────────────────────────
    if not getattr(cfg, "self_improvement_auto_execute_enabled", False):
        logger.info(
            "auto_execute_job_skipped_disabled",
            reason="self_improvement_auto_execute_enabled is False",
        )
        return {
            "status": "skipped_disabled",
            "executed_count": 0,
            "skipped_count": 0,
            "skipped_low_confidence": 0,
            "error_count": 0,
            "run_at": run_at.isoformat(),
        }

    # ── Gate 2: signal-quality observation floor ───────────────────────────
    min_obs = int(
        getattr(cfg, "self_improvement_min_signal_quality_observations", 10)
    )
    quality_report = getattr(app_state, "latest_signal_quality", None)
    total_outcomes = int(
        getattr(quality_report, "total_outcomes_recorded", 0) or 0
    )
    if total_outcomes < min_obs:
        logger.info(
            "auto_execute_job_skipped_insufficient_history",
            total_outcomes=total_outcomes,
            min_required=min_obs,
        )
        return {
            "status": "skipped_insufficient_history",
            "executed_count": 0,
            "skipped_count": 0,
            "skipped_low_confidence": 0,
            "error_count": 0,
            "total_outcomes": total_outcomes,
            "min_required": min_obs,
            "run_at": run_at.isoformat(),
        }

    # ── Gate 3: per-proposal confidence threshold (passed through) ─────────
    min_conf = float(
        getattr(cfg, "self_improvement_min_auto_execute_confidence", 0.70)
    )

    try:
        proposals = getattr(app_state, "improvement_proposals", [])
        result = svc.auto_execute_promoted(
            proposals,
            app_state,
            session_factory=session_factory,
            min_confidence=min_conf,
        )

        logger.info(
            "auto_execute_job_complete",
            executed_count=result["executed_count"],
            skipped_count=result["skipped_count"],
            skipped_low_confidence=result.get("skipped_low_confidence", 0),
            error_count=result["error_count"],
            min_confidence=min_conf,
        )
        return {
            "status": "ok",
            "executed_count": result["executed_count"],
            "skipped_count": result["skipped_count"],
            "skipped_low_confidence": result.get("skipped_low_confidence", 0),
            "error_count": result["error_count"],
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("auto_execute_job_failed", error=str(exc))
        return {
            "status": "error",
            "executed_count": 0,
            "skipped_count": 0,
            "skipped_low_confidence": 0,
            "error_count": 0,
            "run_at": run_at.isoformat(),
        }
