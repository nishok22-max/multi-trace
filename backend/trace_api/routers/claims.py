"""Claim re-check (no-store, coalesced per (claim, source) for 10 s, 30 per minute)."""

from __future__ import annotations

from fastapi import APIRouter

from trace_api.problems import not_implemented
from trace_api.routers._common import ERRORS, Cid, ClaimPath, CsrfHeader
from trace_core.models.case import RecheckResult

router = APIRouter(prefix="/cases/{cid}/claims", tags=["claims"])


@router.post(
    "/{claim_id}/recheck",
    response_model=RecheckResult,
    responses={**ERRORS, 429: {"description": "rate-limited"}},
    operation_id="recheckClaim",
)
def recheck(cid: Cid, claim_id: ClaimPath, x_trace_csrf: CsrfHeader) -> object:
    return not_implemented()
