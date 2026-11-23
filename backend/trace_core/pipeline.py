"""Stages 3-4 shared by `build_case` and `rerun_after_decision`: holds -> gate -> conflicts ->
final confidence. Pure; the caller supplies every input."""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.compare.conflicts import group_conflicts
from trace_core.compare.gate import gate
from trace_core.compare.pairs import candidate_pairs
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.records import (
    ComparisonRecord,
    ConflictRecord,
    Decision,
    Envelope,
    ReviewEvent,
    ReviewItem,
    Source,
)
from trace_core.models.time import Interval
from trace_core.review.holds import apply_holds
from trace_core.score.confidence import score
from trace_core.stage_types import GateContext, Provenance

EVENT_ATTRIBUTES = frozenset({"error_event", "failure_event", "maintenance_action"})


def order_claims(claims: Sequence[ClaimRecord]) -> list[ClaimRecord]:
    unique = {c.claim_id: c for c in claims}
    return sorted(
        unique.values(),
        key=lambda c: (
            c.temporal.valid_time.start if isinstance(c.temporal.valid_time, Interval) else "9999",
            c.claim_id,
        ),
    )


def _is_state(claim: ClaimRecord) -> bool:
    return (claim.method.rule_id or "").startswith("state.")


def compare_and_score(
    claims: Sequence[ClaimRecord],
    review_items: Sequence[ReviewItem],
    review_events: Sequence[ReviewEvent],
    decisions: Sequence[Decision],
    envelopes: Sequence[Envelope],
    sources: Sequence[Source],
    config: ConfigBundle,
    cfg_hash: str,
) -> tuple[list[ClaimRecord], list[ComparisonRecord], list[ConflictRecord]]:
    logs = [s for s in sources if s.modality == "table" and s.held_reason is None]
    covered = [s.coverage_period for s in logs]
    ctx = GateContext(
        config=config,
        config_hash=cfg_hash,
        envelopes=list(envelopes),
        events=[c for c in claims if c.attribute in EVENT_ATTRIBUTES],
        # one undeclared log is enough to withdraw "the logs cover the window"
        log_coverage=[c for c in covered if c is not None] if all(covered) else [],
    )
    groups = {rule.attribute_group: rule.attribute_group for rule in config.ontology.phrases}
    eligible, _held = apply_holds(claims, review_items, review_events, decisions, config)
    compared: dict[str, ComparisonRecord] = {}
    judged = [c for c in eligible if c.modality != "sensor" or _is_state(c)]
    for a, b in candidate_pairs(judged, groups):  # held claims never pair
        record = gate(a, b, ctx)
        compared[record.comparison_id] = record
    comparisons = [compared[k] for k in sorted(compared)]
    conflicts = sorted(group_conflicts(comparisons, claims), key=lambda c: c.conflict_id)
    provenance = Provenance(
        derived_from={s.source_id: list(s.derived_from_sources) for s in sources}
    )
    return score(claims, comparisons, provenance, config), comparisons, conflicts
