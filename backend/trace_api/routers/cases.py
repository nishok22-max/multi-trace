"""Case routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from trace_api.deps import AuthDep, StoreDep
from trace_api.http import NO_STORE
from trace_api.problems import not_found, not_implemented
from trace_api.routers._common import ERRORS, Cid, CsrfHeader
from trace_core.models.api_io import CaseCreate, CaseList
from trace_core.models.case import Case

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=CaseList, responses=ERRORS, operation_id="listCases")
def list_cases() -> object:
    return not_implemented()


@router.post("", response_model=Case, status_code=201, responses=ERRORS, operation_id="createCase")
def create_case(body: CaseCreate, x_trace_csrf: CsrfHeader) -> object:
    """Role: ingestor."""
    return not_implemented()


@router.get(
    "/{cid}/latest",
    status_code=307,
    responses={**ERRORS, 307: {"description": "Redirect to the latest versioned path (no-store)"}},
    operation_id="latestVersion",
)
def latest(cid: Cid, auth: AuthDep, store: StoreDep) -> object:
    version = store.latest(cid)
    if version is None:
        raise not_found()  # a case with no build yet
    return RedirectResponse(
        f"/api/v1/cases/{cid}/versions/{version.version}/state",
        status_code=307,
        headers={"Cache-Control": NO_STORE},
    )
