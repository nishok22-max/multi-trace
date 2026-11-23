"""CSRF defence for writes (A-09, S1): every write needs the `X-TRACE-CSRF` header and a JSON
body (login included). A cross-site form cannot set the header or send `application/json`
without a CORS preflight, which this server never grants. The one multipart exception is the
source upload route, which still needs the header.
"""

from __future__ import annotations

import re

from starlette.types import ASGIApp, Receive, Scope, Send

from trace_api.security.origin import UNSAFE, problem

HEADER = b"x-trace-csrf"
_UPLOAD = re.compile(r"^(?:/api/v1)?/cases/[^/]+/sources/?$")


class CsrfMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE:
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        if not headers.get(HEADER):
            await problem(send, 403, "Forbidden")
            return
        content_type = headers.get(b"content-type", b"").decode("latin-1").split(";")[0].strip()
        has_body = headers.get(b"content-length", b"0") != b"0" or b"transfer-encoding" in headers
        multipart_ok = bool(_UPLOAD.match(scope["path"])) and content_type == "multipart/form-data"
        if has_body and content_type != "application/json" and not multipart_ok:
            await problem(send, 415, "Unsupported Media Type", "/problems/unsupported-media")
            return
        await self.app(scope, receive, send)
