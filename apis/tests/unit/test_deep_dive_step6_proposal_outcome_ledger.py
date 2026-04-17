"""Unit tests for Deep-Dive Plan Step 6 — Proposal Outcome Ledger.

Covers:
  - PROPOSAL_OUTCOME_WINDOWS table matches DEC-035 (per-type days).
  - window_days_for normalises case / None / unknown → default 30.
  - ProposalOutcomeLedgerService validation guards (decision/verdict/confidence).
  - BattingAverage math (improved_rate, regressed_rate).
  - SelfImprovementService.apply_outcome_feedback + generate_proposals filter.
  - Worker-job flag-off path returns no-op summary.
  - Settings integration: new flag field exposed with default False.

Tests that require a live DB session (get_due_for_assessment, batting_average
from rows, end-to-end write_decision → assess cycle) are deferred to the
integration suite — the ledger model itself is declarative SQLAlchemy so
correctness is validated by the alembic migration + integration run, not here.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# PROPOSAL_OUTCOME_WINDOWS table
# ---------------------------------------------------------------------------


class TestProposalOutcomeWindows:
    def test_known_windows_match_dec_035(self) -> None:
        from services.self_improvement.outcome_ledger import PROPOSAL_OUTCOME_WINDOWS

        # DEC-035 per Deep-Dive Plan §6
        assert PROPOSAL_OUTCOME_WINDOWS["source_weight"] == 45
        assert PROPOSAL_OUTCOME_WINDOWS["ranking_threshold"] == 30
        assert PROPOSAL_OUTCOME_WINDOWS["holding_period_rule"] == 14
        assert PROPOSAL_OUTCOME_WINDOWS["confidence_calibration"] == 60
        assert PROPOSAL_OUTCOME_WINDOWS["prompt_template"] == 30
        assert PROPOSAL_OUTCOME_WINDOWS["feature_transformation"] == 45
        assert PROPOSAL_OUTCOME_WINDOWS["sizing_formula"] == 30
        assert PROPOSAL_OUTCOME_WINDOWS["regime_classifier"] == 60
        assert PROPOSAL_OUTCOME_WINDOWS["_default"] == 30

    def test_all_proposal_type_enum_values_have_a_window(self) -> None:
        from services.self_improvement.models import ProposalType
        from services.self_improvement.outcome_ledger import PROPOSAL_OUTCOME_WINDOWS

        # Every enum value should map to an explicit window (plus the _default
        # sentinel).  Guards against adding a new ProposalType without a window.
        for pt in ProposalType:
            assert pt.value in PROPOSAL_OUTCOME_WINDOWS, (
                f"ProposalType {pt.value!r} missing from PROPOSAL_OUTCOME_WINDOWS"
            )


class TestWindowDaysFor:
    def test_known_type_returns_explicit_window(self) -> None:
        from services.self_improvement.outcome_ledger import window_days_for

        assert window_days_for("source_weight") == 45
        assert window_days_for("holding_period_rule") == 14

    def test_case_insensitive(self) -> None:
        from services.self_improvement.outcome_ledger import window_days_for

        assert window_days_for("SOURCE_WEIGHT") == 45
        assert window_days_for("Source_Weight") == 45
        assert window_days_for("  source_weight  ") == 45

    def test_unknown_type_returns_default(self) -> None:
        from services.self_improvement.outcome_ledger import window_days_for

        assert window_days_for("bogus") == 30
        assert window_days_for("") == 30
        assert window_days_for(None) == 30


# ---------------------------------------------------------------------------
# Validation guards in ProposalOutcomeLedgerService
# ---------------------------------------------------------------------------


class _DummySession:
    """Minimal SQLAlchemy-session stub — enough for validation guards."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushed = False

    def execute(self, *_args, **_kwargs):
        class _R:
            def scalar_one_or_none(self) -> None:
                return None

            def scalars(self):
                class _S:
                    def all(self) -> list:
                        return []

                return _S()

            def all(self) -> list:
                return []

        return _R()

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flushed = True

    def get(self, _cls, _id):
        return None


