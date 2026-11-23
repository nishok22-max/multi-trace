"""Snapshot (D-04 minimal): record hashes, views, parent-chained manifest hash.

`manifest_hash(v) = sha256(parent_manifest_hash || sorted record hashes || config_hash ||
engine_sha || lockfile_hash || sorted source shas || snapshot_sha256)` (SYSTEM_DESIGN 9).
`snapshot_sha256` hashes the whole version body with the manifest hash slots zeroed and every
wall-clock field dropped, so a rebuild at another time yields the same manifest hash.
"""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.canonical import canonical_sha256, record_hash
from trace_core.models.case import (
    Case,
    CaseState,
    CaseVersion,
    VersionRecords,
    Views,
)
from trace_core.models.records import Source
from trace_core.normalise.time import fmt_utc
from trace_core.ports import Clock
from trace_core.snapshot.projections import build_story, build_timeline
from trace_core.stage_types import SnapshotHashes, SnapshotParts

ZERO = "0" * 64


class SnapshotInput(SnapshotParts):
    """`SnapshotParts` plus the sources (needed for `CaseState.sources` and the manifest)."""

    sources: list[Source]


def record_hashes(records: VersionRecords) -> list[str]:
    hashes = [c.record_hash for c in records.claims]
    for group in (
        records.comparisons,
        records.conflicts,
        records.envelopes,
        records.review_items,
        records.decisions,
    ):
        hashes.extend(record_hash(item) for item in group)
    return sorted(hashes)


def manifest_hash_of(draft: CaseVersion, sources: Sequence[Source]) -> str:
    """`manifest_hash` of a version whose manifest slots are zeroed (see module docstring).
    `snapshot_sha256` drops every wall-clock field, so the clock never changes the hash."""
    return canonical_sha256(
        {
            "parent": draft.parent_manifest_hash,
            "records": record_hashes(draft.records),
            "config_hash": draft.config_hash,
            "engine_sha": draft.engine_sha,
            "lockfile_hash": draft.lockfile_hash,
            "sources": sorted(s.sha256 for s in sources),
            "snapshot_sha256": canonical_sha256(draft),
        }
    )


def snapshot(
    case: Case,
    parent: CaseVersion | None,
    parts: SnapshotParts,
    hashes: SnapshotHashes,
    clock: Clock,
) -> CaseVersion:
    sources = parts.sources if isinstance(parts, SnapshotInput) else []
    records = parts.records
    version = 1 if parent is None else parent.version + 1
    state = CaseState(
        case_id=case.case_id,
        version=version,
        manifest_hash=ZERO,
        plant_tz=case.plant_tz,
        scope_entities=sorted(case.entities),
        window_start=case.window_start,
        window_end=case.window_end,
        sources=sorted(sources, key=lambda s: s.source_id),
        claim_ids=sorted(c.claim_id for c in records.claims),
        comparison_ids=sorted(c.comparison_id for c in records.comparisons),
        conflict_ids=sorted(c.conflict_id for c in records.conflicts),
        gap_claim_ids=sorted(
            c.claim_id for c in records.claims if c.attribute == "data_availability"
        ),
        decision_ids=sorted(d.decision_id for d in records.decisions),
        review_ids=sorted(r.review_id for r in records.review_items),
    )
    draft = CaseVersion(
        case_id=case.case_id,
        version=version,
        parent_manifest_hash=None if parent is None else parent.manifest_hash,
        manifest_hash=ZERO,
        config_hash=hashes.config_hash,
        engine_sha=hashes.engine_sha,
        lockfile_hash=hashes.lockfile_hash,
        canon_version=hashes.canon_version,
        tesseract_version=hashes.tesseract_version,
        traineddata_sha=hashes.traineddata_sha,
        pdfium_version=hashes.pdfium_version,
        tzdata_version=hashes.tzdata_version,
        llm_mode="off",  # M2 supports only the P0 default; build_case refuses anything else
        ai_status="off",
        records=records,
        views=Views(
            state=state,
            story=build_story(records),
            timeline=build_timeline(records, case.plant_tz),
            review=[],  # TODO(M3): derived review queue
        ),
        created_at=fmt_utc(clock.now_utc()),
    )
    manifest = manifest_hash_of(draft, sources)
    final_state = state.model_copy(update={"manifest_hash": manifest})
    return draft.model_copy(
        update={
            "manifest_hash": manifest,
            "views": draft.views.model_copy(update={"state": final_state}),
        }
    )
