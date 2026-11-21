"""Response helpers: versioned reads are immutable, `latest` and writes are no-store."""

from __future__ import annotations

from fastapi import Request, Response
from pydantic_core import to_json

from trace_core.models.case import CaseVersion

IMMUTABLE = "private, max-age=31536000, immutable"
NO_STORE = "no-store"


def versioned(request: Request, version: CaseVersion, payload: object) -> Response:
    """JSON body with ETag = manifest_hash. Never `public`: responses are authenticated."""
    etag = f'"{version.manifest_hash}"'
    headers = {"Cache-Control": IMMUTABLE, "ETag": etag, "Vary": "Cookie"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(
        content=to_json(payload, by_alias=True),
        media_type="application/json",
        headers=headers,
    )
