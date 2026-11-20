"""Value types passed between the pure stage functions (IMPLEMENTATION_PLAN C.3)."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field

from trace_core.models.base import CoreModel, Sha256, SourceId
from trace_core.models.case import VersionRecords
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.records import Envelope, ReviewItem

Pair = tuple[ClaimRecord, ClaimRecord]


class ReadResult(CoreModel):
    claims: list[ClaimRecord]
    review_items: list[ReviewItem] = Field(default_factory=list)


class SensorWindows(CoreModel):
    """Day and hour window claims plus gap claims. Duplicates with different values become
    GapClaim(conflicting_readings); they are never averaged (promise 1)."""

    claims: list[ClaimRecord]
    gap_claims: list[ClaimRecord] = Field(default_factory=list)


class GateContext(CoreModel):
    config: ConfigBundle
    config_hash: Sha256
    envelopes: list[Envelope]


class Provenance(CoreModel):
    """Declared provenance only: source -> sources it was derived from (PRD 10.7)."""

    derived_from: dict[SourceId, list[SourceId]] = Field(default_factory=dict)


class SnapshotParts(CoreModel):
    records: VersionRecords


class SnapshotHashes(CoreModel):
    config_hash: Sha256
    engine_sha: str
    lockfile_hash: Sha256
    canon_version: str
    tesseract_version: str
    traineddata_sha: str
    pdfium_version: str
    tzdata_version: str


ClaimSeq = Sequence[ClaimRecord]
