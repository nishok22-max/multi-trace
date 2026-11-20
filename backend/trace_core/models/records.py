"""Evidence-table records: sources, envelopes, comparisons, conflicts, review items/events,
decisions (IMPLEMENTATION_PLAN C.1, PRD 9.5). None of these carries a mutable status."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import Field, model_validator

from trace_core.models.base import (
    CaseId,
    ClaimId,
    ComparisonId,
    ConflictId,
    CoreModel,
    DecisionId,
    EntityId,
    EnvelopeId,
    ReviewEventId,
    ReviewId,
    SeriesId,
    Sha256,
    SourceId,
)
from trace_core.models.claims import Candidate, MentionKey
from trace_core.models.config import EnvelopeConfig
from trace_core.models.evidence import Principal, Role
from trace_core.models.time import UtcStr

# ---------------------------------------------------------------------------- sources
SourceModality = Literal["text", "table", "image", "sensor"]


class CoveragePeriod(CoreModel):
    """Dates an event log is complete for (half-open, UTC)."""

    start: UtcStr
    end: UtcStr

    @model_validator(mode="after")
    def _order(self) -> CoveragePeriod:
        if not self.start < self.end:
            raise ValueError("coverage_period requires start < end")
        return self


class Reliability(CoreModel):
    """Beta prior on source reliability (PRD 9.2). Neutral prior is alpha = beta = 1."""

    alpha: float = Field(default=1.0, gt=0)
    beta: float = Field(default=1.0, gt=0)


class Source(CoreModel):
    source_id: SourceId
    case_id: CaseId
    modality: SourceModality
    sha256: Sha256
    origin: str
    ingested_at: UtcStr
    derived_from_sources: list[SourceId] = Field(default_factory=list)
    coverage_period: CoveragePeriod | None = None
    synthetic: bool
    mime: str
    size: int = Field(ge=0)
    held_reason: str | None = None
    reliability: Reliability = Field(default_factory=Reliability)

    wall_clock_fields: ClassVar[frozenset[str]] = frozenset({"ingested_at"})


# -------------------------------------------------------------------------- envelopes
class QuietDay(CoreModel):
    date: str  # plant-local YYYY-MM-DD
    reasons: list[str]
    t_d: float


class Envelope(CoreModel):
    envelope_id: EnvelopeId
    machine: EntityId
    series_id: SeriesId
    scope: list[str]  # channels
    statistic: Literal["robust_max_z"] = "robust_max_z"
    granularity: Literal["day"] = "day"
    quiet_days: list[QuietDay]
    n: int = Field(ge=0)
    med: dict[str, float]
    mad: dict[str, float]
    T_star: float
    pooled: Literal["none", "t_star_model", "model_level"]
    pool_members: list[EntityId]
    degenerate_channels: list[str]
    params: EnvelopeConfig
    partition_hashes: dict[str, Sha256]


# ------------------------------------------------------------------------ comparisons
GateCheckName = Literal[
    "same_entity",
    "same_attribute",
    "time_overlap",
    "comparable_terms",
    "data_both_sides",
    "beyond_variation",
]
Outcome = Literal["agree", "disagree", "cant_compare", "cant_tell"]


class GateCheck(CoreModel):
    n: int = Field(ge=1, le=6)
    name: GateCheckName
    passed: bool = Field(alias="pass")
    detail: str


class ComparisonRecord(CoreModel):
    comparison_id: ComparisonId
    claim_a: ClaimId
    claim_b: ClaimId
    config_hash: Sha256
    checks: list[GateCheck]
    outcome: Outcome
    reason: str

    @model_validator(mode="after")
    def _checks_ordered(self) -> ComparisonRecord:
        numbers = [c.n for c in self.checks]
        if numbers != sorted(set(numbers)):
            raise ValueError("checks must be unique and in ascending order")
        return self


class Magnitude(CoreModel):
    statistic: str
    observed: float | None = None
    threshold: float | None = None
    unit: str


class ConflictRecord(CoreModel):
    """Status is derived from review events, never stored. Values are never averaged."""

    conflict_id: ConflictId
    comparison_ids: list[ComparisonId]
    sides: list[ClaimId]
    supporting_context: list[ClaimId] = Field(default_factory=list)
    magnitude: Magnitude
    averaged: Literal[False] = False

    @model_validator(mode="after")
    def _sides(self) -> ConflictRecord:
        if len(self.sides) < 2:
            raise ValueError("a conflict has at least two sides")
        return self


# ---------------------------------------------------------------------------- review
ReviewType = Literal[
    "ambiguous_entity",
    "reader_disagreement",
    "implausible_value",
    "hidden_text",
    "envelope_drift",
    "low_confidence",
    "unknown_unit",
    "llm_only_interpretation",
    "no_text_layer",
    "unsupported_page",
    "pdf_page_cap",
    "conflict_explain",
]
ReviewKind = Literal["opened", "decided", "stale", "explained"]
ReviewStatus = Literal["open", "decided", "stale", "escalated"]
"""Derived at read time only. `escalated` is never stored."""


class ReviewItem(CoreModel):
    review_id: ReviewId
    type: ReviewType
    claim_ids: list[ClaimId]
    mention_keys: list[MentionKey]
    candidates: list[Candidate] | None = None
    evidence_hash: Sha256
    opened_at: UtcStr

    wall_clock_fields: ClassVar[frozenset[str]] = frozenset({"opened_at"})


class ReviewEvent(CoreModel):
    """Append-only. `kind` is opened|decided|stale|explained; escalated is derived."""

    event_id: ReviewEventId
    seq: int = Field(ge=0)
    review_id: ReviewId
    kind: ReviewKind
    decision_id: DecisionId | None = None
    at: UtcStr

    wall_clock_fields: ClassVar[frozenset[str]] = frozenset({"at"})

    @model_validator(mode="after")
    def _decision_link(self) -> ReviewEvent:
        if self.kind in ("decided", "explained") and self.decision_id is None:
            raise ValueError(f"'{self.kind}' event requires decision_id")
        return self


# ---------------------------------------------------------------------------- decisions
class EntityChoice(CoreModel):
    type: Literal["entity"] = "entity"
    entity_id: EntityId


class ReadingChoice(CoreModel):
    type: Literal["reading"] = "reading"
    verdict: Literal["accept", "reject"]


class ExplainChoice(CoreModel):
    type: Literal["explain"] = "explain"
    explanation: str | None = None


class EscalateChoice(CoreModel):
    type: Literal["escalate"] = "escalate"


Choice = Annotated[
    EntityChoice | ReadingChoice | ExplainChoice | EscalateChoice, Field(discriminator="type")
]


class Decision(CoreModel):
    """A stored human decision. Identity fields come from the session (promise 9)."""

    decision_id: DecisionId
    case_id: CaseId
    review_id: ReviewId
    principal: Principal
    display_name_snapshot: str
    role_snapshot: Role
    choice: Choice
    reason: str = Field(min_length=15)
    base_version: int = Field(ge=0)
    shown_evidence_hash: Sha256
    supersedes: DecisionId | None = None
    at: UtcStr

    wall_clock_fields: ClassVar[frozenset[str]] = frozenset({"at"})
