"""Dependencies. `resolve_case_and_authorize` is the single door to every case route.

Identity comes only from the session cookie (promise 9). `TRACE_DEV_AUTH=1` (default OFF)
admits a fixed local principal for development. An unknown case is 404, checked after
authentication so an anonymous caller cannot probe which cases exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from trace_adapters.clock import SystemClock
from trace_adapters.sqlite.builds import BuildRepository
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_api.problems import ProblemError, not_found, unauthenticated
from trace_api.routers._common import Cid
from trace_api.security.sessions import COOKIE, AuthRepository
from trace_api.services.build_service import BuildService
from trace_api.settings import Settings, load_settings
from trace_core.models.evidence import Principal, Role


@dataclass(frozen=True)
class AuthContext:
    principal: Principal
    role: Role
    display_name: str = ""


@lru_cache(maxsize=8)
def _store_at(path: str) -> SqliteClaimStore:
    return SqliteClaimStore(path)


def get_settings() -> Settings:
    return load_settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_store(settings: SettingsDep) -> SqliteClaimStore:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return _store_at(str(settings.db_path))


StoreDep = Annotated[SqliteClaimStore, Depends(get_store)]


def get_build_service(settings: SettingsDep) -> BuildService:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _store_at(str(settings.db_path))  # migrations applied before any child opens the file
    return BuildService(
        settings, BuildRepository(settings.db_path), _store_at(str(settings.db_path))
    )


def get_auth_repo(settings: SettingsDep) -> AuthRepository:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _store_at(str(settings.db_path))  # migrations first
    return AuthRepository(settings.db_path, SystemClock())


AuthRepoDep = Annotated[AuthRepository, Depends(get_auth_repo)]


def resolve_case_and_authorize(
    cid: Cid, request: Request, settings: SettingsDep, repo: AuthRepoDep
) -> AuthContext:
    if settings.dev_auth:
        context = AuthContext(
            principal=Principal(iss="local", sub="dev-user"),
            role="ingestor",
            display_name="Dev User",
        )
    else:
        user = repo.lookup(request.cookies.get(COOKIE))
        if user is None:
            raise unauthenticated()
        context = AuthContext(
            principal=Principal(iss="local", sub=user.user_id),
            role=user.role,
            display_name=user.display_name,
        )
    if _store_at(str(settings.db_path)).get_case(cid) is None:
        raise not_found()
    return context


def require_role(auth: AuthContext, *roles: Role) -> None:
    """403 unless the session's role is one of `roles`."""
    if auth.role not in roles:
        raise ProblemError(403, "Forbidden", headers={"Cache-Control": "no-store"})


AuthDep = Annotated[AuthContext, Depends(resolve_case_and_authorize)]
BuildServiceDep = Annotated[BuildService, Depends(get_build_service)]
