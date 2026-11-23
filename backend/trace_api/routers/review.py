"""Decision route. The reviewer identity comes from the session; a `reviewer` field is 422."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from trace_adapters.clock import SystemClock
from trace_adapters.sqlite.builds import BuildRepository
from trace_api.deps import AuthDep, SettingsDep, StoreDep, require_role
from trace_api.routers._common import ERRORS, Cid, CsrfHeader, Rid
from trace_api.services import decision_service
from trace_core.models.api_io import DecisionRequest, DecisionResponse

router = APIRouter(prefix="/cases/{cid}/review", tags=["review"])

DECISION_ERRORS = {
    **ERRORS,
    409: {"description": "already-decided | evidence-changed | build-in-progress"},
}


@router.post(
    "/{rid}/decision",
    response_model=DecisionResponse,
    status_code=201,
    responses=DECISION_ERRORS,
    operation_id="decide",
)
def decide(
    cid: Cid,
    rid: Rid,
    body: DecisionRequest,
    x_trace_csrf: CsrfHeader,
    auth: AuthDep,
    store: StoreDep,
    settings: SettingsDep,
) -> object:
    """Role: reviewer (senior_reviewer to supersede). Covers conflict_explain and escalate."""
    require_role(auth, "reviewer", "senior_reviewer")
    if body.supersedes is not None:
        require_role(auth, "senior_reviewer")
    result = decision_service.decide(
        store, BuildRepository(settings.db_path), SystemClock(), auth, cid, rid, body
    )
    return JSONResponse(
        result.model_dump(mode="json"), status_code=201, headers={"Cache-Control": "no-store"}
    )
