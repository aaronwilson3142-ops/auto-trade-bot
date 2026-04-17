"""
Self-Improvement Engine Service.

Implements the controlled improvement loop described in spec §13.3:
  1. Ingest evaluation results / attribution
  2. Generate proposals for candidate changes
  3. Evaluate challenger vs baseline
  4. Apply promotion guard — no self-promotion, all accepted changes traceable

Public API
----------
generate_proposals(attribution_summary, scorecard_grade, ...)  → list[ImprovementProposal]
evaluate_proposal(proposal, baseline_metrics, candidate_metrics)  → ProposalEvaluation
promote_or_reject(proposal, evaluation)                           → PromotionDecision

Guardrail rules enforced here
------------------------------
- Protected components (risk_engine, execution_engine, …) → always rejected
- Blocked proposal types from config → always rejected
- Must pass metric thresholds: improvement_count >= min_improving_metrics
  AND regression_count <= max_regressing_metrics
  AND primary_metric_delta >= min_primary_metric_delta
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from config.settings import get_settings
from services.self_improvement.config import SelfImprovementConfig
from services.self_improvement.models import (
    ImprovementProposal,
    PromotionDecision,
    ProposalEvaluation,
    ProposalStatus,
    ProposalType,
)


class SelfImprovementService:
    """Proposal generator, challenger evaluator, and promotion guard."""

    def __init__(self, config: SelfImprovementConfig | None = None) -> None:
        self._config = config or SelfImprovementConfig()
        # Deep-Dive Plan Step 6 Rec 10 — optional outcome-ledger-driven
        # suppression of proposal types whose batting average is too low.
        # Populated by :meth:`apply_outcome_feedback` before generate_proposals
        # is called.  Empty set when the ledger flag is off or no history yet.
        self._suppressed_types: set[str] = set()

    # ── Proposal generation ────────────────────────────────────────────────────

    def apply_outcome_feedback(self, suppressed_types: set[str] | None) -> None:
        """Attach a set of proposal_type values that should be suppressed.

        Callers compute this set via
        :meth:`ProposalOutcomeLedgerService.types_to_suppress` — it's kept
        out of ``generate_proposals``'s hot path so the ledger dependency
        stays optional and the signature doesn't break existing callers.

        Passing ``None`` or an empty set clears the suppression list.
        Flag-gated at the caller: check
        ``settings.proposal_outcome_ledger_enabled`` before populating.
        """
        self._suppressed_types = set(suppressed_types) if suppressed_types else set()

    def generate_proposals(
        self,
        scorecard_grade: str,
        attribution_summary: dict[str, Any],
        current_versions: dict[str, str] | None = None,
    ) -> list[ImprovementProposal]:
        """Generate a list of candidate improvement proposals.

        The engine analyses the scorecard grade and attribution to decide
        *which* components to target.  Only allowed proposal types are
        created; protected components are never targeted.

        Args:
            scorecard_grade:      Single-letter daily grade (A/B/C/D/F) from
                                  the evaluation engine.
            attribution_summary:  Dict summarising performance by dimension.
                                  Expected keys (all optional):
                                    "worst_strategy" str
                                    "worst_ticker" str
                                    "hit_rate" Decimal
                                    "avg_loss_pct" Decimal
            current_versions:     Optional map of component → current version
                                  label used to build baseline_version strings.

        Returns:
            List of ImprovementProposal objects (may be empty).  Capped at
            config.max_proposals_per_cycle.
        """
        versions = current_versions or {}
        proposals: list[ImprovementProposal] = []

        hit_rate = Decimal(
            str(attribution_summary.get("hit_rate", "0"))
        )
        worst_strategy: str = attribution_summary.get("worst_strategy", "")
        avg_loss_pct = Decimal(
            str(attribution_summary.get("avg_loss_pct", "0"))
        )

        # Rule floors sourced from settings (Deep-Dive Plan Step 1).
        _settings = get_settings()
        _hit_rate_floor = Decimal(
            str(getattr(_settings, "source_weight_hit_rate_floor", 0.50))
        )
        _avg_loss_floor = Decimal(
            str(getattr(_settings, "ranking_threshold_avg_loss_floor", -0.02))
        )

        # ── Rule 1: low hit-rate → investigate source weights ─────────────────
        if hit_rate < _hit_rate_floor and scorecard_grade in ("D", "F", "C"):
            proposals.append(
                ImprovementProposal(
                    proposal_type=ProposalType.SOURCE_WEIGHT,
                    target_component="signal_engine",
                    baseline_version=versions.get("signal_engine", "1.0.0"),
                    candidate_version=self._bump_version(
                        versions.get("signal_engine", "1.0.0")
                    ),
                    proposal_summary=(
                        f"Hit rate {float(hit_rate):.1%} below 50 % threshold. "
                        "Reduce weighting on lowest-reliability sources."
                    ),
                    expected_benefit="Improve signal precision; target hit_rate > 0.55",
                )
            )

        # ── Rule 2: consistent losses → adjust ranking threshold ──────────────
        if avg_loss_pct < _avg_loss_floor and scorecard_grade in ("D", "F"):
            proposals.append(
                ImprovementProposal(
                    proposal_type=ProposalType.RANKING_THRESHOLD,
                    target_component="ranking_engine",
                    baseline_version=versions.get("ranking_engine", "1.0.0"),
                    candidate_version=self._bump_version(
                        versions.get("ranking_engine", "1.0.0")
                    ),
                    proposal_summary=(
                        f"Avg loss {float(avg_loss_pct):.2%}. "
                        "Raise minimum composite score threshold for entry."
                    ),
                    expected_benefit="Filter out borderline ideas; reduce avg_loss_pct",
                )
            )

        # ── Rule 3: poor-performing strategy → tune holding period ────────────
        if worst_strategy and scorecard_grade in ("D", "F"):
            proposals.append(
                ImprovementProposal(
                    proposal_type=ProposalType.HOLDING_PERIOD_RULE,
                    target_component="signal_engine",
                    baseline_version=versions.get("signal_engine", "1.0.0"),
                    candidate_version=self._bump_version(
                        versions.get("signal_engine", "1.0.0")
                    ),
                    proposal_summary=(
                        f"Strategy '{worst_strategy}' underperforming. "
                        "Evaluate shorter holding window to cut losers earlier."
                    ),
                    expected_benefit="Reduce holding_days on losing positions",
                    candidate_params={"target_strategy": worst_strategy},
                )
            )

        # ── Rule 4: grade below C → review confidence calibration ─────────────
        if scorecard_grade in ("D", "F"):
            proposals.append(
                ImprovementProposal(
                    proposal_type=ProposalType.CONFIDENCE_CALIBRATION,
                    target_component="signal_engine",
                    baseline_version=versions.get("signal_engine", "1.0.0"),
                    candidate_version=self._bump_version(
                        versions.get("signal_engine", "1.0.0")
                    ),
                    proposal_summary=(
                        f"Daily grade {scorecard_grade}. "
                        "Re-calibrate conviction scores against realised outcomes."
                    ),
                    expected_benefit="Reduce overconfident entries on weak setups",
                )
            )

        # Deep-Dive Plan Step 6 Rec 10 — suppress proposal types that the
        # outcome ledger flagged as regressing more than 50 % of the time.
        # apply_outcome_feedback() is no-op when the ledger flag is off, so
        # this filter is a pass-through in default config.
        if self._suppressed_types:
            proposals = [
                p for p in proposals
                if p.proposal_type.value not in self._suppressed_types
            ]

        # Cap at configured maximum
        return proposals[: self._config.max_proposals_per_cycle]

    # ── Challenger evaluation ──────────────────────────────────────────────────

    def evaluate_proposal(
        self,
        proposal: ImprovementProposal,
        baseline_metrics: dict[str, Decimal],
        candidate_metrics: dict[str, Decimal],
        comparison_summary: str = "",
    ) -> ProposalEvaluation:
        """Run guardrail checks and compare challenger vs baseline metrics.

        Guardrail (spec §13.2 + §4.5):
         - Proposals targeting protected components always fail.
         - Proposals with blocked types always fail.

        Metric pass criteria (configurable):
         - improvement_count >= min_improving_metrics
         - regression_count  <= max_regressing_metrics
         - primary_metric_delta >= min_primary_metric_delta

        The proposal's status field is NOT updated here — that is the
        responsibility of promote_or_reject().

        Args:
            proposal:           The candidate ImprovementProposal.
            baseline_metrics:   Fractional perf metrics for the current version.
            candidate_metrics:  Same keys, values for the challenger version.
            comparison_summary: Optional human-readable description.

        Returns:
            ProposalEvaluation with result_status "pass", "fail", or
            "inconclusive" and guardrail_passed flag.
        """
        # ── Guardrail checks ───────────────────────────────────────────────────
        if proposal.is_protected:
            return ProposalEvaluation(
                proposal_id=proposal.id,
                baseline_metrics=baseline_metrics,
                candidate_metrics=candidate_metrics,
                comparison_summary=(
                    f"GUARDRAIL BLOCKED: '{proposal.target_component}' is a "
                    "protected component and cannot be auto-promoted."
                ),
                guardrail_passed=False,
                result_status="fail",
            )

        if proposal.proposal_type.value in self._config.blocked_proposal_types:
            return ProposalEvaluation(
                proposal_id=proposal.id,
                baseline_metrics=baseline_metrics,
                candidate_metrics=candidate_metrics,
                comparison_summary=(
                    f"GUARDRAIL BLOCKED: proposal type "
                    f"'{proposal.proposal_type.value}' is blocked by config."
                ),
                guardrail_passed=False,
                result_status="fail",
            )

        # ── Metric evaluation ──────────────────────────────────────────────────
        evaluation = ProposalEvaluation(
            proposal_id=proposal.id,
            baseline_metrics=baseline_metrics,
            candidate_metrics=candidate_metrics,
            comparison_summary=comparison_summary,
            guardrail_passed=True,
        )

        cfg = self._config
        primary_delta = evaluation.metric_deltas.get(
            cfg.primary_metric_key, Decimal("0")
        )

        enough_improvements = (
            evaluation.improvement_count >= cfg.min_improving_metrics
        )
        acceptable_regressions = (
            evaluation.regression_count <= cfg.max_regressing_metrics
        )
        primary_ok = primary_delta >= cfg.min_primary_metric_delta

        if not baseline_metrics:
            # No metrics to compare → inconclusive, not a failure
            evaluation.result_status = "inconclusive"
        elif enough_improvements and acceptable_regressions and primary_ok:
            evaluation.result_status = "pass"
        else:
            evaluation.result_status = "fail"

        return evaluation

    # ── Promotion guard ────────────────────────────────────────────────────────

    def promote_or_reject(
        self,
        proposal: ImprovementProposal,
        evaluation: ProposalEvaluation,
    ) -> PromotionDecision:
        """Apply the promotion guard and return the final decision.

        Per spec §4.5: "No strategy or model promotes itself directly."
        This method is the only path to acceptance.

        Acceptance requires:
          - evaluation.guardrail_passed is True
          - evaluation.result_status is "pass"

        "inconclusive" evaluations are rejected with an explanatory reason
        rather than silently ignored.

        The proposal's status is updated in-place to reflect the decision.

        Args:
            proposal:   The ImprovementProposal being decided on.
            evaluation: The corresponding ProposalEvaluation.

        Returns:
            PromotionDecision recording accept/reject with full traceability.
        """
        accepted = (
            evaluation.guardrail_passed
            and evaluation.result_status == "pass"
        )

        if accepted:
            version_label = (
                f"{self._config.version_label_prefix}"
                f"{proposal.candidate_version}"
            )
            reason = (
                f"Candidate version {proposal.candidate_version} "
                f"outperformed baseline {proposal.baseline_version} on "
                f"{evaluation.improvement_count} metric(s) with "
                f"{evaluation.regression_count} regression(s). "
                f"Guardrail passed. Promoted."
            )
            proposal.status = ProposalStatus.PROMOTED
        else:
            version_label = None
            if not evaluation.guardrail_passed:
                reason = f"Rejected — guardrail check failed: {evaluation.comparison_summary}"
            elif evaluation.result_status == "inconclusive":
                reason = (
                    "Rejected — evaluation inconclusive (no baseline metrics "
                    "to compare). Re-run with performance data."
                )
            else:
                cfg = self._config
                primary_delta = evaluation.metric_deltas.get(
                    cfg.primary_metric_key, Decimal("0")
                )
                reason = (
                    f"Rejected — insufficient improvement. "
                    f"improvements={evaluation.improvement_count} "
                    f"(need ≥{cfg.min_improving_metrics}), "
                    f"regressions={evaluation.regression_count} "
                    f"(max {cfg.max_regressing_metrics}), "
                    f"primary_delta={primary_delta} "
                    f"(need ≥{cfg.min_primary_metric_delta})."
                )
            proposal.status = ProposalStatus.REJECTED

        # ── Phase 36: compute and stamp confidence score ──────────────────────
        proposal.confidence_score = self._compute_confidence_score(evaluation)

        return PromotionDecision(
            proposal_id=proposal.id,
            accepted=accepted,
            decision_reason=reason,
            promoted_version_label=version_label,
            rollback_reference=(
                proposal.baseline_version if accepted else None
            ),
            component_type=proposal.proposal_type.value,
            component_key=proposal.target_component,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _compute_confidence_score(self, evaluation: ProposalEvaluation) -> float:
        """Compute a [0.0, 1.0] confidence score for a proposal evaluation.

        Formula (Phase 36):
          improvement_ratio   = improvement_count / max(total_metrics, 1)
          regression_penalty  = 0.2 * regression_count   (capped at 1.0)
          primary_delta_boost = clamp(primary_delta / 0.05, 0.0, 1.0)

          raw = improvement_ratio * (1 - regression_penalty) + 0.2 * primary_delta_boost
          score = clamp(raw, 0.0, 1.0)

        Guardrail-blocked evaluations always receive score 0.0.
        """
        if not evaluation.guardrail_passed:
            return 0.0

        total_metrics = len(evaluation.baseline_metrics)
        if total_metrics == 0:
            return 0.0

        improvement_ratio = evaluation.improvement_count / total_metrics
        regression_penalty = min(0.2 * evaluation.regression_count, 1.0)

        primary_delta = float(
            evaluation.metric_deltas.get(
                self._config.primary_metric_key, Decimal("0")
            )
        )
        primary_boost = min(max(primary_delta / 0.05, 0.0), 1.0)

        raw = improvement_ratio * (1.0 - regression_penalty) + 0.2 * primary_boost
        return round(min(max(raw, 0.0), 1.0), 4)

    @staticmethod
    def _bump_version(version_str: str) -> str:
        """Increment the patch segment of a semver-like string.

        Examples:
          "1.0.0" → "1.0.1"
          "2.3"   → "2.4"      (treat last segment as patch)
          "abc"   → "abc.1"    (non-numeric fallback)
        """
        parts = version_str.split(".")
        if parts and parts[-1].isdigit():
            parts[-1] = str(int(parts[-1]) + 1)
            return ".".join(parts)
        return f"{version_str}.1"
