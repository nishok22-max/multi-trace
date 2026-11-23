"""Versioned, frozen reads. Cache-Control: private, max-age=31536000, immutable;
ETag = manifest_hash; Vary: Cookie."""

from __future__ import annotations

import hashlib
import multiprocessing
import queue
import threading
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from trace_adapters.blob_fs import FsBlobStore
from trace_adapters.clock import SystemClock
from trace_adapters.config_loader import load_config_bundle
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_api.deps import AuthDep, SettingsDep, StoreDep, require_role
from trace_api.http import IMMUTABLE, NO_STORE, versioned
from trace_api.problems import PROBLEM_BASE, ProblemError, not_found
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
from trace_api.services import evidence_render
from trace_api.settings import Settings
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
    CaseVersion,
    EvidenceRender,
    IntegrityResult,
    ReviewQueueEntry,
    Story,
    TimelineEntry,
)
from trace_core.models.claims import Modality
from trace_core.models.records import Envelope
from trace_core.review.status import derive_review_status
from trace_core.snapshot.integrity import verify_chain
from trace_worker.build_runner import BuildPaths
from trace_worker.child_guard import kill_tree
from trace_worker.replay import replay_target

router = APIRouter(prefix="/cases/{cid}/versions/{v}", tags=["versions"])


def _load(store: StoreDep, cid: str, v: int) -> CaseVersion:
    version = store.get_version(cid, v)
    if version is None:
        raise not_found()
    return version


PNG = {
    **ERRORS,
    200: {"content": {"image/png": {}}, "description": "Cached PNG"},
    404: {"description": "render-missing: only pre-rendered pages and crops are served"},
}


_REPLAY_LOCK = threading.Lock()


def _png(
    cid: str,
    v: int,
    claim_id: str,
    which: str,
    request: Request,
    store: SqliteClaimStore,
    settings: Settings,
) -> object:
    version = _load(store, cid, v)
    claim = next((c for c in version.records.claims if c.claim_id == claim_id), None)
    if claim is None:
        raise not_found()
    path = evidence_render.artifact_path(settings, claim, which)
    if path is None:  # only pre-rendered pages and crops are served: never render here
        raise ProblemError(
            404,
            "Render missing",
            type_=PROBLEM_BASE + "render-missing",
            headers={"Cache-Control": NO_STORE},
        )
    etag = f'"{version.manifest_hash}-{path.stem}"'
    headers = {"Cache-Control": IMMUTABLE, "ETag": etag, "Vary": "Cookie"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=path.read_bytes(), media_type="image/png", headers=headers)


def run_replay(settings: Settings, cid: str, version: int) -> str:
    """Rebuild in a killable spawned child (it decodes PDFs); the API never does."""
    paths = BuildPaths(
        db=str(settings.db_path),
        blobs=str(settings.blobs_dir),
        derived=str(settings.derived_dir),
    )
    ctx = multiprocessing.get_context("spawn")
    out = ctx.Queue()
    child = ctx.Process(target=replay_target, args=(paths, cid, version, out))
    child.start()
    try:
        kind, value = out.get(timeout=settings.build_timeout_s)
    except queue.Empty:
        kind, value = "error", "timeout"
    finally:
        if child.is_alive():
            kill_tree(child.pid or 0)
        child.join(10)
    if kind != "ok":
        raise ProblemError(500, "Replay failed", headers={"Cache-Control": NO_STORE})
    return str(value)


@router.get("/state", response_model=CaseState, responses=ERRORS, operation_id="getState")
def get_state(cid: Cid, v: Version, request: Request, auth: AuthDep, store: StoreDep) -> object:
    version = _load(store, cid, v)
    return versioned(request, version, version.views.state)


@router.get("/story", response_model=Story, responses=ERRORS, operation_id="getStory")
def get_story(cid: Cid, v: Version, request: Request, auth: AuthDep, store: StoreDep) -> object:
    version = _load(store, cid, v)
    return versioned(request, version, version.views.story)


