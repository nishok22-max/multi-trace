"""Claim re-check (no-store, coalesced per (claim, source) for 10 s, 30 per minute)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from trace_api.deps import AuthDep, SettingsDep, StoreDep
from trace_api.http import NO_STORE
from trace_api.problems import PROBLEM_BASE, ProblemError, not_found
from trace_api.routers._common import ERRORS, Cid, ClaimPath, CsrfHeader
from trace_api.services import recheck as recheck_service
from trace_core.models.case import RecheckResult

router = APIRouter(prefix="/cases/{cid}/claims", tags=["claims"])
LIMITER = recheck_service.RateLimiter()


@router.post(
    "/{claim_id}/recheck",
    response_model=RecheckResult,
    responses={**ERRORS, 429: {"description": "rate-limited"}},
    operation_id="recheckClaim",
)
def recheck(
    cid: Cid,
    claim_id: ClaimPath,
    x_trace_csrf: CsrfHeader,
    auth: AuthDep,
    store: StoreDep,
    settings: SettingsDep,
) -> object:
    if not LIMITER.allow(f"{auth.principal.iss}:{auth.principal.sub}"):
        raise ProblemError(
            429,
            "Too Many Requests",
            type_=PROBLEM_BASE + "rate-limited",
            headers={"Retry-After": "60", "Cache-Control": NO_STORE},
            retry_after=60,
        )
    version = store.latest(cid)
    claim = (
        None
        if version is None
        else next((c for c in version.records.claims if c.claim_id == claim_id), None)
    )
    if version is None or claim is None:
        raise not_found()  # another case's id is a 404 too
    result = recheck_service.recheck(settings, version, claim)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": NO_STORE})
