"""Streaming upload caps (A-07, HARDENING S2), enforced before the body reaches the app.

`POST .../sources` is capped at 25 MB (documents) or, with `?kind=telemetry`, 200 MB. A declared
`Content-Length` above the cap is refused without reading a byte; without a length (chunked) the
bytes are counted as they stream and the request is refused once the cap is passed, so at most
`cap + SLACK` bytes are ever read (SLACK = one server chunk). The refusal is problem+json 413.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

DOCUMENT_CAP = 25 * 1024 * 1024
TELEMETRY_CAP = 200 * 1024 * 1024
SLACK = 1 << 16  # one 64 KiB server chunk
MIN_FREE_BYTES = 1024**3
_UPLOAD_PATH = re.compile(r"^(?:/api/v1)?/cases/[^/]+/sources/?$")
_BODY = json.dumps(
    {"type": "/problems/payload-too-large", "title": "Payload Too Large", "status": 413}
).encode()


class _TooLarge(Exception):
    pass


def cap_for(scope: MutableMapping[str, Any]) -> int:
    query = scope.get("query_string", b"").decode("latin-1")
    return TELEMETRY_CAP if "kind=telemetry" in query.split("&") else DOCUMENT_CAP


def ensure_free_space(
    directory: Path,
    needed: int = 0,
    *,
    minimum: int = MIN_FREE_BYTES,
    usage: Callable[[Path], Any] = shutil.disk_usage,
) -> bool:
    """False when writing `needed` bytes would leave less than `minimum` free (upload refused)."""
    return int(usage(directory).free) - needed >= minimum


class UploadCapMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not _UPLOAD_PATH.match(scope["path"])
        ):
            await self.app(scope, receive, send)
            return
        cap = cap_for(scope)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > cap:
            await self._refuse(send)
            return
        seen = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > cap:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._refuse(send)

    @staticmethod
    async def _refuse(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"cache-control", b"no-store"),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _BODY})