class TestLedgerValidationGuards:
    def test_write_decision_rejects_unknown_decision(self) -> None:
        from services.self_improvement.outcome_ledger import ProposalOutcomeLedgerService

        svc = ProposalOutcomeLedgerService(_DummySession())
        with pytest.raises(ValueError, match="invalid decision"):
            svc.write_decision(
                proposal_id=uuid.uuid4(),
                decision="FROBNICATE",
                decision_at=dt.datetime.now(dt.timezone.utc),
                baseline_metric_snapshot={"sharpe": 1.2},
            )

    def test_write_decision_accepts_each_valid_decision(self) -> None:
        from services.self_improvement.outcome_ledger import (
            ProposalOutcomeLedgerService,
            VALID_DECISIONS,
        )

        for d in VALID_DECISIONS:
            svc = ProposalOutcomeLedgerService(_DummySession())
            # Should not raise
            svc.write_decision(
                proposal_id=uuid.uuid4(),
                decision=d,
                decision_at=dt.datetime.now(dt.timezone.utc),
                baseline_metric_snapshot={},
                proposal_type="source_weight",
            )

    def test_write_decision_defaults_window_from_type(self) -> None:
        from services.self_improvement.outcome_ledger import ProposalOutcomeLedgerService

        sess = _DummySession()
        svc = ProposalOutcomeLedgerService(sess)
        svc.write_decision(
            proposal_id=uuid.uuid4(),
            decision="PROMOTED",
            decision_at=dt.datetime.now(dt.timezone.utc),
            baseline_metric_snapshot={},
            proposal_type="holding_period_rule",  # 14-day window per DEC-035
        )
        assert len(sess.added) == 1
        row = sess.added[0]
        assert row.measurement_window_days == 14

    def test_write_decision_override_window_beats_type_default(self) -> None:
        from services.self_improvement.outcome_ledger import ProposalOutcomeLedgerService

        sess = _DummySession()
        svc = ProposalOutcomeLedgerService(sess)
        svc.write_decision(
            proposal_id=uuid.uuid4(),
            decision="PROMOTED",
            decision_at=dt.datetime.now(dt.timezone.utc),
            baseline_metric_snapshot={},
            proposal_type="holding_period_rule",
            measurement_window_days=7,
        )
        assert sess.added[0].measurement_window_days == 7

    def test_write_assessment_rejects_unknown_verdict(self) -> None:
        from services.self_improvement.outcome_ledger import ProposalOutcomeLedgerService

        svc = ProposalOutcomeLedgerService(_DummySession())
        with pytest.raises(ValueError, match="invalid verdict"):
            svc.write_assessment(
                outcome_id=uuid.uuid4(),
                realized_metric_snapshot={},
                outcome_verdict="amazing",
                outcome_confidence=0.5,
                measured_at=dt.datetime.now(dt.timezone.utc),
            )

    def test_write_assessment_rejects_out_of_range_confidence(self) -> None:
        from services.self_improvement.outcome_ledger import ProposalOutcomeLedgerService

        svc = ProposalOutcomeLedgerService(_DummySession())
        with pytest.raises(ValueError, match="confidence"):
            svc.write_assessment(
                outcome_id=uuid.uuid4(),
                realized_metric_snapshot={},
                outcome_verdict="improved",
                outcome_confidence=1.5,
                measured_at=dt.datetime.now(dt.timezone.utc),
            )
        with pytest.raises(ValueError, match="confidence"):
            svc.write_assessment(
                outcome_id=uuid.uuid4(),
                realized_metric_snapshot={},
                outcome_verdict="improved",
                outcome_confidence=-0.01,
                measured_at=dt.datetime.now(dt.timezone.utc),
            )


# ---------------------------------------------------------------------------
# BattingAverage math
# ---------------------------------------------------------------------------


class TestBattingAverage:
    def test_rates_sum_correctly(self) -> None:
        from services.self_improvement.outcome_ledger import BattingAverage

        ba = BattingAverage(
            proposal_type="source_weight",
            n_total=10,
            n_improved=4,
            n_regressed=3,
            n_unchanged=2,
            n_inconclusive=1,
        )
        assert ba.improved_rate == pytest.approx(0.4)
        assert ba.regressed_rate == pytest.approx(0.3)

    def test_zero_total_does_not_divide_by_zero(self) -> None:
        from services.self_improvement.outcome_ledger import BattingAverage

        ba = BattingAverage(
            proposal_type="source_weight",
            n_total=0,
            n_improved=0,
            n_regressed=0,
            n_unchanged=0,
            n_inconclusive=0,
        )
        assert ba.improved_rate == 0.0
        assert ba.regressed_rate == 0.0


