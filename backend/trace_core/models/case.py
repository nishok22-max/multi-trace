"""Case, manifest, CaseVersion and the precomputed views (IMPLEMENTATION_PLAN C.1)."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from trace_core.models.base import (
    CaseId,
    ClaimId,
    ComparisonId,
    ConflictId,
    CoreModel,
    DecisionId,
    EntityId,
    ReviewId,
    Sha256,
    SourceId,
)
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import LlmMode
from trace_core.models.evidence import EvidencePointer
from trace_core.models.records import (
    ComparisonRecord,
    ConflictRecord,
    Decision,
    Envelope,
    Outcome,
    ReviewItem,
    ReviewStatus,
    Source,
)
from trace_core.models.time import UtcStr

AiStatus = Literal["off", "used"]


class Case(CoreModel):
    case_id: CaseId
    title: str
    entities: list[EntityId]
    window_start: UtcStr
    window_end: UtcStr
    plant_tz: str
    created_at: UtcStr

    wall_clock_fields: ClassVar[frozenset[str]] = frozenset({"created_at"})


class Manifest(CoreModel):
    """Input to build_case: the case and its sources (including derived telemetry sources)."""

    case: Case
    sources: list[Source]


# ------------------------------------------------------------------------- the views
class CaseState(CoreModel):
    """Unified Case State (PRD 9.1), reduced to ids. Entities, events, measurements and
    relations are views over claims and are projected later (M2/M3)."""

    case_id: CaseId
    version: int = Field(ge=1)
    manifest_hash: Sha256
    plant_tz: str
    scope_entities: list[EntityId]
    window_start: UtcStr
    window_end: UtcStr
    sources: list[Source]
    claim_ids: list[ClaimId]
    comparison_ids: list[ComparisonId]
    conflict_ids: list[ConflictId]
    gap_claim_ids: list[ClaimId]
    decision_ids: list[DecisionId]
    review_ids: list[ReviewId]


class StoryStep(CoreModel):
    n: int = Field(ge=1, le=5)
    title: str
    text: str
    claim_ids: list[ClaimId] = Field(default_factory=list)
    comparison_ids: list[ComparisonId] = Field(default_factory=list)


class Story(CoreModel):
    """Five-step story. Numbers in `text` are computed, never typed (promise 8)."""

    steps: list[StoryStep]
    headline_outcome: Outcome | None = None


class TimelineEntry(CoreModel):
    entry_id: str
    claim_id: ClaimId
    entity_id: EntityId | None = None
    start: UtcStr | None = None  # None for UnknownTime
    end: UtcStr | None = None
    granularity: Literal["hour", "shift", "day", "unknown"]
    attribute: str
    modality: Literal["text", "table", "image", "sensor", "decision"]
    label: str


class ReviewQueueEntry(CoreModel):
    item: ReviewItem
    status: ReviewStatus
    explained: bool = False


class Views(CoreModel):
    state: CaseState
    story: Story
    timeline: list[TimelineEntry]
    review: list[ReviewQueueEntry]


class VersionRecords(CoreModel):
    claims: list[ClaimRecord]
    comparisons: list[ComparisonRecord]
    conflicts: list[ConflictRecord]
    envelopes: list[Envelope]
    review_items: list[ReviewItem]
    decisions: list[Decision]


class CaseVersion(CoreModel):
    case_id: CaseId
    version: int = Field(ge=1)
    parent_manifest_hash: Sha256 | None = None
    manifest_hash: Sha256
    config_hash: Sha256
    engine_sha: str
    lockfile_hash: Sha256
    canon_version: str
    tesseract_version: str
    traineddata_sha: str
    pdfium_version: str
    tzdata_version: str
    llm_mode: LlmMode
    ai_status: AiStatus
    records: VersionRecords
    views: Views
    created_at: UtcStr | None = None

    wall_clock_fields: ClassVar[frozenset[str]] = frozenset({"created_at"})


class VersionMembers(CoreModel):
    """Contents of `version_claims` for one version."""

    claim_ids: list[ClaimId]
    comparison_ids: list[ComparisonId]
    conflict_ids: list[ConflictId]

    @classmethod
    def from_records(cls, records: VersionRecords) -> VersionMembers:
        return cls(
            claim_ids=sorted(c.claim_id for c in records.claims),
            comparison_ids=sorted(c.comparison_id for c in records.comparisons),
            conflict_ids=sorted(c.conflict_id for c in records.conflicts),
        )


# --------------------------------------------------------------------- operational views
BuildState = Literal[
    "queued",
    "running",
    "done",
    "failed",
    "failed_stale",
    "failed_timeout",
    "failed_resource",
]


class BuildStatus(CoreModel):
    build_id: str
    case_id: CaseId
    status: BuildState
    version: int | None = None
    heartbeat_at: UtcStr | None = None
    stage_ms: dict[str, int] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)


class EvidenceRender(CoreModel):
    """What the proof view needs. PNGs are served from cache only: a miss is 404 render-missing."""

    claim_id: ClaimId
    pointer: EvidencePointer
    render_status: Literal["cached", "missing"]
    page_png: str | None = None
    crop_png: str | None = None
    window_rows: list[dict[str, str | int | float | None]] | None = None


class RecheckResult(CoreModel):
    match: bool
    source_sha_ok: bool
    artifact_sha_ok: bool
    input_sha_ok: bool
    value_ok: bool


class IntegrityResult(CoreModel):
    ok: bool
    version: int = Field(ge=1)
    chain_ok: bool
    snapshot_ok: bool
    records_ok: bool
    failures: list[str] = Field(default_factory=list)


class SourceRef(CoreModel):
    source_id: SourceId
    sha256: Sha256
