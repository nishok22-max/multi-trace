"""API request/response bodies (IMPLEMENTATION_PLAN C.4, PRD 13).

Wire models are frozen and forbid extra fields. A `reviewer` field on a decision therefore
fails validation (422): identity comes only from the session (promise 9).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from trace_core.models.base import (
    CaseId,
    ClaimId,
    DecisionId,
    EntityId,
    Sha256,
    SourceId,
    WireModel,
)
from trace_core.models.case import Case, CaseVersion
from trace_core.models.claims import ClaimRecord
from trace_core.models.evidence import Role
from trace_core.models.records import (
    Choice,
    ComparisonRecord,
    ConflictRecord,
    EntityChoice,
    EscalateChoice,
    ExplainChoice,
    ReadingChoice,
    ReviewType,
)
from trace_core.models.time import UtcStr


class DecisionRequest(WireModel):
    choice: Choice
    reason: str = Field(min_length=15)
    base_version: int = Field(ge=0)
    shown_evidence_hash: Sha256
    supersedes: DecisionId | None = None


# Which choice kinds are valid per review type (validated against the item at the API layer).
_ENTITY_TYPES: frozenset[ReviewType] = frozenset({"ambiguous_entity"})
_EXPLAIN_TYPES: frozenset[ReviewType] = frozenset({"conflict_explain"})


def choice_allowed(review_type: ReviewType, choice: Choice) -> bool:
    """Fail closed: EscalateChoice is allowed on any item; others only on their item type."""
    if isinstance(choice, EscalateChoice):
        return True
    if isinstance(choice, EntityChoice):
        return review_type in _ENTITY_TYPES
    if isinstance(choice, ExplainChoice):
        return review_type in _EXPLAIN_TYPES
    if isinstance(choice, ReadingChoice):
        return review_type not in _ENTITY_TYPES and review_type not in _EXPLAIN_TYPES
    return False


class DecisionResponse(WireModel):
    decision_id: DecisionId
    version: int
    manifest_hash: Sha256


class Problem(WireModel):
    """RFC 9457 problem+json. Bodies never carry exception text."""

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    retry_after: int | None = None
    existing_decision_id: DecisionId | None = None


class LoginRequest(WireModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class MeResponse(WireModel):
    user_id: str
    display_name: str
    role: Role


class CaseCreate(WireModel):
    case_id: CaseId
    title: str
    entities: list[EntityId]
    window_start: UtcStr
    window_end: UtcStr
    plant_tz: str


class CaseList(WireModel):
    cases: list[Case]


class SourceUploaded(WireModel):
    source_id: SourceId
    sha256: Sha256


class BuildAccepted(WireModel):
    build_id: str


class ClaimsPage(WireModel):
    items: list[ClaimRecord]
    offset: int
    limit: int
    total: int


class ComparisonsPage(WireModel):
    items: list[ComparisonRecord]


class ConflictsPage(WireModel):
    items: list[ConflictRecord]


class ClaimDetail(WireModel):
    claim: ClaimRecord
    parents: list[ClaimId]
    children: list[ClaimId]


class ReplayResult(WireModel):
    match: bool
    expected_manifest_hash: Sha256
    actual_manifest_hash: Sha256


class EvalRunAccepted(WireModel):
    run_id: str


class VersionManifest(WireModel):
    version: CaseVersion
    manifest_hash: Sha256
    kind: Literal["manifest"] = "manifest"


class HealthResponse(WireModel):
    status: Literal["ok"]


class ReadyResponse(WireModel):
    """Readiness probe: every flag must be true for 200."""

    db_writable: bool
    blobs_writable: bool
    tesseract_present: bool
    disk_ok: bool
