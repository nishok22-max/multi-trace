"""Source routes: streaming-capped upload and hardened original download.

The API never decodes an untrusted file: it sniffs magic bytes (security/magic.py), stores the
bytes under their hash, and records a `Source`. Reading happens later, in the build child.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from trace_adapters.blob_fs import FsBlobStore
from trace_adapters.clock import SystemClock
from trace_api.deps import AuthDep, SettingsDep, StoreDep, require_role
from trace_api.http import NO_STORE
from trace_api.problems import PROBLEM_BASE, ProblemError, not_found
from trace_api.routers._common import ERRORS, Cid, CsrfHeader, Sid
from trace_api.security.headers import original_download_headers
from trace_api.security.magic import Detected, UnsupportedMedia, classify
from trace_api.security.upload_asgi import (
    DOCUMENT_CAP,
    TELEMETRY_CAP,
    ensure_free_space,
)
from trace_core.errors import PayloadTooLarge
from trace_core.models.api_io import SourceUploaded
from trace_core.models.records import Source
from trace_core.normalise.time import fmt_utc

router = APIRouter(prefix="/cases/{cid}/sources", tags=["sources"])

SNIFF_BYTES = 1 << 16


def _modality(detected: Detected, kind: str) -> str:
    if detected.kind in ("png", "jpeg"):
        return "image"
    if detected.kind == "csv":
        return "sensor" if kind == "telemetry" else "table"
    return "text"


def _problem(status: int, title: str, type_: str) -> ProblemError:
    return ProblemError(
        status, title, type_=PROBLEM_BASE + type_, headers={"Cache-Control": NO_STORE}
    )


@router.post(
    "",
    response_model=SourceUploaded,
    status_code=201,
    responses=ERRORS,
    operation_id="uploadSource",
)
def upload_source(
    cid: Cid,
    file: UploadFile,
    x_trace_csrf: CsrfHeader,
    request: Request,
    auth: AuthDep,
    settings: SettingsDep,
    store: StoreDep,
) -> object:
    """Role: ingestor. Streaming caps (25 MB documents, 200 MB telemetry) are enforced in ASGI
    middleware before the body is read; magic-byte allowlist PDF, PNG, JPEG, CSV, TXT, MD."""
    require_role(auth, "ingestor")
    # `?kind=telemetry` is read here (not declared) so the frozen contract stays unchanged.
    kind = "telemetry" if request.query_params.get("kind") == "telemetry" else "document"
    cap = TELEMETRY_CAP if kind == "telemetry" else DOCUMENT_CAP
    if not ensure_free_space(settings.data_dir, cap):
        raise ProblemError(
            507, "Insufficient Storage", headers={"Cache-Control": NO_STORE}
        )  # less than 1 GiB would remain
    head = file.file.read(SNIFF_BYTES)
    file.file.seek(0)
    try:
        detected = classify(file.filename or "", head)
    except UnsupportedMedia:
        raise _problem(415, "Unsupported Media Type", "unsupported-media") from None
    try:
        ref = FsBlobStore(settings.blobs_dir).put(file.file, max_bytes=cap)
    except PayloadTooLarge:
        raise _problem(413, "Payload Too Large", "payload-too-large") from None
    modality = _modality(detected, kind)
    origin = "upload:" + detected.display_name
    # same bytes under another name or role are another Source (the table is append-only)
    identity = hashlib.sha256(f"{ref.sha256}|{modality}|{origin}".encode()).hexdigest()
    source_id = "src-" + identity[:12]
    store.append(
        cid,
        [
            Source(
                source_id=source_id,
                case_id=cid,
                modality=modality,  # type: ignore[arg-type]
                sha256=ref.sha256,
                origin=origin,
                ingested_at=fmt_utc(SystemClock().now_utc()),
                synthetic=False,
                mime=detected.mime,
                size=ref.size,
            )
        ],
    )
    return JSONResponse(
        SourceUploaded(source_id=source_id, sha256=ref.sha256).model_dump(mode="json"),
        status_code=201,
        headers={"Cache-Control": NO_STORE},
    )


@router.get(
    "/{sid}/original",
    responses={
        **ERRORS,
        200: {"content": {"application/octet-stream": {}}, "description": "Original bytes"},
    },
    operation_id="downloadOriginal",
)
def download_original(
    cid: Cid, sid: Sid, auth: AuthDep, settings: SettingsDep, store: StoreDep
) -> object:
    """Served as attachment, octet-stream, nosniff, CSP sandbox, CORP same-origin."""
    manifest = store.load_manifest(cid)
    source = next((s for s in (manifest.sources if manifest else []) if s.source_id == sid), None)
    if source is None or source.held_reason is not None:
        raise not_found()  # another case's source id is a 404, not a leak
    blobs = FsBlobStore(settings.blobs_dir)
    if not blobs.exists(source.sha256):
        raise not_found()
    path = settings.blobs_dir / source.sha256[:2] / source.sha256
    name = source.origin.removeprefix("upload:").rsplit("/", 1)[-1]
    return FileResponse(path, headers=original_download_headers(name))
