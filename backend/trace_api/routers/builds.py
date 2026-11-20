"""Build routes. One build in flight per case; idempotent by build_key."""

from __future__ import annotations

from fastapi import APIRouter

from trace_api.problems import not_implemented
from trace_api.routers._common import ERRORS, Bid, Cid, CsrfHeader
from trace_core.models.api_io import BuildAccepted
from trace_core.models.case import BuildStatus

router = APIRouter(prefix="/cases/{cid}", tags=["builds"])

BUILD_ERRORS = {
    **ERRORS,
    409: {"description": "build-in-progress (Retry-After: 5)"},
}


@router.post(
    "/build",
    response_model=BuildAccepted,
    status_code=202,
    responses=BUILD_ERRORS,
    operation_id="startBuild",
)
def start_build(cid: Cid, x_trace_csrf: CsrfHeader) -> object:
    """Role: ingestor. Runs in a killable child process."""
    return not_implemented()


@router.get("/builds/{bid}", response_model=BuildStatus, responses=ERRORS, operation_id="getBuild")
def get_build(cid: Cid, bid: Bid) -> object:
    return not_implemented()
