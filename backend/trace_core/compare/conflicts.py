"""Conflict grouping (B-08 minimal). One ConflictRecord per connected set of disagreeing claims.
Conflicts are never averaged: both sides are kept and `averaged` is always False (promise 1).

TODO(M3): error/failure rows as `supporting_context`; "explained" review state.
"""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.compare.quantifiers import sensor_state_of
from trace_core.ids import conflict_id
from trace_core.models.claims import ClaimRecord
from trace_core.models.records import ComparisonRecord, ConflictRecord, Magnitude

UNIT = "unitless (z)"


def _components(pairs: Sequence[tuple[str, str]]) -> list[set[str]]:
    groups: list[set[str]] = []
    for a, b in pairs:
        touching = [g for g in groups if a in g or b in g]
        merged = {a, b}.union(*touching) if touching else {a, b}
        groups = [g for g in groups if g not in touching]
        groups.append(merged)
    return groups


def group_conflicts(
    comparisons: Sequence[ComparisonRecord], claims: Sequence[ClaimRecord]
) -> list[ConflictRecord]:
    by_id = {c.claim_id: c for c in claims}
    disagreeing = [c for c in comparisons if c.outcome == "disagree"]
    out: list[ConflictRecord] = []
    for component in sorted(
        _components([(c.claim_a, c.claim_b) for c in disagreeing]), key=lambda g: sorted(g)
    ):
        sides = sorted(component)
        context = sorted(
            c.claim_id
            for c in claims
            if c.claim_id not in component and any(s in c.derived_from for s in sides)
        )
        numbers = next(
            (st for st in (sensor_state_of(by_id[s]) for s in sides if s in by_id) if st), None
        )
        out.append(
            ConflictRecord(
                conflict_id=conflict_id(sides),
                comparison_ids=sorted(
                    c.comparison_id for c in disagreeing if c.claim_a in component
                ),
                sides=sides,
                supporting_context=context,
                magnitude=Magnitude(
                    statistic="robust_max_z",
                    observed=numbers.t_d if numbers else None,
                    threshold=numbers.t_star if numbers else None,
                    unit=UNIT,
                ),
                averaged=False,
            )
        )
    return out
