"""Integrity re-walk (D-04, SYSTEM_DESIGN 9): the green/red badge.

Three independent checks, all recomputed from stored content:
- records: every claim's id and record hash match its content;
- snapshot: the version's `manifest_hash` equals the one recomputed from its own content;
- chain: every version's `parent_manifest_hash` equals its parent's manifest hash, back to v1;
and, when a byte reader is supplied, the stored source bytes still hash to `Source.sha256`
(derived telemetry partitions are checked against their partition hash by the telemetry port).
Failure strings are constant phrases with ids (never document text).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from trace_core.ids import verify_claim
from trace_core.models.case import CaseVersion, IntegrityResult
from trace_core.snapshot.manifest import ZERO, manifest_hash_of

BlobSha = Callable[[str], str | None]
"""sha256 of the bytes actually stored under a source hash, or None when missing."""


def _zeroed(version: CaseVersion) -> CaseVersion:
    state = version.views.state.model_copy(update={"manifest_hash": ZERO})
    return version.model_copy(
        update={
            "manifest_hash": ZERO,
            "views": version.views.model_copy(update={"state": state}),
        }
    )


def snapshot_matches(version: CaseVersion) -> bool:
    recomputed = manifest_hash_of(_zeroed(version), version.views.state.sources)
    return recomputed == version.manifest_hash == version.views.state.manifest_hash


def verify_chain(
    versions: Sequence[CaseVersion], blob_sha: BlobSha | None = None
) -> IntegrityResult:
    """`versions` is the full chain v1..vN in order; the result is about vN."""
    if not versions:
        raise ValueError("an empty chain has no version to verify")
    failures: list[str] = []
    chain_ok = snapshot_ok = records_ok = True
    for index, version in enumerate(versions):
        label = f"v{version.version}"
        if version.version != index + 1:
            chain_ok = False
            failures.append(f"chain: {label} is out of order")
        expected_parent = versions[index - 1].manifest_hash if index else None
        if version.parent_manifest_hash != expected_parent:
            chain_ok = False
            failures.append(f"chain: {label} does not link to its parent")
        if not snapshot_matches(version):
            snapshot_ok = False
            failures.append(f"snapshot: {label} manifest hash mismatch")
        for claim in version.records.claims:
            if not verify_claim(claim):
                records_ok = False
                failures.append(f"records: {label} claim {claim.claim_id} fails its hash")
    if blob_sha is not None:
        for source in versions[-1].views.state.sources:
            if source.held_reason is not None or source.modality == "sensor":
                continue  # held raws are not stored; telemetry is a derived Parquet partition
            if blob_sha(source.sha256) != source.sha256:
                records_ok = False
                failures.append(f"records: stored bytes of source {source.source_id} changed")
    return IntegrityResult(
        ok=chain_ok and snapshot_ok and records_ok,
        version=versions[-1].version,
        chain_ok=chain_ok,
        snapshot_ok=snapshot_ok,
        records_ok=records_ok,
        failures=failures,
    )
