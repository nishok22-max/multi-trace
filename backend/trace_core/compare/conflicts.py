"""Conflict grouping (stage signature only). Conflicts are never averaged."""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.models.claims import ClaimRecord
from trace_core.models.records import ComparisonRecord, ConflictRecord


def group_conflicts(
    comparisons: Sequence[ComparisonRecord], claims: Sequence[ClaimRecord]
) -> list[ConflictRecord]:
    raise NotImplementedError("M2/M3")
