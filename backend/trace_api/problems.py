"""RFC 9457 problem+json helpers. Stable `type`s; bodies never carry exception text."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from trace_core.models.api_io import Problem

PROBLEM_BASE = "/problems/"
PROBLEM_TYPES = (
    "evidence-changed",
    "already-decided",
    "build-in-progress",
    "unknown-unit",
    "quote-not-verified",
    "unsupported-media",
    "payload-too-large",
    "append-only",
    "log-coverage",
    "render-missing",
    "replay-cache-miss",
    "pdf-page-cap",
    "rate-limited",
    "not-implemented",
)


def problem_response(problem: Problem, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        problem.model_dump(mode="json", exclude_none=True),
        status_code=problem.status,
        media_type="application/problem+json",
        headers=headers,
    )


def not_implemented() -> JSONResponse:
    """Contract stubs return this until the real service lands (M2+)."""
    return problem_response(
        Problem(type=PROBLEM_BASE + "not-implemented", title="Not implemented", status=501)
    )
