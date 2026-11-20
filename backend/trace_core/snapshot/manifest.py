"""Snapshot (stage signature only). The manifest hash excludes wall-clock fields."""

from __future__ import annotations

from trace_core.models.case import Case, CaseVersion
from trace_core.ports import Clock
from trace_core.stage_types import SnapshotHashes, SnapshotParts


def snapshot(
    case: Case,
    parent: CaseVersion | None,
    parts: SnapshotParts,
    hashes: SnapshotHashes,
    clock: Clock,
) -> CaseVersion:
    raise NotImplementedError("M2/M3")
