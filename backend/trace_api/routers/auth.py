"""Auth routes. Identity comes only from the session (promise 9)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from trace_api.problems import not_implemented
from trace_api.routers._common import ERRORS, CsrfHeader
from trace_core.models.api_io import LoginRequest, MeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=MeResponse, responses=ERRORS, operation_id="login")
def login(body: LoginRequest, x_trace_csrf: CsrfHeader) -> object:
    """CSRF header + JSON body, login included. Cache-Control: no-store."""
    return not_implemented()


@router.post("/logout", status_code=204, responses=ERRORS, operation_id="logout")
def logout(x_trace_csrf: CsrfHeader) -> Response:
    return not_implemented()


@router.get("/me", response_model=MeResponse, responses=ERRORS, operation_id="me")
def me() -> object:
    return not_implemented()
