"""Versioned, frozen reads. Cache-Control: private, max-age=31536000, immutable;
ETag = manifest_hash; Vary: Cookie."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from trace_api.problems import not_implemented
from trace_api.routers._common import (
    ERRORS,
    Cid,
    ClaimPath,
    CsrfHeader,
    Eid,
    Limit,
    Offset,
    Version,
)
from trace_core.models.api_io import (
    ClaimDetail,
    ClaimsPage,
    ComparisonsPage,
    ConflictsPage,
    ReplayResult,
    VersionManifest,
)
from trace_core.models.case import (
    CaseState,
    EvidenceRender,
    IntegrityResult,
    ReviewQueueEntry,
    Story,
    TimelineEntry,
)
from trace_core.models.claims import Modality
from trace_core.models.records import Envelope

router = APIRouter(prefix="/cases/{cid}/versions/{v}", tags=["versions"])

PNG = {
    **ERRORS,
    200: {"content": {"image/png": {}}, "description": "Cached PNG"},
    404: {"description": "render-missing: only pre-rendered pages and crops are served"},
}


@router.get("/state", response_model=CaseState, responses=ERRORS, operation_id="getState")
def get_state(cid: Cid, v: Version) -> object:
    return not_implemented()


@router.get("/story", response_model=Story, responses=ERRORS, operation_id="getStory")
def get_story(cid: Cid, v: Version) -> object:
    return not_implemented()


@router.get(
    "/timeline", response_model=list[TimelineEntry], responses=ERRORS, operation_id="getTimeline"
)
def get_timeline(cid: Cid, v: Version) -> object:
    return not_implemented()


@router.get("/claims", response_model=ClaimsPage, responses=ERRORS, operation_id="listClaims")
def list_claims(
    cid: Cid,
    v: Version,
    modality: Annotated[Modality | None, Query()] = None,
    type: Annotated[str | None, Query(pattern="^(extracted|inferred)$")] = None,  # noqa: A002
    entity: Annotated[str | None, Query(max_length=128)] = None,
    offset: Offset = 0,
    limit: Limit = 100,
) -> object:
    return not_implemented()


@router.get(
    "/comparisons",
    response_model=ComparisonsPage,
    responses=ERRORS,
    operation_id="listComparisons",
)
def list_comparisons(cid: Cid, v: Version) -> object:
    return not_implemented()


@router.get(
    "/conflicts", response_model=ConflictsPage, responses=ERRORS, operation_id="listConflicts"
)
def list_conflicts(cid: Cid, v: Version) -> object:
    return not_implemented()


@router.get(
    "/review",
    response_model=list[ReviewQueueEntry],
    responses=ERRORS,
    operation_id="getReviewQueue",
)
def get_review(cid: Cid, v: Version) -> object:
    return not_implemented()


@router.get(
    "/manifest", response_model=VersionManifest, responses=ERRORS, operation_id="getManifest"
)
def get_manifest(cid: Cid, v: Version) -> object:
    return not_implemented()


@router.get(
    "/integrity", response_model=IntegrityResult, responses=ERRORS, operation_id="getIntegrity"
)
def get_integrity(cid: Cid, v: Version) -> object:
    """Verifies stored bytes against stored hashes and walks the chain."""
    return not_implemented()


@router.get(
    "/claims/{claim_id}", response_model=ClaimDetail, responses=ERRORS, operation_id="getClaim"
)
def get_claim(cid: Cid, v: Version, claim_id: ClaimPath) -> object:
    return not_implemented()


@router.get(
    "/claims/{claim_id}/evidence",
    response_model=EvidenceRender,
    responses=ERRORS,
    operation_id="getEvidence",
)
def get_evidence(cid: Cid, v: Version, claim_id: ClaimPath) -> object:
    return not_implemented()


@router.get(
    "/claims/{claim_id}/evidence/page.png", responses=PNG, operation_id="getEvidencePagePng"
)
def get_evidence_page(cid: Cid, v: Version, claim_id: ClaimPath) -> object:
    return not_implemented()


@router.get(
    "/claims/{claim_id}/evidence/crop.png", responses=PNG, operation_id="getEvidenceCropPng"
)
def get_evidence_crop(cid: Cid, v: Version, claim_id: ClaimPath) -> object:
    return not_implemented()


@router.get(
    "/entities/{eid}/envelope",
    response_model=Envelope,
    responses=ERRORS,
    operation_id="getEnvelope",
)
def get_envelope(cid: Cid, v: Version, eid: Eid) -> object:
    return not_implemented()


@router.post("/replay", response_model=ReplayResult, responses=ERRORS, operation_id="replayVersion")
def replay(cid: Cid, v: Version, x_trace_csrf: CsrfHeader) -> object:
    """Role: evaluator. DB single-flight. Cache-Control: no-store."""
    return not_implemented()
