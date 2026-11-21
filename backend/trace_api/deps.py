"""Dependencies. `resolve_case_and_authorize` is the single door to every case route.

Until real auth lands (A-09, M3) it returns a fixed local viewer principal ONLY when
TRACE_DEV_AUTH=1; the default is OFF, which means 401. An unknown case is 404, checked after
authentication so an anonymous caller cannot probe which cases exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from trace_adapters.sqlite.builds import BuildRepository
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_api.problems import not_found, unauthenticated
from trace_api.routers._common import Cid
from trace_api.services.build_service import BuildService
from trace_api.settings import Settings, load_settings
from trace_core.models.evidence import Principal, Role


@dataclass(frozen=True)
class AuthContext:
    principal: Principal
    role: Role


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


def resolve_case_and_authorize(cid: Cid, settings: SettingsDep) -> AuthContext:
    if not settings.dev_auth:
        raise unauthenticated()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if _store_at(str(settings.db_path)).get_case(cid) is None:
        raise not_found()
    # TODO(M3/A-09): real sessions and roles (ingestor for build, reviewer for decisions).
    return AuthContext(principal=Principal(iss="local", sub="dev-viewer"), role="viewer")


AuthDep = Annotated[AuthContext, Depends(resolve_case_and_authorize)]
BuildServiceDep = Annotated[BuildService, Depends(get_build_service)]