# ---------------------------------------------------------------------------
# SelfImprovementService generator feedback loop
# ---------------------------------------------------------------------------


# SelfImprovementService instantiates ImprovementProposal, whose dataclass
# fields use ``dt.datetime.now(dt.UTC)`` as a default_factory — that expression
# raises AttributeError on Python 3.10 (our sandbox) but works on 3.11+
# (production).  Follow the Step 5 precedent: skip under 3.10 rather than
# patching an out-of-scope pre-existing model file.
import sys as _sys
_skip_if_no_dt_utc = pytest.mark.skipif(
    _sys.version_info < (3, 11),
    reason="models.py uses dt.UTC which is Python 3.11+; sandbox is 3.10",
)


@_skip_if_no_dt_utc
class TestGeneratorFeedbackLoop:
    def _attribution_that_produces_all_rules(self) -> dict:
        # Crafted so all 4 generate_proposals rules fire under grade "F".
        return {
            "hit_rate": "0.40",            # < 0.50 → SOURCE_WEIGHT
            "avg_loss_pct": "-0.05",       # < -0.02 → RANKING_THRESHOLD
            "worst_strategy": "momentum",  # non-empty → HOLDING_PERIOD_RULE
        }

    def test_suppressed_types_filter_out_matching_proposals(self) -> None:
        from services.self_improvement.service import SelfImprovementService

        svc = SelfImprovementService()
        # Baseline: all four proposal types present under grade F.
        baseline = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary=self._attribution_that_produces_all_rules(),
        )
        baseline_types = {p.proposal_type.value for p in baseline}
        assert {"source_weight", "ranking_threshold", "holding_period_rule", "confidence_calibration"} <= baseline_types

        # Apply suppression — source_weight should be removed.
        svc.apply_outcome_feedback({"source_weight"})
        filtered = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary=self._attribution_that_produces_all_rules(),
        )
        filtered_types = {p.proposal_type.value for p in filtered}
        assert "source_weight" not in filtered_types
        # Other types still present.
        assert "ranking_threshold" in filtered_types

    def test_apply_outcome_feedback_none_clears_suppression(self) -> None:
        from services.self_improvement.service import SelfImprovementService

        svc = SelfImprovementService()
        svc.apply_outcome_feedback({"source_weight"})
        svc.apply_outcome_feedback(None)
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary=self._attribution_that_produces_all_rules(),
        )
        types = {p.proposal_type.value for p in proposals}
        assert "source_weight" in types

    def test_default_suppressed_types_is_empty(self) -> None:
        from services.self_improvement.service import SelfImprovementService

        svc = SelfImprovementService()
        # Default construction should not drop anything.
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary=self._attribution_that_produces_all_rules(),
        )
        assert len(proposals) > 0


# ---------------------------------------------------------------------------
# Worker job flag-off path
# ---------------------------------------------------------------------------


class TestWorkerJobFlagOff:
    def test_flag_off_returns_noop_summary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.worker.jobs import proposal_outcome_assessment as job_mod

        class _FakeSettings:
            proposal_outcome_ledger_enabled = False

        monkeypatch.setattr(job_mod, "get_settings", lambda: _FakeSettings())
        summary = job_mod.run_proposal_outcome_assessment()
        assert summary == {
            "considered": 0,
            "assessed": 0,
            "skipped": 0,
            "flag_off": True,
        }


# ---------------------------------------------------------------------------
# Settings integration
# ---------------------------------------------------------------------------


class TestSettingsIntegration:
    def test_settings_exposes_ledger_flag_default_false(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert hasattr(s, "proposal_outcome_ledger_enabled")
        assert s.proposal_outcome_ledger_enabled is False

    def test_settings_min_observations_default(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert s.proposal_outcome_min_observations == 10

    def test_settings_diversity_floor_default(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert s.proposal_outcome_diversity_floor_days == 31

    def test_ledger_flag_settable_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config.settings import Settings

        monkeypatch.setenv("APIS_PROPOSAL_OUTCOME_LEDGER_ENABLED", "true")
        s = Settings()
        assert s.proposal_outcome_ledger_enabled is True
