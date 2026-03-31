"""
Route handlers for /api/v1/live-gate/*.

Provides gate status visibility and advisory promotion workflow for the
PAPER → HUMAN_APPROVED and HUMAN_APPROVED → RESTRICTED_LIVE progressions.

Endpoints
---------
  GET  /api/v1/live-gate/status
      Evaluates gate prerequisites for the natural next promotion from the
      current operating mode.  Returns a full LiveGateStatusResponse with
      per-requirement detail.

  POST /api/v1/live-gate/promote
      Body: { "target_mode": "human_approved" | "restricted_live" }
      Runs the gate check.  If all requirements pass, records a promotion
      advisory in ApiAppState and returns an operator-action message.
      This endpoint is *advisory only* — it does not change settings.
      The operator must update APIS_OPERATING_MODE env var and restart.

Safety note
-----------
These endpoints are read-heavy and make no broker calls, DB writes, or
settings mutations.  The POST endpoint only writes to the in-memory
ApiAppState (``live_gate_last_result`` and ``live_gate_promotion_pending``).

Spec references
---------------
- APIS_MASTER_SPEC.md §3.1 — Safety rollout discipline
- APIS_MASTER_SPEC.md §5   — Operating modes
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.live_gate import (
    GateRequirementSchema,
    LiveGatePromoteRequest,
    LiveGatePromoteResponse,
    LiveGateStatusResponse,
    PromotableMode,
)
from config.settings import OperatingMode
from services.live_mode_gate.service import LiveModeGateService

router = APIRouter(tags=["Live Gate"])

_gate_svc = LiveModeGateService()

# Mapping from each mode to the next gated promotion target
_NEXT_GATED_TARGET: dict[OperatingMode, OperatingMode] = {
    OperatingMode.PAPER: OperatingMode.HUMAN_APPROVED,
    OperatingMode.HUMAN_APPROVED: OperatingMode.RESTRICTED_LIVE,
}


def _serialize_result(result) -> LiveGateStatusResponse:
    """Convert a ``LiveModeGateResult`` dataclass to the API response schema."""
    reqs = [
        GateRequirementSchema(
            name=r.name,
            description=r.description,
            status=r.status.value,
            passed=r.passed,
            actual_value=r.actual_value,
            required_value=r.required_value,
            detail=r.detail,
        )
        for r in result.requirements
    ]
    return LiveGateStatusResponse(
        id=result.id,
        evaluated_at=result.evaluated_at.isoformat(),
        current_mode=result.current_mode,
        target_mode=result.target_mode,
        all_passed=result.all_passed,
        requirements=reqs,
        failed_count=len(result.failed_requirements),
        promotion_advisory=result.promotion_advisory,
    )


@router.get("/live-gate/status", response_model=LiveGateStatusResponse)
async def get_live_gate_status(
    state: AppStateDep,
    settings: SettingsDep,
) -> LiveGateStatusResponse:
    """Evaluate gate prerequisites for the next natural mode promotion.

    Returns a full gate result including per-requirement detail.
    For modes without a gated next step (RESEARCH, BACKTEST), a pass result
    with an informational message is returned.
    """
    current_mode = settings.operating_mode
    target_mode = _NEXT_GATED_TARGET.get(current_mode)

    if target_mode is None:
        # RESEARCH and BACKTEST transitions are low-risk config changes
        from services.live_mode_gate.models import GateRequirement, GateStatus, LiveModeGateResult
        result = LiveModeGateResult(
            current_mode=current_mode.value,
            target_mode="n/a",
            promotion_advisory=(
                f"No gated promotion required from '{current_mode.value}'. "
                f"Update APIS_OPERATING_MODE directly to advance to the next stage."
            ),
        )
        result.requirements.append(
            GateRequirement(
                name="no_gate_required",
                description=(
                    f"No programmatic gate applies to the '{current_mode.value}' "
                    f"→ next transition."
                ),
                status=GateStatus.PASS,
                actual_value=current_mode.value,
                required_value="n/a",
            )
        )
    else:
        result = _gate_svc.check_prerequisites(
            current_mode=current_mode,
            target_mode=target_mode,
            app_state=state,
            settings=settings,
        )

    # Cache result in app state for observability
    state.live_gate_last_result = result

    return _serialize_result(result)


@router.post("/live-gate/promote", response_model=LiveGatePromoteResponse)
async def post_live_gate_promote(
    body: LiveGatePromoteRequest,
    state: AppStateDep,
    settings: SettingsDep,
) -> LiveGatePromoteResponse:
    """Run the gate check for the requested promotion and record advisory.

    If all requirements pass, sets ``app_state.live_gate_promotion_pending`` to
    True and populates ``live_gate_last_result``.

    The operator must then:
      1. Review the promotion advisory in the response.
      2. Update APIS_OPERATING_MODE in the environment.
      3. Restart the service to apply the setting change.

    Returns:
        LiveGatePromoteResponse with gate result and a human-readable message.
    """
    current_mode = settings.operating_mode
    target_mode = OperatingMode(body.target_mode.value)

    result = _gate_svc.check_prerequisites(
        current_mode=current_mode,
        target_mode=target_mode,
        app_state=state,
        settings=settings,
    )

    # Persist gate result + advisory flag in app state
    state.live_gate_last_result = result
    state.live_gate_promotion_pending = result.all_passed

    gate_response = _serialize_result(result)

    if result.all_passed:
        message = (
            f"Gate PASSED ({len(result.requirements)} of "
            f"{len(result.requirements)} requirements met). "
            f"Promotion advisory recorded in system state. "
            f"Operator action required: {result.promotion_advisory}"
        )
        promotion_recorded = True
    else:
        failed = len(result.failed_requirements)
        total = len(result.requirements)
        message = (
            f"Gate FAILED ({failed} of {total} requirements not met). "
            f"Resolve all failing requirements before promotion."
        )
        promotion_recorded = False

    return LiveGatePromoteResponse(
        gate_result=gate_response,
        promotion_recorded=promotion_recorded,
        message=message,
    )
