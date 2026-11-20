"""Evaluation routes (evaluator role; one run in flight)."""

from __future__ import annotations

from fastapi import APIRouter

from trace_api.problems import not_implemented
from trace_api.routers._common import ERRORS, CsrfHeader
from trace_core.models.api_io import EvalRunAccepted
from trace_core.models.eval import EvalReport

router = APIRouter(prefix="/eval", tags=["eval"])


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
def get_report() -> object:
    return not_implemented()
