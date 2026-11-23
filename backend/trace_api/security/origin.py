"""Host and Origin checks (A-09, S1): loopback binding is not enough against DNS rebinding.

- A request whose `Host` is not on the allowlist is 400 (foreign host header).
- A write whose `Origin` names another host than `Host` is 403 (cross-origin form post).
Both answer problem+json and never run the app.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def host_only(host: str) -> str:
    """`host:port` -> `host` (IPv6 literals keep their brackets)."""
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


async def problem(send: Send, status: int, title: str, type_: str = "about:blank") -> None:
    body = json.dumps({"type": type_, "title": title, "status": status}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class HostOriginMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: frozenset[str] = LOOPBACK_HOSTS) -> None:
        self.app = app
        self.allowed = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        if host_only(host) not in self.allowed:
            await problem(send, 400, "Bad Request")
            return
        origin = headers.get("origin")
        if scope["method"] in UNSAFE and origin is not None:
            if origin == "null" or urlsplit(origin).netloc != host:
                await problem(send, 403, "Forbidden")
                return
        await self.app(scope, receive, send)
