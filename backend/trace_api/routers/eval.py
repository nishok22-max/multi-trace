"""Evaluation routes (evaluator role; one run in flight)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from trace_api.deps import AuthRepoDep, SettingsDep
from trace_api.problems import not_found, not_implemented, unauthenticated
from trace_api.routers._common import ERRORS, CsrfHeader
from trace_api.security.sessions import COOKIE
from trace_core.models.api_io import EvalRunAccepted
from trace_core.models.eval import EvalReport

router = APIRouter(prefix="/eval", tags=["eval"])


def _signed_in(request: Request, settings: SettingsDep, repo: AuthRepoDep) -> str:
    if settings.dev_auth:
        return "dev"
    user = repo.lookup(request.cookies.get(COOKIE))
    if user is None:
        raise unauthenticated()
    return user.user_id


EvalAuthDep = Annotated[str, Depends(_signed_in)]


@router.post(
    "/run",
    response_model=EvalRunAccepted,
    status_code=202,
    responses=ERRORS,
    operation_id="runEval",
)
def run_eval(x_trace_csrf: CsrfHeader) -> object:
    return not_implemented()


@router.get("/report", response_model=EvalReport, responses=ERRORS, operation_id="getEvalReport")
def get_report(auth: EvalAuthDep, settings: SettingsDep) -> object:
    # The report is written by `make eval-dev` / `make eval-holdout`; the API only shows it.
    path = settings.data_dir / "eval_report.json"
    if not path.is_file():
        raise not_found()  # no evaluation has been run yet
    report = EvalReport.model_validate_json(path.read_bytes())
    return JSONResponse(report.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
