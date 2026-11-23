"""Health probes (not versioned): /healthz and /readyz."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from trace_api.deps import SettingsDep
from trace_api.routers._common import ERRORS
from trace_api.security.upload_asgi import ensure_free_space
from trace_core.models.api_io import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, operation_id="healthz")
def healthz() -> HealthResponse:
    """Liveness. Always 200 while the process is up."""
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadyResponse, responses=ERRORS, operation_id="readyz")
def readyz(settings: SettingsDep) -> object:
    """Readiness: DB writable, blob dir writable, Tesseract present, free disk > 1 GB."""
    body = ReadyResponse(
        db_writable=_writable(settings.data_dir),
        blobs_writable=_writable(settings.blobs_dir),
        # reported honestly; the P0 build reads images through a fake OCR, so a missing binary
        # does not make the service unready until the Tesseract adapter is wired (P1-10)
        tesseract_present=shutil.which("tesseract") is not None,
        disk_ok=ensure_free_space(settings.data_dir),
    )
    ready = body.db_writable and body.blobs_writable and body.disk_ok
    return JSONResponse(
        body.model_dump(mode="json"),
        status_code=200 if ready else 503,
        headers={"Cache-Control": "no-store"},
    )


def _writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory):
            return True
    except OSError:
        return False
