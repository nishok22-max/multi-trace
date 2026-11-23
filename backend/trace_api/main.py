"""The TRACE app: every contract route (stubs replaced by real services from M2 on) plus the
built frontend on the same origin. Always binds loopback unless TLS is configured."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from trace_api.contract_app import build_contract_app
from trace_api.logging import AccessLogMiddleware, configure_logging
from trace_api.security.csp import load_csp
from trace_api.security.csrf import CsrfMiddleware
from trace_api.security.headers import SecurityHeadersMiddleware
from trace_api.security.origin import LOOPBACK_HOSTS, HostOriginMiddleware
from trace_api.security.upload_asgi import UploadCapMiddleware
from trace_api.settings import assert_safe_bind

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(allowed_hosts: frozenset[str] = LOOPBACK_HOSTS, dist: Path = DIST) -> FastAPI:
    app = build_contract_app()
    # Mounted last so it never shadows API routes.
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    # Added innermost first: CSRF, upload caps, host/origin, then headers on every response.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(UploadCapMiddleware)
    app.add_middleware(HostOriginMiddleware, allowed_hosts=allowed_hosts)
    app.add_middleware(SecurityHeadersMiddleware, csp=load_csp(dist))
    app.add_middleware(AccessLogMiddleware)
    return app


configure_logging()
app = create_app()


def run() -> None:
    """Entry point for `uv run trace-api`. LAN binding needs TLS (TRACE_TLS_CERT/KEY)."""
    host = os.environ.get("TRACE_HOST", "127.0.0.1")
    cert, key = os.environ.get("TRACE_TLS_CERT"), os.environ.get("TRACE_TLS_KEY")
    assert_safe_bind(host, bool(cert and key))
    uvicorn.run(app, host=host, port=8000, ssl_certfile=cert, ssl_keyfile=key)
