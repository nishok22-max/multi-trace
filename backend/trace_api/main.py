"""Minimal M0 app: /healthz plus the built frontend served on the same origin."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

app = FastAPI(title="TRACE", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# Mounted last so it never shadows API routes.
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")


def run() -> None:
    """Entry point for `uv run trace-api`. Always binds loopback."""
    uvicorn.run(app, host="127.0.0.1", port=8000)
