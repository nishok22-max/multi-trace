"""Candidate pairs (B-08 minimal): same entity, same attribute group, overlapping valid time.

Claims related by `derived_from` (a parent and its child) are never paired with each other.
Unresolved entities never pair. A claim with unknown time is paired with the rest of its group
so the gate can say "time unknown" instead of silently dropping it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from trace_core.models.claims import ClaimRecord
from trace_core.models.time import Interval
from trace_core.stage_types import Pair


def _related(a: ClaimRecord, b: ClaimRecord) -> bool:
    return a.claim_id in b.derived_from or b.claim_id in a.derived_from


def _interval(claim: ClaimRecord) -> Interval | None:
    vt = claim.temporal.valid_time
    return vt if isinstance(vt, Interval) else None


def _start(claim: ClaimRecord) -> str:
    span = _interval(claim)
    return span.start if span is not None else ""


def candidate_pairs(
    eligible: Sequence[ClaimRecord], ontology_groups: Mapping[str, str]
) -> Iterator[Pair]:
    buckets: dict[tuple[str, str], list[ClaimRecord]] = {}
    for claim in eligible:
        group = ontology_groups.get(claim.attribute)
        entity = claim.subject.entity_id
        if group is None or entity is None or claim.subject.link_status != "resolved":
            continue
        buckets.setdefault((entity, group), []).append(claim)
    for key in sorted(buckets):
        members = sorted(buckets[key], key=lambda c: (_start(c), c.claim_id))
        timed = [c for c in members if _interval(c) is not None]
        untimed = [c for c in members if _interval(c) is None]
        active: list[ClaimRecord] = []
        for claim in timed:
            span = _interval(claim)
            assert span is not None  # noqa: S101
            active = [a for a in active if (_interval(a) or span).end > span.start]
            for other in active:
                if not _related(other, claim):
                    yield other, claim
            active.append(claim)
        for claim in untimed:
            for other in members:
                if other.claim_id != claim.claim_id and not _related(other, claim):
                    if other in untimed and other.claim_id < claim.claim_id:
                        continue  # each unordered pair once
                    yield other, claim
