"""Decision route. The reviewer identity comes from the session; a `reviewer` field is 422."""

from __future__ import annotations

from fastapi import APIRouter

from trace_api.problems import not_implemented
from trace_api.routers._common import ERRORS, Cid, CsrfHeader, Rid
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
def decide(cid: Cid, rid: Rid, body: DecisionRequest, x_trace_csrf: CsrfHeader) -> object:
    """Role: reviewer (senior_reviewer to supersede). Covers conflict_explain and escalate."""
    return not_implemented()
