"""Security headers on every response (C-09, S7/S8).

HTML gets the strict CSP; everything gets nosniff, no-referrer and same-origin resource/opener
policies. API responses without a cache policy default to `no-store`, and `public` is never sent
(authenticated responses are never shared-cacheable).
"""

from __future__ import annotations

import re

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from trace_api.security.csp import DOWNLOAD_CSP

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def original_download_headers(display_name: str) -> dict[str, str]:
    """Uploaded originals are served as an attachment, never rendered by the browser."""
    kept = "".join(ch for ch in display_name if ch.isalnum() or ch in "._-")
    safe = re.sub(r"\.{2,}", ".", kept).lstrip(".") or "original"
    return {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": f'attachment; filename="{safe}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": DOWNLOAD_CSP,
        "Cross-Origin-Resource-Policy": "same-origin",
        "Cache-Control": "private, no-store",
    }


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, csp: str) -> None:
        self.app = app
        self.csp = csp

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in BASE_HEADERS.items():
                    headers.setdefault(name, value)
                content_type = headers.get("content-type", "")
                if content_type.startswith("text/html"):
                    headers.setdefault("Content-Security-Policy", self.csp)
                cache = headers.get("cache-control")
                if cache is None:
                    headers["Cache-Control"] = "no-store"
                elif "public" in cache.lower():
                    headers["Cache-Control"] = cache.lower().replace("public", "private")
            await send(message)

        await self.app(scope, receive, wrapped)
