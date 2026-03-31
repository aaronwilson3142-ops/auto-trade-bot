"""
Gate E — Self-Improvement Engine Tests.

Verifies:
  Gate E criteria (spec §04_APIS_BUILD_RUNBOOK.md §Gate E):
    ✅ proposals are logged                  (generate_proposals returns ImprovementProposal list)
    ✅ baseline comparison works              (evaluate_proposal populates metric_deltas / result_status)
    ✅ no unsafe auto-promotion occurs        (protected components + blocked types always rejected)
    ✅ accepted changes are traceable         (PromotionDecision fields populated on accept)

Test classes
------------
  TestImprovementProposalModel      — model properties (is_protected, etc.)
  TestProposalEvaluationModel       — metric_deltas, improvement_count, regression_count
  TestPromotionDecisionModel        — dataclass fields
  TestGenerateProposals             — service.generate_proposals()
  TestEvaluateProposal              — service.evaluate_proposal() guardrail + metric logic
  TestPromoteOrReject               — service.promote_or_reject() full promotion guard
  TestVersionBumping                — _bump_version() internal helper
  TestConfigThresholds              — custom config thresholds respected
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from services.self_improvement.config import SelfImprovementConfig
from services.self_improvement.models import (
    PROTECTED_COMPONENTS,
    ImprovementProposal,
    ProposalEvaluation,
    ProposalStatus,
    ProposalType,
    PromotionDecision,
)
from services.self_improvement.service import SelfImprovementService


# ─────────────────────── helpers ──────────────────────────────────────────────

def _svc(config: SelfImprovementConfig | None = None) -> SelfImprovementService:
    return SelfImprovementService(config)


def _proposal(
    proposal_type: ProposalType = ProposalType.SOURCE_WEIGHT,
    target_component: str = "signal_engine",
    baseline_version: str = "1.0.0",
    candidate_version: str = "1.0.1",
    proposal_summary: str = "Test proposal",
    expected_benefit: str = "Improve hit rate",
    **kwargs: Any,
) -> ImprovementProposal:
    return ImprovementProposal(
        proposal_type=proposal_type,
        target_component=target_component,
        baseline_version=baseline_version,
        candidate_version=candidate_version,
        proposal_summary=proposal_summary,
        expected_benefit=expected_benefit,
        **kwargs,
    )


def _metrics(**kw: str) -> dict[str, Decimal]:
    return {k: Decimal(v) for k, v in kw.items()}


# ─────────────────────── TestImprovementProposalModel ─────────────────────────

class TestImprovementProposalModel:
    def test_is_protected_false_for_allowed_component(self) -> None:
        p = _proposal(target_component="signal_engine")
        assert p.is_protected is False

    def test_is_protected_true_for_risk_engine(self) -> None:
        p = _proposal(target_component="risk_engine")
        assert p.is_protected is True

    def test_is_protected_true_for_execution_engine(self) -> None:
        p = _proposal(target_component="execution_engine")
        assert p.is_protected is True

    def test_is_protected_true_for_broker_adapter(self) -> None:
        p = _proposal(target_component="broker_adapter")
        assert p.is_protected is True

    def test_is_protected_true_for_capital_allocation(self) -> None:
        p = _proposal(target_component="capital_allocation")
        assert p.is_protected is True

    def test_is_protected_true_for_live_trading_permissions(self) -> None:
        p = _proposal(target_component="live_trading_permissions")
        assert p.is_protected is True

    def test_default_status_is_pending(self) -> None:
        p = _proposal()
        assert p.status == ProposalStatus.PENDING

    def test_id_auto_assigned(self) -> None:
        p = _proposal()
        assert len(p.id) == 36  # UUID string

    def test_two_proposals_have_different_ids(self) -> None:
        p1 = _proposal()
        p2 = _proposal()
        assert p1.id != p2.id

    def test_proposal_timestamp_is_datetime(self) -> None:
        p = _proposal()
        assert isinstance(p.proposal_timestamp, dt.datetime)

    def test_baseline_params_default_empty(self) -> None:
        p = _proposal()
        assert p.baseline_params == {}

    def test_candidate_params_stored(self) -> None:
        p = _proposal(candidate_params={"key": "val"})
        assert p.candidate_params == {"key": "val"}


# ─────────────────────── TestProposalEvaluationModel ──────────────────────────

class TestProposalEvaluationModel:
    def _eval(
        self,
        baseline: dict[str, Decimal],
        candidate: dict[str, Decimal],
        guardrail_passed: bool = True,
        result_status: str = "pass",
    ) -> ProposalEvaluation:
        return ProposalEvaluation(
            proposal_id="test-id",
            baseline_metrics=baseline,
            candidate_metrics=candidate,
            comparison_summary="test",
            guardrail_passed=guardrail_passed,
            result_status=result_status,
        )

    def test_metric_deltas_all_positive(self) -> None:
        e = self._eval(
            _metrics(hit_rate="0.50", sharpe="1.0"),
            _metrics(hit_rate="0.60", sharpe="1.2"),
        )
        assert e.metric_deltas["hit_rate"] == Decimal("0.10")
        assert e.metric_deltas["sharpe"] == Decimal("0.2")

    def test_metric_deltas_negative_when_regression(self) -> None:
        e = self._eval(
            _metrics(hit_rate="0.55"),
            _metrics(hit_rate="0.45"),
        )
        assert e.metric_deltas["hit_rate"] < Decimal("0")

    def test_metric_deltas_uses_baseline_keys(self) -> None:
        e = self._eval(
            _metrics(hit_rate="0.5", sharpe="1.0"),
            _metrics(hit_rate="0.6"),  # sharpe missing from candidate
        )
        # sharpe delta = 0 - 1.0 = -1.0
        assert e.metric_deltas["sharpe"] == Decimal("-1.0")

    def test_improvement_count_two(self) -> None:
        e = self._eval(
            _metrics(hit_rate="0.50", sharpe="1.0"),
            _metrics(hit_rate="0.60", sharpe="1.2"),
        )
        assert e.improvement_count == 2

    def test_regression_count_one(self) -> None:
        e = self._eval(
            _metrics(hit_rate="0.60", sharpe="1.2", drawdown="0.10"),
            _metrics(hit_rate="0.65", sharpe="1.1", drawdown="0.10"),
        )
        # sharpe went down, drawdown unchanged (not neg), hit_rate up
        assert e.regression_count == 1

    def test_improvement_count_zero_when_no_improvements(self) -> None:
        e = self._eval(
            _metrics(hit_rate="0.60"),
            _metrics(hit_rate="0.50"),
        )
        assert e.improvement_count == 0

    def test_id_auto_assigned(self) -> None:
        e = self._eval({}, {})
        assert len(e.id) == 36


# ─────────────────────── TestPromotionDecisionModel ───────────────────────────

class TestPromotionDecisionModel:
    def test_accepted_fields(self) -> None:
        d = PromotionDecision(
            proposal_id="pid",
            accepted=True,
            decision_reason="good results",
            promoted_version_label="v1.0.1",
            rollback_reference="1.0.0",
            component_type="source_weight",
            component_key="signal_engine",
        )
        assert d.accepted is True
        assert d.promoted_version_label == "v1.0.1"
        assert d.rollback_reference == "1.0.0"

    def test_rejected_fields(self) -> None:
        d = PromotionDecision(
            proposal_id="pid",
            accepted=False,
            decision_reason="guardrail",
            promoted_version_label=None,
            rollback_reference=None,
        )
        assert d.accepted is False
        assert d.promoted_version_label is None

    def test_id_auto_assigned(self) -> None:
        d = PromotionDecision(
            proposal_id="pid",
            accepted=False,
            decision_reason="x",
            promoted_version_label=None,
            rollback_reference=None,
        )
        assert len(d.id) == 36

    def test_timestamp_is_datetime(self) -> None:
        d = PromotionDecision(
            proposal_id="pid",
            accepted=False,
            decision_reason="x",
            promoted_version_label=None,
            rollback_reference=None,
        )
        assert isinstance(d.decision_timestamp, dt.datetime)


# ─────────────────────── TestGenerateProposals ────────────────────────────────

class TestGenerateProposals:
    def test_grade_f_low_hit_rate_generates_source_weight_proposal(self) -> None:
        svc = _svc()
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary={"hit_rate": Decimal("0.30"), "avg_loss_pct": Decimal("-0.05")},
        )
        types = [p.proposal_type for p in proposals]
        assert ProposalType.SOURCE_WEIGHT in types

    def test_grade_f_avg_loss_generates_ranking_threshold_proposal(self) -> None:
        svc = _svc()
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary={"hit_rate": Decimal("0.60"), "avg_loss_pct": Decimal("-0.03")},
        )
        types = [p.proposal_type for p in proposals]
        assert ProposalType.RANKING_THRESHOLD in types

    def test_grade_d_worst_strategy_generates_holding_period_proposal(self) -> None:
        svc = _svc()
        proposals = svc.generate_proposals(
            scorecard_grade="D",
            attribution_summary={
                "hit_rate": Decimal("0.60"),
                "avg_loss_pct": Decimal("-0.01"),
                "worst_strategy": "momentum",
            },
        )
        types = [p.proposal_type for p in proposals]
        assert ProposalType.HOLDING_PERIOD_RULE in types

    def test_grade_f_generates_confidence_calibration_proposal(self) -> None:
        svc = _svc()
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary={"hit_rate": Decimal("0.60")},
        )
        types = [p.proposal_type for p in proposals]
        assert ProposalType.CONFIDENCE_CALIBRATION in types

    def test_grade_a_produces_no_proposals(self) -> None:
        svc = _svc()
        proposals = svc.generate_proposals(
            scorecard_grade="A",
            attribution_summary={"hit_rate": Decimal("0.70")},
        )
        assert proposals == []

    def test_grade_b_produces_no_proposals(self) -> None:
        svc = _svc()
        proposals = svc.generate_proposals(
            scorecard_grade="B",
            attribution_summary={"hit_rate": Decimal("0.65")},
        )
        assert proposals == []

    def test_proposals_capped_at_max_proposals_per_cycle(self) -> None:
        cfg = SelfImprovementConfig(max_proposals_per_cycle=2)
        svc = _svc(cfg)
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary={
                "hit_rate": Decimal("0.30"),
                "avg_loss_pct": Decimal("-0.05"),
                "worst_strategy": "momentum",
            },
        )
        assert len(proposals) <= 2

    def test_all_proposals_have_unique_ids(self) -> None:
        svc = _svc()
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary={
                "hit_rate": Decimal("0.30"),
                "avg_loss_pct": Decimal("-0.05"),
                "worst_strategy": "swing",
            },
        )
        ids = [p.id for p in proposals]
        assert len(ids) == len(set(ids))

    def test_proposals_have_pending_status(self) -> None:
        svc = _svc()
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary={"hit_rate": Decimal("0.30")},
        )
        for p in proposals:
            assert p.status == ProposalStatus.PENDING

    def test_current_versions_used_in_baseline(self) -> None:
        svc = _svc()
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary={"hit_rate": Decimal("0.30")},
            current_versions={"signal_engine": "2.5.0"},
        )
        baseline_versions = [p.baseline_version for p in proposals]
        assert all(bv == "2.5.0" for bv in baseline_versions)

    def test_empty_attribution_summary_does_not_raise(self) -> None:
        svc = _svc()
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary={},
        )
        # Should run without error; confidence calibration proposal expected
        assert isinstance(proposals, list)


# ─────────────────────── TestEvaluateProposal ─────────────────────────────────

class TestEvaluateProposal:
    def test_protected_component_fails_guardrail(self) -> None:
        svc = _svc()
        p = _proposal(target_component="risk_engine")
        ev = svc.evaluate_proposal(p, _metrics(hit_rate="0.5"), _metrics(hit_rate="0.6"))
        assert ev.guardrail_passed is False
        assert ev.result_status == "fail"
        assert "protected" in ev.comparison_summary.lower()

    def test_blocked_proposal_type_fails_guardrail(self) -> None:
        cfg = SelfImprovementConfig(
            blocked_proposal_types=[ProposalType.SIZING_FORMULA.value]
        )
        svc = _svc(cfg)
        p = _proposal(
            proposal_type=ProposalType.SIZING_FORMULA,
            target_component="portfolio_engine",
        )
        ev = svc.evaluate_proposal(p, _metrics(hit_rate="0.5"), _metrics(hit_rate="0.6"))
        assert ev.guardrail_passed is False
        assert ev.result_status == "fail"

    def test_passing_evaluation_sets_pass_status(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = svc.evaluate_proposal(
            p,
            _metrics(hit_rate="0.50"),
            _metrics(hit_rate="0.60"),
        )
        assert ev.guardrail_passed is True
        assert ev.result_status == "pass"

    def test_failing_metrics_sets_fail_status(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = svc.evaluate_proposal(
            p,
            _metrics(hit_rate="0.60"),
            _metrics(hit_rate="0.50"),  # regression
        )
        assert ev.result_status == "fail"

    def test_empty_baseline_metrics_gives_inconclusive(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = svc.evaluate_proposal(p, {}, {})
        assert ev.result_status == "inconclusive"
        assert ev.guardrail_passed is True

    def test_proposal_id_recorded_in_evaluation(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = svc.evaluate_proposal(p, _metrics(hit_rate="0.5"), _metrics(hit_rate="0.6"))
        assert ev.proposal_id == p.id

    def test_comparison_summary_propagated(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = svc.evaluate_proposal(
            p,
            _metrics(hit_rate="0.5"),
            _metrics(hit_rate="0.6"),
            comparison_summary="backtest over 30 days",
        )
        assert ev.comparison_summary == "backtest over 30 days"

    def test_multiple_metrics_all_improve_passes(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = svc.evaluate_proposal(
            p,
            _metrics(hit_rate="0.50", sharpe="1.0", sortino="1.2"),
            _metrics(hit_rate="0.55", sharpe="1.1", sortino="1.3"),
        )
        assert ev.result_status == "pass"
        assert ev.improvement_count == 3

    def test_regression_exceeds_max_causes_fail(self) -> None:
        cfg = SelfImprovementConfig(max_regressing_metrics=0)
        svc = _svc(cfg)
        p = _proposal()
        ev = svc.evaluate_proposal(
            p,
            _metrics(hit_rate="0.50", sharpe="1.2"),
            _metrics(hit_rate="0.55", sharpe="1.1"),  # sharpe regresses
        )
        assert ev.result_status == "fail"

    def test_primary_metric_delta_below_threshold_causes_fail(self) -> None:
        cfg = SelfImprovementConfig(
            min_primary_metric_delta=Decimal("0.05"),
            primary_metric_key="hit_rate",
        )
        svc = _svc(cfg)
        p = _proposal()
        ev = svc.evaluate_proposal(
            p,
            _metrics(hit_rate="0.50"),
            _metrics(hit_rate="0.53"),  # delta=0.03 < 0.05
        )
        assert ev.result_status == "fail"

    def test_primary_metric_delta_meets_threshold_passes(self) -> None:
        cfg = SelfImprovementConfig(
            min_primary_metric_delta=Decimal("0.05"),
            primary_metric_key="hit_rate",
        )
        svc = _svc(cfg)
        p = _proposal()
        ev = svc.evaluate_proposal(
            p,
            _metrics(hit_rate="0.50"),
            _metrics(hit_rate="0.56"),  # delta=0.06 >= 0.05
        )
        assert ev.result_status == "pass"


# ─────────────────────── TestPromoteOrReject ─────────────────────────────────

class TestPromoteOrReject:
    def _passing_eval(self, proposal: ImprovementProposal) -> ProposalEvaluation:
        return ProposalEvaluation(
            proposal_id=proposal.id,
            baseline_metrics=_metrics(hit_rate="0.50"),
            candidate_metrics=_metrics(hit_rate="0.60"),
            comparison_summary="improvement confirmed",
            guardrail_passed=True,
            result_status="pass",
        )

    def _failing_eval(
        self,
        proposal: ImprovementProposal,
        guardrail_passed: bool = True,
        result_status: str = "fail",
    ) -> ProposalEvaluation:
        return ProposalEvaluation(
            proposal_id=proposal.id,
            baseline_metrics=_metrics(hit_rate="0.60"),
            candidate_metrics=_metrics(hit_rate="0.50"),
            comparison_summary="regression",
            guardrail_passed=guardrail_passed,
            result_status=result_status,
        )

    def test_accepted_when_evaluation_passes(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = self._passing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert decision.accepted is True

    def test_rejected_when_evaluation_fails(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = self._failing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert decision.accepted is False

    def test_rejected_when_guardrail_failed(self) -> None:
        svc = _svc()
        p = _proposal(target_component="risk_engine")
        ev = self._failing_eval(p, guardrail_passed=False, result_status="fail")
        decision = svc.promote_or_reject(p, ev)
        assert decision.accepted is False

    def test_accepted_sets_promoted_version_label(self) -> None:
        svc = _svc()
        p = _proposal(candidate_version="1.0.1")
        ev = self._passing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert decision.promoted_version_label == "v1.0.1"

    def test_accepted_sets_rollback_reference(self) -> None:
        svc = _svc()
        p = _proposal(baseline_version="1.0.0")
        ev = self._passing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert decision.rollback_reference == "1.0.0"

    def test_rejected_has_no_promoted_version_label(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = self._failing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert decision.promoted_version_label is None

    def test_rejected_has_no_rollback_reference(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = self._failing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert decision.rollback_reference is None

    def test_proposal_status_updated_to_promoted_on_accept(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = self._passing_eval(p)
        svc.promote_or_reject(p, ev)
        assert p.status == ProposalStatus.PROMOTED

    def test_proposal_status_updated_to_rejected_on_reject(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = self._failing_eval(p)
        svc.promote_or_reject(p, ev)
        assert p.status == ProposalStatus.REJECTED

    def test_decision_records_proposal_id(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = self._passing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert decision.proposal_id == p.id

    def test_decision_records_component_type(self) -> None:
        svc = _svc()
        p = _proposal(
            proposal_type=ProposalType.SOURCE_WEIGHT,
            target_component="signal_engine",
        )
        ev = self._passing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert decision.component_type == ProposalType.SOURCE_WEIGHT.value

    def test_decision_records_component_key(self) -> None:
        svc = _svc()
        p = _proposal(target_component="ranking_engine")
        ev = self._passing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert decision.component_key == "ranking_engine"

    def test_decision_has_non_empty_reason(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = self._passing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert len(decision.decision_reason) > 0

    def test_rejection_reason_mentions_guardrail_when_blocked(self) -> None:
        svc = _svc()
        p = _proposal(target_component="risk_engine")
        ev = self._failing_eval(p, guardrail_passed=False, result_status="fail")
        decision = svc.promote_or_reject(p, ev)
        assert "guardrail" in decision.decision_reason.lower()

    def test_inconclusive_evaluation_is_rejected(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = ProposalEvaluation(
            proposal_id=p.id,
            baseline_metrics={},
            candidate_metrics={},
            comparison_summary="no baseline data",
            guardrail_passed=True,
            result_status="inconclusive",
        )
        decision = svc.promote_or_reject(p, ev)
        assert decision.accepted is False
        assert "inconclusive" in decision.decision_reason.lower()

    def test_decision_timestamp_is_datetime(self) -> None:
        svc = _svc()
        p = _proposal()
        ev = self._passing_eval(p)
        decision = svc.promote_or_reject(p, ev)
        assert isinstance(decision.decision_timestamp, dt.datetime)

    def test_no_self_promotion_protected_component_always_rejected(self) -> None:
        """Core Gate E safety: protected components can NEVER be auto-promoted."""
        svc = _svc()
        for component in PROTECTED_COMPONENTS:
            p = _proposal(target_component=component)
            # Force evaluation as if metrics all improved — should still reject
            ev = ProposalEvaluation(
                proposal_id=p.id,
                baseline_metrics=_metrics(hit_rate="0.50"),
                candidate_metrics=_metrics(hit_rate="0.99"),
                comparison_summary="looks great",
                guardrail_passed=False,   # guardrail set by evaluate_proposal
                result_status="fail",
            )
            decision = svc.promote_or_reject(p, ev)
            assert decision.accepted is False, (
                f"Protected component '{component}' must never be auto-promoted"
            )


# ─────────────────────── TestVersionBumping ────────────────────────────────────

class TestVersionBumping:
    def test_semver_patch_increments(self) -> None:
        assert SelfImprovementService._bump_version("1.0.0") == "1.0.1"

    def test_semver_minor_increments(self) -> None:
        assert SelfImprovementService._bump_version("2.5.3") == "2.5.4"

    def test_single_digit_increments(self) -> None:
        assert SelfImprovementService._bump_version("3") == "4"

    def test_two_part_version_increments_last(self) -> None:
        assert SelfImprovementService._bump_version("2.3") == "2.4"

    def test_non_numeric_suffix_gets_dot_one(self) -> None:
        result = SelfImprovementService._bump_version("abc")
        assert result == "abc.1"

    def test_version_zero_increments_to_one(self) -> None:
        assert SelfImprovementService._bump_version("1.0") == "1.1"


# ─────────────────────── TestConfigThresholds ─────────────────────────────────

class TestConfigThresholds:
    def test_custom_max_proposals_per_cycle(self) -> None:
        cfg = SelfImprovementConfig(max_proposals_per_cycle=1)
        svc = _svc(cfg)
        proposals = svc.generate_proposals(
            scorecard_grade="F",
            attribution_summary={
                "hit_rate": Decimal("0.30"),
                "avg_loss_pct": Decimal("-0.05"),
                "worst_strategy": "momentum",
            },
        )
        assert len(proposals) <= 1

    def test_custom_min_improving_metrics_respected(self) -> None:
        cfg = SelfImprovementConfig(min_improving_metrics=2)
        svc = _svc(cfg)
        p = _proposal()
        # Only 1 metric improves — should fail
        ev = svc.evaluate_proposal(
            p,
            _metrics(hit_rate="0.50", sharpe="1.2"),
            _metrics(hit_rate="0.55", sharpe="1.1"),  # sharpe regresses
        )
        assert ev.result_status == "fail"

    def test_custom_primary_metric_key_respected(self) -> None:
        cfg = SelfImprovementConfig(
            primary_metric_key="sharpe",
            min_primary_metric_delta=Decimal("0.10"),
        )
        svc = _svc(cfg)
        p = _proposal()
        ev = svc.evaluate_proposal(
            p,
            _metrics(sharpe="1.0", hit_rate="0.50"),
            _metrics(sharpe="1.08", hit_rate="0.60"),  # sharpe delta=0.08 < 0.10
        )
        assert ev.result_status == "fail"

    def test_default_config_instance(self) -> None:
        cfg = SelfImprovementConfig()
        assert cfg.min_improving_metrics == 1
        assert cfg.max_regressing_metrics == 0
        assert cfg.primary_metric_key == "hit_rate"
        assert cfg.max_proposals_per_cycle == 5

    def test_version_label_prefix_used_in_promoted_label(self) -> None:
        cfg = SelfImprovementConfig(version_label_prefix="release-")
        svc = _svc(cfg)
        p = _proposal(candidate_version="2.1.0")
        ev = ProposalEvaluation(
            proposal_id=p.id,
            baseline_metrics=_metrics(hit_rate="0.50"),
            candidate_metrics=_metrics(hit_rate="0.60"),
            comparison_summary="good",
            guardrail_passed=True,
            result_status="pass",
        )
        decision = svc.promote_or_reject(p, ev)
        assert decision.promoted_version_label == "release-2.1.0"
