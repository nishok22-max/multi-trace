"""Evaluation routes (evaluator role; one run in flight)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from trace_adapters.sqlite.eval_runs import EvalInProgress, EvalRunRepository
from trace_api.deps import AuthRepoDep, SettingsDep, StoreDep
from trace_api.http import NO_STORE
from trace_api.problems import PROBLEM_BASE, ProblemError, not_found, unauthenticated
from trace_api.routers._common import ERRORS, CsrfHeader
from trace_api.security.sessions import COOKIE
from trace_api.services.eval_service import EvalService
from trace_core.models.api_io import EvalRunAccepted
from trace_core.models.eval import EvalReport
from trace_worker.env import engine_sha

router = APIRouter(prefix="/eval", tags=["eval"])


def _evaluator(request: Request, settings: SettingsDep, repo: AuthRepoDep) -> str:
    """Signed in AND an evaluator (the route matrix: others get 403)."""
    if settings.dev_auth:
        return "dev"
    user = repo.lookup(request.cookies.get(COOKIE))
    if user is None:
        raise unauthenticated()
    if user.role != "evaluator":
        raise ProblemError(403, "Forbidden", headers={"Cache-Control": NO_STORE})
    return user.user_id


EvaluatorDep = Annotated[str, Depends(_evaluator)]


@router.post(
    "/run",
    response_model=EvalRunAccepted,
    status_code=202,
    responses=ERRORS,
    operation_id="runEval",
)
def run_eval(
    x_trace_csrf: CsrfHeader, auth: EvaluatorDep, settings: SettingsDep, store: StoreDep
) -> object:
    # `store` makes sure the migrations (incl. eval_runs) are applied before the first use.
    service = EvalService(settings, EvalRunRepository(settings.db_path))
    try:
        run_id = service.start()
    except EvalInProgress:
        raise ProblemError(
            409,
            "Evaluation already running",
            type_=PROBLEM_BASE + "build-in-progress",
            headers={"Retry-After": "5", "Cache-Control": NO_STORE},
            retry_after=5,
        ) from None
    return JSONResponse(
        EvalRunAccepted(run_id=run_id).model_dump(),
        status_code=202,
        headers={"Cache-Control": NO_STORE},
    )


@router.get("/report", response_model=EvalReport, responses=ERRORS, operation_id="getEvalReport")
def get_report(auth: EvaluatorDep, settings: SettingsDep) -> object:
    # The report is written by an evaluation run (API or `make eval-dev`); this only shows it.
    # the holdout report, once it exists, is THE report; a later dev run never replaces it
    holdout = settings.data_dir / "eval_report_holdout.json"
    path = holdout if holdout.is_file() else settings.data_dir / "eval_report.json"
    if not path.is_file():
        raise not_found()  # no evaluation has been run yet
    report = EvalReport.model_validate_json(path.read_bytes())
    # a report made by another engine than the one running now says so (T-31), as a header: the
    # frozen report model has no field for it
    stale = "true" if report.engine_sha != engine_sha() else "false"
    return JSONResponse(
        report.model_dump(mode="json"),
        headers={"Cache-Control": NO_STORE, "X-Report-Superseded": stale},
    )
