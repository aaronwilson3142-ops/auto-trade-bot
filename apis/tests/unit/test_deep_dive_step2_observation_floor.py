"""Deep-Dive Plan Step 2 Rec 13 — self-improvement observation-floor tests.

Verifies that the ``self_improvement_min_signal_quality_observations``
setting gates the auto-execute job: below the floor returns
``skipped_insufficient_history`` and does NOT invoke the service's
auto_execute_promoted path.

Default raised 10 → 50 in Step 2 to keep the confidence_score out of
statistical-noise territory per DEC-034.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest import mock

import pytest

# ── Fixtures ─────────────────────────────────────────────────────────────────


class _Settings:
    """Minimal settings stub covering only fields the job reads."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        min_observations: int = 50,
        min_confidence: float = 0.70,
    ) -> None:
        self.self_improvement_auto_execute_enabled = enabled
        self.self_improvement_min_signal_quality_observations = min_observations
        self.self_improvement_min_auto_execute_confidence = min_confidence


def _app_state(total_outcomes: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        latest_signal_quality=(
            SimpleNamespace(total_outcomes_recorded=total_outcomes)
            if total_outcomes is not None else None
        ),
        improvement_proposals=[],
    )


# ── Tests ────────────────────────────────────────────────────────────────────


def test_settings_default_floor_is_fifty():
    """DEC-034: observation floor default raised 10 → 50."""
    from config.settings import Settings

    s = Settings()
    assert s.self_improvement_min_signal_quality_observations == 50


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="self_improvement.service imports datetime.UTC (3.11+)",
)
def test_below_floor_returns_skipped_and_does_not_call_service():
    """49 outcomes vs floor of 50 → skipped_insufficient_history."""
    from apps.worker.jobs.self_improvement import run_auto_execute_proposals

    settings = _Settings(min_observations=50)
    app_state = _app_state(total_outcomes=49)

    fake_service = mock.MagicMock()
    # Any call to auto_execute_promoted() would be a test failure.
    fake_service.auto_execute_promoted.side_effect = AssertionError(
        "service should not be invoked below observation floor"
    )

    result = run_auto_execute_proposals(
        app_state,
        settings=settings,
        auto_execution_service=fake_service,
        session_factory=lambda: None,
    )

    assert result["status"] == "skipped_insufficient_history"
    assert result["total_outcomes"] == 49
    assert result["min_required"] == 50
    assert result["executed_count"] == 0
    fake_service.auto_execute_promoted.assert_not_called()


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="self_improvement.service imports datetime.UTC (3.11+)",
)
def test_at_floor_proceeds_to_service_call():
    """50 outcomes exactly → proceeds to auto_execute_promoted."""
    from apps.worker.jobs.self_improvement import run_auto_execute_proposals

    settings = _Settings(min_observations=50)
    app_state = _app_state(total_outcomes=50)

    fake_service = mock.MagicMock()
    fake_service.auto_execute_promoted.return_value = {
        "executed_count": 0,
        "skipped_count": 0,
        "skipped_low_confidence": 0,
        "error_count": 0,
    }

    result = run_auto_execute_proposals(
        app_state,
        settings=settings,
        auto_execution_service=fake_service,
        session_factory=lambda: None,
    )

    # Not skipped on history grounds; outcome depends on service.
    assert result["status"] != "skipped_insufficient_history"
    fake_service.auto_execute_promoted.assert_called_once()


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="self_improvement.service imports datetime.UTC (3.11+)",
)
def test_missing_quality_report_treated_as_zero_outcomes():
    """No latest_signal_quality on app_state → count=0, still below floor."""
    from apps.worker.jobs.self_improvement import run_auto_execute_proposals

    settings = _Settings(min_observations=50)
    app_state = _app_state(total_outcomes=None)

    fake_service = mock.MagicMock()
    fake_service.auto_execute_promoted.side_effect = AssertionError(
        "service should not be invoked when quality_report is missing"
    )

    result = run_auto_execute_proposals(
        app_state,
        settings=settings,
        auto_execution_service=fake_service,
        session_factory=lambda: None,
    )

    assert result["status"] == "skipped_insufficient_history"
    assert result["total_outcomes"] == 0