@router.get(
    "/timeline", response_model=list[TimelineEntry], responses=ERRORS, operation_id="getTimeline"
)
def get_timeline(cid: Cid, v: Version, request: Request, auth: AuthDep, store: StoreDep) -> object:
    version = _load(store, cid, v)
    return versioned(request, version, version.views.timeline)


@router.get("/claims", response_model=ClaimsPage, responses=ERRORS, operation_id="listClaims")
def list_claims(
    cid: Cid,
    v: Version,
    request: Request,
    auth: AuthDep,
    store: StoreDep,
    modality: Annotated[Modality | None, Query()] = None,
    type: Annotated[str | None, Query(pattern="^(extracted|inferred)$")] = None,  # noqa: A002
    entity: Annotated[str | None, Query(max_length=128)] = None,
    offset: Offset = 0,
    limit: Limit = 100,
) -> object:
    version = _load(store, cid, v)
    rows = [
        c
        for c in version.records.claims
        if (modality is None or c.modality == modality)
        and (type is None or c.claim_type == type)
        and (entity is None or c.subject.entity_id == entity)
    ]
    page = ClaimsPage(
        items=rows[offset : offset + limit], offset=offset, limit=limit, total=len(rows)
    )
    return versioned(request, version, page)


@router.get(
    "/comparisons",
    response_model=ComparisonsPage,
    responses=ERRORS,
    operation_id="listComparisons",
)
def list_comparisons(
    cid: Cid, v: Version, request: Request, auth: AuthDep, store: StoreDep
) -> object:
    version = _load(store, cid, v)
    return versioned(request, version, ComparisonsPage(items=version.records.comparisons))


@router.get(
    "/conflicts", response_model=ConflictsPage, responses=ERRORS, operation_id="listConflicts"
)
def list_conflicts(
    cid: Cid, v: Version, request: Request, auth: AuthDep, store: StoreDep
) -> object:
    version = _load(store, cid, v)
    return versioned(request, version, ConflictsPage(items=version.records.conflicts))


@router.get(
    "/review",
    response_model=list[ReviewQueueEntry],
    responses=ERRORS,
    operation_id="getReviewQueue",
)
def get_review(cid: Cid, v: Version, auth: AuthDep, store: StoreDep) -> object:
    # The queue with its derived status. Status depends on events and the clock, so unlike the
    # frozen reads this answer is `no-store` (status is never stored, promise 6). A comment, not
    # a docstring: docstrings are part of the frozen OpenAPI contract.
    version = _load(store, cid, v)
    events = store.review_events(cid)
    statuses = derive_review_status(
        version.records.review_items, events, SystemClock(), load_config_bundle().case.calendar
    )
    explained = {e.review_id for e in events if e.kind == "explained"}
    queue = [
        ReviewQueueEntry(item=i, status=statuses[i.review_id], explained=i.review_id in explained)
        for i in sorted(version.records.review_items, key=lambda i: i.review_id)
    ]
    return JSONResponse(
        [q.model_dump(mode="json", by_alias=True) for q in queue],
        headers={"Cache-Control": NO_STORE},
    )


@router.get(
    "/manifest", response_model=VersionManifest, responses=ERRORS, operation_id="getManifest"
)
def get_manifest(cid: Cid, v: Version, request: Request, auth: AuthDep, store: StoreDep) -> object:
    version = _load(store, cid, v)
    return versioned(
        request, version, VersionManifest(version=version, manifest_hash=version.manifest_hash)
    )


@router.get(
    "/integrity", response_model=IntegrityResult, responses=ERRORS, operation_id="getIntegrity"
)
def get_integrity(
    cid: Cid, v: Version, auth: AuthDep, store: StoreDep, settings: SettingsDep
) -> object:
    """Verifies stored bytes against stored hashes and walks the chain."""
    chain: list[CaseVersion] = []
    for n in range(1, v + 1):
        version = store.get_version(cid, n)
        if version is None:
            raise not_found()
        chain.append(version)
    blobs = FsBlobStore(settings.blobs_dir)

    def stored_sha(sha: str) -> str | None:
        if not blobs.exists(sha):
            return None
        digest = hashlib.sha256()
        with blobs.open(sha) as handle:
            while chunk := handle.read(1 << 16):
                digest.update(chunk)
        return digest.hexdigest()

    result = verify_chain(chain, stored_sha)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": NO_STORE})


