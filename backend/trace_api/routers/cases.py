"""Case routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from trace_adapters.clock import SystemClock
from trace_api.deps import (
    AuthDep,
    AuthRepoDep,
    SessionDep,
    SettingsDep,
    StoreDep,
    require_role,
)
from trace_api.http import NO_STORE
from trace_api.problems import PROBLEM_BASE, ProblemError, not_found, unauthenticated
from trace_api.routers._common import ERRORS, Cid, CsrfHeader
from trace_api.security.sessions import COOKIE
from trace_core.models.api_io import CaseCreate, CaseList
from trace_core.models.case import Case
from trace_core.normalise.time import fmt_utc

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=CaseList, responses=ERRORS, operation_id="listCases")
def list_cases(
    request: Request, settings: SettingsDep, repo: AuthRepoDep, store: StoreDep
) -> object:
    if not settings.dev_auth and repo.lookup(request.cookies.get(COOKIE)) is None:
        raise unauthenticated()
    body = CaseList(cases=store.list_cases())
    return JSONResponse(body.model_dump(mode="json"), headers={"Cache-Control": NO_STORE})


@router.post("", response_model=Case, status_code=201, responses=ERRORS, operation_id="createCase")
def create_case(
    body: CaseCreate, x_trace_csrf: CsrfHeader, auth: SessionDep, store: StoreDep
) -> object:
    """Role: ingestor."""
    require_role(auth, "ingestor")
    if store.get_case(body.case_id) is not None:
        raise ProblemError(
            409,
            "Case already exists",
            type_=PROBLEM_BASE + "append-only",
            headers={"Cache-Control": NO_STORE},
        )  # a case is append-only evidence: it is never replaced
    case = Case(
        case_id=body.case_id,
        title=body.title,
        entities=body.entities,
        window_start=body.window_start,
        window_end=body.window_end,
        plant_tz=body.plant_tz,
        created_at=fmt_utc(SystemClock().now_utc()),
    )
    store.append(case.case_id, [case])
    return JSONResponse(
        case.model_dump(mode="json"), status_code=201, headers={"Cache-Control": NO_STORE}
    )


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
