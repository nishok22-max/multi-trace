"""Build routes. One build in flight per case; idempotent by build_key."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from trace_adapters.sqlite.builds import BuildInProgress, BuildRepository
from trace_api.deps import AuthDep, BuildServiceDep, SettingsDep, require_role
from trace_api.http import NO_STORE
from trace_api.problems import PROBLEM_BASE, ProblemError, not_found
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
def start_build(
    cid: Cid, x_trace_csrf: CsrfHeader, auth: AuthDep, service: BuildServiceDep
) -> object:
    """Role: ingestor. Runs in a killable child process."""
    require_role(auth, "ingestor")
    try:
        status = service.start(cid)
    except BuildInProgress:
        raise ProblemError(
            409,
            "Build in progress",
            type_=PROBLEM_BASE + "build-in-progress",
            headers={"Retry-After": "5", "Cache-Control": NO_STORE},
            retry_after=5,
        ) from None
    except LookupError:
        raise not_found() from None
    return JSONResponse(
        BuildAccepted(build_id=status.build_id).model_dump(),
        status_code=202,
        headers={"Cache-Control": NO_STORE},
    )


@router.get("/builds/{bid}", response_model=BuildStatus, responses=ERRORS, operation_id="getBuild")
def get_build(cid: Cid, bid: Bid, auth: AuthDep, settings: SettingsDep) -> object:
    status = BuildRepository(settings.db_path).get(bid)
    if status is None or status.case_id != cid:
        raise not_found()  # another case's build id is a 404, not a leak
    return JSONResponse(status.model_dump(mode="json"), headers={"Cache-Control": NO_STORE})
