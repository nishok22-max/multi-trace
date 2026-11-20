"""ClaimRecord and its parts (PRD 9.3, IMPLEMENTATION_PLAN C.1).

Claims carry NO version and NO status (promise 6): membership lives in `version_claims`,
review status is derived from `review_events`.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from trace_core.models.base import CaseId, ClaimId, CoreModel, EntityId, Sha256
from trace_core.models.evidence import EvidencePointer
from trace_core.models.time import Temporal, UtcStr

JsonScalar = str | int | float | bool | None
ClaimValue = JsonScalar | dict[str, JsonScalar]

ClaimType = Literal["extracted", "inferred"]
Modality = Literal["text", "table", "image", "sensor", "decision"]
ValueType = Literal["categorical", "numeric", "text", "boolean", "structured"]
UnitStatus = Literal["known", "unknown", "sensor_native", "not_applicable"]
LinkStatus = Literal["resolved", "ambiguous", "unresolved"]


class MentionKey(CoreModel):
    """Stable key `(source_sha256, locator)` that decisions attach to."""

    source_sha256: Sha256
    locator: str


class Candidate(CoreModel):
    entity_id: EntityId
    score: float
    features: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    vetoed: bool = False


class Subject(CoreModel):
    mention: str | None = None
    entity_id: EntityId | None = None
    link_status: LinkStatus
    candidates: list[Candidate] = Field(default_factory=list)
    mention_key: MentionKey | None = None


class Method(CoreModel):
    extractor: str
    extractor_version: str
    rule_id: str | None = None
    llm_used: bool = False
    model_id: str | None = None


class Confidence(CoreModel):
    value: float = Field(ge=0.0, le=1.0)
    calibrated: bool = False
    components: dict[str, float] = Field(default_factory=dict)
    stage: Literal["pre", "final"] = "pre"
    calibration_fit_id: str | None = None
    note: str | None = None


class ClaimRecord(CoreModel):
    claim_id: ClaimId
    label: str | None = None
    case_id: CaseId
    claim_type: ClaimType
    statement: str
    subject: Subject
    attribute: str
    value: ClaimValue
    value_type: ValueType
    unit: str | None = None
    unit_status: UnitStatus
    normalized_value: ClaimValue = None
    normalized_unit: str | None = None
    temporal: Temporal
    modality: Modality
    evidence: EvidencePointer | None = None
    derived_from: list[str] = Field(default_factory=list)
    method: Method
    confidence: Confidence
    supersedes: ClaimId | None = None
    record_hash: Sha256
    created_at: UtcStr | None = None

    wall_clock_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "record_hash"})

    @model_validator(mode="after")
    def _rules(self) -> ClaimRecord:
        if self.claim_type == "inferred":
            if not self.derived_from:
                raise ValueError("inferred claim requires non-empty derived_from")
            if not self.method.rule_id:
                raise ValueError("inferred claim requires method.rule_id")
        if self.claim_type == "extracted" and self.evidence is None:
            raise ValueError("extracted claim requires evidence")
        if self.unit_status == "sensor_native" and (
            self.normalized_value is not None or self.normalized_unit is not None
        ):
            raise ValueError("sensor_native units are never converted (promise 5)")
        return self