@router.get(
    "/claims/{claim_id}", response_model=ClaimDetail, responses=ERRORS, operation_id="getClaim"
)
def get_claim(
    cid: Cid, v: Version, claim_id: ClaimPath, request: Request, auth: AuthDep, store: StoreDep
) -> object:
    version = _load(store, cid, v)
    claims = version.records.claims
    claim = next((c for c in claims if c.claim_id == claim_id), None)
    if claim is None:
        raise not_found()  # another version's or another case's id is a 404
    known = {c.claim_id for c in claims}
    detail = ClaimDetail(
        claim=claim,
        parents=[p for p in claim.derived_from if p in known],
        children=sorted(c.claim_id for c in claims if claim_id in c.derived_from),
    )
    return versioned(request, version, detail)


@router.get(
    "/claims/{claim_id}/evidence",
    response_model=EvidenceRender,
    responses=ERRORS,
    operation_id="getEvidence",
)
def get_evidence(
    cid: Cid,
    v: Version,
    claim_id: ClaimPath,
    request: Request,
    auth: AuthDep,
    store: StoreDep,
    settings: SettingsDep,
) -> object:
    version = _load(store, cid, v)
    claim = next((c for c in version.records.claims if c.claim_id == claim_id), None)
    if claim is None or claim.evidence is None:
        raise not_found()
    return versioned(request, version, evidence_render.render(settings, cid, version, claim))


@router.get(
    "/claims/{claim_id}/evidence/page.png", responses=PNG, operation_id="getEvidencePagePng"
)
def get_evidence_page(
    cid: Cid,
    v: Version,
    claim_id: ClaimPath,
    request: Request,
    auth: AuthDep,
    store: StoreDep,
    settings: SettingsDep,
) -> object:
    return _png(cid, v, claim_id, "page", request, store, settings)


@router.get(
    "/claims/{claim_id}/evidence/crop.png", responses=PNG, operation_id="getEvidenceCropPng"
)
def get_evidence_crop(
    cid: Cid,
    v: Version,
    claim_id: ClaimPath,
    request: Request,
    auth: AuthDep,
    store: StoreDep,
    settings: SettingsDep,
) -> object:
    return _png(cid, v, claim_id, "crop", request, store, settings)


@router.get(
    "/entities/{eid}/envelope",
    response_model=Envelope,
    responses=ERRORS,
    operation_id="getEnvelope",
)
def get_envelope(
    cid: Cid, v: Version, eid: Eid, request: Request, auth: AuthDep, store: StoreDep
) -> object:
    version = _load(store, cid, v)
    envelope = next((e for e in version.records.envelopes if e.machine == eid), None)
    if envelope is None:
        raise not_found()
    return versioned(request, version, envelope)


@router.post("/replay", response_model=ReplayResult, responses=ERRORS, operation_id="replayVersion")
def replay(
    cid: Cid,
    v: Version,
    x_trace_csrf: CsrfHeader,
    auth: AuthDep,
    store: StoreDep,
    settings: SettingsDep,
) -> object:
    """Role: evaluator. DB single-flight. Cache-Control: no-store."""
    require_role(auth, "evaluator")
    version = _load(store, cid, v)
    if not _REPLAY_LOCK.acquire(blocking=False):
        raise ProblemError(
            409,
            "Replay in progress",
            type_=PROBLEM_BASE + "build-in-progress",
            headers={"Retry-After": "5", "Cache-Control": NO_STORE},
            retry_after=5,
        )
    try:
        actual = run_replay(settings, cid, v)
    finally:
        _REPLAY_LOCK.release()
    result = ReplayResult(
        match=actual == version.manifest_hash,
        expected_manifest_hash=version.manifest_hash,
        actual_manifest_hash=actual,
    )
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": NO_STORE})
