"""RFC 9457 problem+json helpers. Stable `type`s; bodies never carry exception text."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from trace_core.models.api_io import Problem

PROBLEM_BASE = "/problems/"
GENERIC = "about:blank"  # RFC 9457: no extra semantics beyond the HTTP status
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


class ProblemError(Exception):
    """Raised by dependencies and routes; rendered as problem+json by `register_handlers`."""

    def __init__(
        self,
        status: int,
        title: str,
        *,
        type_: str = GENERIC,
        headers: dict[str, str] | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(title)  # title is a constant phrase, never document text
        self.problem = Problem(type=type_, title=title, status=status, retry_after=retry_after)
        self.headers = headers


def unauthenticated() -> ProblemError:
    return ProblemError(401, "Unauthorized", headers={"Cache-Control": "no-store"})


def not_found() -> ProblemError:
    return ProblemError(404, "Not Found", headers={"Cache-Control": "no-store"})


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _handle(_: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(exc.problem, exc.headers)
