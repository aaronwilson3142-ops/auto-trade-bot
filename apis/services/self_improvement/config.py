"""
Self-Improvement Engine configuration.

Centralises all tuneable thresholds so tests and service code share the same
defaults and promotion policy is easy to audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class SelfImprovementConfig:
    """Configuration for proposal generation, evaluation, and promotion.

    Promotion policy (spec §13.3):
    - A proposal may only be promoted when:
        1. guardrail_passed is True (correct proposal type + not protected component)
        2. net_improvement_threshold is met:
           improvement_count >= min_improving_metrics AND
           regression_count   <= max_regressing_metrics
        3. The primary metric delta >= min_primary_metric_delta

    These defaults represent a conservative starting point.
    """

    # ── Evaluation windows ─────────────────────────────────────────────────────
    # Minimum number of metrics that must improve for promotion
    min_improving_metrics: int = 1

    # Maximum metrics allowed to regress for promotion to go through
    max_regressing_metrics: int = 0

    # The primary metric delta (e.g. hit_rate or sharpe) must exceed this
    # minimum value for the promotion to be accepted.  Set to 0.0 to treat
    # any non-negative improvement as acceptable.
    min_primary_metric_delta: Decimal = Decimal("0")

    # ── Which metric is treated as the primary signal ─────────────────────────
    primary_metric_key: str = "hit_rate"

    # ── Proposal generation limits ─────────────────────────────────────────────
    # Max number of proposals generated per daily improvement cycle
    max_proposals_per_cycle: int = 5

    # ── Version labelling ──────────────────────────────────────────────────────
    # Prefix used when building promoted_version_label strings
    version_label_prefix: str = "v"

    # ── Restricted proposal types ─────────────────────────────────────────────
    # Extra proposal types to block for this deployment (empty by default)
    blocked_proposal_types: list[str] = field(default_factory=list)

    # ── Phase 36: Promotion confidence threshold ──────────────────────────────
    # Proposals with confidence_score below this threshold are skipped by
    # auto_execute_promoted() even if their status is PROMOTED.
    # Set to 0.0 to disable confidence gating (allow all PROMOTED proposals).
    min_auto_execute_confidence: float = 0.70
