"""Auth routes. Identity comes only from the session (promise 9)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from trace_api.deps import AuthRepoDep
from trace_api.problems import PROBLEM_BASE, ProblemError, unauthenticated
from trace_api.routers._common import ERRORS, CsrfHeader
from trace_api.security.sessions import (
    COOKIE,
    SESSION_TTL,
    BadCredentials,
    LockedOut,
    User,
)
from trace_core.models.api_io import LoginRequest, MeResponse

router = APIRouter(prefix="/auth", tags=["auth"])
NO_STORE = {"Cache-Control": "no-store"}


def _me(user: User) -> MeResponse:
    return MeResponse(user_id=user.user_id, display_name=user.display_name, role=user.role)


@router.post("/login", response_model=MeResponse, responses=ERRORS, operation_id="login")
def login(
    body: LoginRequest,
    x_trace_csrf: CsrfHeader,
    request: Request,
    response: Response,
    repo: AuthRepoDep,
) -> MeResponse:
    """CSRF header + JSON body, login included. Cache-Control: no-store."""
    try:
        token, user = repo.login(body.username, body.password, request.cookies.get(COOKIE))
    except LockedOut:
        raise ProblemError(
            429,
            "Too Many Requests",
            type_=PROBLEM_BASE + "rate-limited",
            headers={"Retry-After": "300", **NO_STORE},
            retry_after=300,
        ) from None
    except BadCredentials:
        raise unauthenticated() from None
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return _me(user)


@router.post("/logout", status_code=204, responses=ERRORS, operation_id="logout")
def logout(x_trace_csrf: CsrfHeader, request: Request, repo: AuthRepoDep) -> Response:
    repo.logout(request.cookies.get(COOKIE))
    out = Response(status_code=204, headers=NO_STORE)
    out.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
    return out


@router.get("/me", response_model=MeResponse, responses=ERRORS, operation_id="me")
def me(request: Request, response: Response, repo: AuthRepoDep) -> MeResponse:
    user = repo.lookup(request.cookies.get(COOKIE))
    if user is None:
        raise unauthenticated()
    response.headers["Cache-Control"] = "no-store"
    return _me(user)
