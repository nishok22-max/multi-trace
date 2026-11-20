"""Source routes: streaming-capped upload and hardened original download."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile

from trace_api.problems import not_implemented
from trace_api.routers._common import ERRORS, Cid, CsrfHeader, Sid
from trace_core.models.api_io import SourceUploaded

router = APIRouter(prefix="/cases/{cid}/sources", tags=["sources"])


@router.post(
    "",
    response_model=SourceUploaded,
    status_code=201,
    responses=ERRORS,
    operation_id="uploadSource",
)
def upload_source(cid: Cid, file: UploadFile, x_trace_csrf: CsrfHeader) -> object:
    """Role: ingestor. Streaming caps (25 MB documents, 200 MB telemetry) are enforced in ASGI
    middleware before the body is read; magic-byte allowlist PDF, PNG, JPEG, CSV, TXT, MD."""
    return not_implemented()


@router.get(
    "/{sid}/original",
    responses={
        **ERRORS,
        200: {"content": {"application/octet-stream": {}}, "description": "Original bytes"},
    },
    operation_id="downloadOriginal",
)
def download_original(cid: Cid, sid: Sid) -> object:
    """Served as attachment, octet-stream, nosniff, CSP sandbox, CORP same-origin."""
    return not_implemented()
