"""The TRACE app: every contract route (stubs replaced by real services from M2 on) plus the
built frontend on the same origin. Always binds loopback."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from trace_api.contract_app import build_contract_app

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app() -> FastAPI:
    app = build_contract_app()
    # Mounted last so it never shadows API routes.
    if DIST.is_dir():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
    return app


app = create_app()


def run() -> None:
    """Entry point for `uv run trace-api`. Always binds loopback."""
    uvicorn.run(app, host="127.0.0.1", port=8000)
