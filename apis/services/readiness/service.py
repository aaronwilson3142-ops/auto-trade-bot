"""
Readiness Report service — Phase 53.

``ReadinessReportService.generate_report()`` delegates gate evaluation to
``LiveModeGateService`` and wraps the result into a ``ReadinessReport``
dataclass that can be cached in ``ApiAppState`` and served via
``GET /system/readiness-report``.

Design
------
- Stateless: no instance state; all inputs come from app_state + settings.
- Delegates all gate logic to ``LiveModeGateService`` — no duplication.
- Always returns a valid ``ReadinessReport`` (graceful degradation on error).
- overall_status computation:
    • "NO_GATE"  — mode has no gated promotion path (RESEARCH/BACKTEST)
    • "FAIL"     — at least one gate row is FAIL
    • "WARN"     — no FAIL, but at least one WARN
    • "PASS"     — all gate rows PASS
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import TYPE_CHECKING, Any, Optional

from services.readiness.models import ReadinessGateRow, ReadinessReport

if TYPE_CHECKING:
    from apps.api.state import ApiAppState
    from config.settings import Settings


class ReadinessReportService:
    """Generates a pre-computed live-mode readiness snapshot."""

    def generate_report(
        self,
        app_state: "ApiAppState",
        settings: "Settings",
    ) -> ReadinessReport:
        """Evaluate all live-gate requirements and return a ReadinessReport.

        Args:
            app_state: Shared ApiAppState providing runtime evidence.
            settings:  Current system settings (determines current mode).

        Returns:
            A fully populated ``ReadinessReport`` ready to cache in app_state.
        """
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService

        generated_at = dt.datetime.now(dt.timezone.utc)
        current_mode_enum = settings.operating_mode
        current_mode = current_mode_enum.value

        # Determine the next gated target for this mode
        _NEXT_GATED: dict[OperatingMode, OperatingMode] = {
            OperatingMode.PAPER: OperatingMode.HUMAN_APPROVED,
            OperatingMode.HUMAN_APPROVED: OperatingMode.RESTRICTED_LIVE,
        }
        target_mode_enum = _NEXT_GATED.get(current_mode_enum)

        if target_mode_enum is None:
            # No gated promotion from this mode
            return ReadinessReport(
                generated_at=generated_at,
                current_mode=current_mode,
                target_mode="n/a",
                overall_status="NO_GATE",
                gate_rows=[],
                pass_count=0,
                warn_count=0,
                fail_count=0,
                recommendation=(
                    f"No gated promotion required from '{current_mode}'. "
                    f"Update APIS_OPERATING_MODE directly to advance."
                ),
            )

        target_mode = target_mode_enum.value

        # Delegate gate evaluation to LiveModeGateService
        gate_svc = LiveModeGateService()
        try:
            result = gate_svc.check_prerequisites(
                current_mode=current_mode_enum,
                target_mode=target_mode_enum,
                app_state=app_state,
                settings=settings,
            )
        except Exception:  # noqa: BLE001
            # Graceful degradation: return a FAIL report if gate service errors
            return ReadinessReport(
                generated_at=generated_at,
                current_mode=current_mode,
                target_mode=target_mode,
                overall_status="FAIL",
                gate_rows=[
                    ReadinessGateRow(
                        gate_name="gate_evaluation_error",
                        description="Gate evaluation encountered an unexpected error.",
                        status="FAIL",
                        actual_value="error",
                        required_value="no_error",
                        detail="LiveModeGateService.check_prerequisites() raised an exception.",
                    )
                ],
                pass_count=0,
                warn_count=0,
                fail_count=1,
                recommendation="Resolve gate evaluation error before attempting promotion.",
            )

        # Convert GateRequirement objects → ReadinessGateRow objects
        gate_rows: list[ReadinessGateRow] = []
        for req in result.requirements:
            gate_rows.append(
                ReadinessGateRow(
                    gate_name=req.name,
                    description=req.description,
                    status=req.status.value.upper(),
                    actual_value=str(req.actual_value),
                    required_value=str(req.required_value),
                    detail=req.detail or "",
                )
            )

        pass_count = sum(1 for r in gate_rows if r.status == "PASS")
        warn_count = sum(1 for r in gate_rows if r.status == "WARN")
        fail_count = sum(1 for r in gate_rows if r.status == "FAIL")

        if fail_count > 0:
            overall_status = "FAIL"
        elif warn_count > 0:
            overall_status = "WARN"
        else:
            overall_status = "PASS"

        recommendation = self._build_recommendation(
            overall_status=overall_status,
            current_mode=current_mode,
            target_mode=target_mode,
            pass_count=pass_count,
            warn_count=warn_count,
            fail_count=fail_count,
            gate_rows=gate_rows,
        )

        return ReadinessReport(
            generated_at=generated_at,
            current_mode=current_mode,
            target_mode=target_mode,
            overall_status=overall_status,
            gate_rows=gate_rows,
            pass_count=pass_count,
            warn_count=warn_count,
            fail_count=fail_count,
            recommendation=recommendation,
        )

    @staticmethod
    def persist_snapshot(
        report: ReadinessReport,
        session_factory: Any = None,
    ) -> None:
        """Persist a ReadinessReport as a ReadinessSnapshot row (fire-and-forget).

        Never raises — errors are silently swallowed so callers are never blocked.

        Args:
            report:          The ReadinessReport to persist.
            session_factory: Callable that returns a DB session context manager.
                             When None, this method is a no-op.
        """
        if session_factory is None:
            return

        try:
            from infra.db.models.readiness import ReadinessSnapshot

            gates_data = [
                {
                    "gate_name": r.gate_name,
                    "status": r.status,
                    "actual_value": r.actual_value,
                    "required_value": r.required_value,
                    "detail": r.detail,
                }
                for r in report.gate_rows
            ]

            snapshot = ReadinessSnapshot(
                id=str(uuid.uuid4()),
                captured_at=report.generated_at,
                overall_status=report.overall_status,
                current_mode=report.current_mode,
                target_mode=report.target_mode,
                pass_count=report.pass_count,
                warn_count=report.warn_count,
                fail_count=report.fail_count,
                gate_count=report.gate_count,
                gates_json=json.dumps(gates_data),
                recommendation=report.recommendation or None,
            )

            with session_factory() as session:
                session.add(snapshot)
                session.commit()

        except Exception:  # noqa: BLE001
            pass  # Fire-and-forget: never raise

    @staticmethod
    def _build_recommendation(
        overall_status: str,
        current_mode: str,
        target_mode: str,
        pass_count: int,
        warn_count: int,
        fail_count: int,
        gate_rows: list[ReadinessGateRow],
    ) -> str:
        """Build a human-readable recommendation string from gate results."""
        total = pass_count + warn_count + fail_count
        if overall_status == "PASS":
            return (
                f"All {total} gate requirements satisfied. "
                f"System is ready to promote from '{current_mode}' to '{target_mode}'. "
                f"Call POST /api/v1/live-gate/promote to record the promotion advisory, "
                f"then set APIS_OPERATING_MODE={target_mode} and restart."
            )
        if overall_status == "WARN":
            warn_names = [r.gate_name for r in gate_rows if r.status == "WARN"]
            return (
                f"{pass_count}/{total} gates PASS, {warn_count} advisory warning(s): "
                f"{', '.join(warn_names)}. "
                f"Promotion is permitted, but review warnings before advancing to '{target_mode}'."
            )
        # FAIL
        fail_names = [r.gate_name for r in gate_rows if r.status == "FAIL"]
        return (
            f"{fail_count} gate(s) failing: {', '.join(fail_names)}. "
            f"Resolve all failing requirements before promoting from "
            f"'{current_mode}' to '{target_mode}'."
        )
