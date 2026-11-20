"""Candidate pairs (stage signature only): attribute-group interval sweep."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from trace_core.models.claims import ClaimRecord
from trace_core.stage_types import Pair


def candidate_pairs(
    eligible: Sequence[ClaimRecord], ontology_groups: Mapping[str, str]
) -> Iterator[Pair]:
    raise NotImplementedError("M2/M3")
