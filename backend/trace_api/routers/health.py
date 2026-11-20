"""Health probes (not versioned): /healthz and /readyz."""

from __future__ import annotations

from fastapi import APIRouter

from trace_api.problems import not_implemented
from trace_api.routers._common import ERRORS
from trace_core.models.api_io import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, operation_id="healthz")
def healthz() -> HealthResponse:
    """Liveness. Always 200 while the process is up."""
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadyResponse, responses=ERRORS, operation_id="readyz")
def readyz() -> object:
    """Readiness: DB writable, blob dir writable, Tesseract present, free disk > 1 GB."""
    return not_implemented()
