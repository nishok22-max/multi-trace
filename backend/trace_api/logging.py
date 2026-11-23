"""Structured logging with a scrubber that cannot be turned off (A-10, S10).

Never logged: document text, quotes, OCR text, prompts, completions, cookies, passwords, tokens,
API keys, request bodies, or exception *messages* (they can carry document content). The scrubber
is a structlog processor, so every log line passes through it; sensitive keys are redacted by
name and secret-shaped strings are redacted by value wherever they appear.
"""

from __future__ import annotations

import re
import sys
from collections.abc import MutableMapping
from typing import Any, TextIO

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REDACTED = "[redacted]"
_SENSITIVE_KEYS = (
    "password", "passwd", "secret", "token", "cookie", "authorization", "api_key", "apikey",
    "quote", "text", "prompt", "completion", "ocr", "body", "content", "document", "csrf",
    "session",
)  # fmt: skip
_SECRET_VALUE = re.compile(
    r"(gsk_[A-Za-z0-9_\-]{6,}|sk-[A-Za-z0-9_\-]{8,}|Bearer\s+\S+|trace_session=[^;\s]+)"
)


def _sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEYS)


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET_VALUE.sub(REDACTED, value)
    if isinstance(value, dict):
        return {k: REDACTED if _sensitive(str(k)) else _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def scrub(_logger: Any, _method: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """structlog processor. The event name is a constant phrase chosen by the code; every other
    field is redacted by key name or by secret-shaped value."""
    out: dict[str, Any] = {}
    for key, value in event.items():
        if key == "exc_info" and value:
            exc = value[1] if isinstance(value, tuple) else value
            name = type(exc).__name__ if isinstance(exc, BaseException) else "error"
            out["exception_type"] = name  # the type only: the message may hold document text
        elif key == "exception":
            continue
        elif key != "event" and _sensitive(key):
            out[key] = REDACTED
        else:
            out[key] = _clean(value)
    return out


def configure_logging(stream: TextIO | None = None) -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            scrub,  # always before rendering, so nothing reaches a sink unscrubbed
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.WriteLoggerFactory(file=stream or sys.stderr),
        cache_logger_on_first_use=False,
    )


class AccessLogMiddleware:
    """One line per request: method, route path and status. Never headers, query or bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 500

        async def wrapped(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            structlog.get_logger("access").info(
                "request", method=scope["method"], path=scope["path"], status=status
            )
