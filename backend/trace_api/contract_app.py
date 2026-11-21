"""The contract app: every C.4 route declared as a typed stub (501 problem+json).

Its OpenAPI document is the frozen API contract (`schemas/openapi.json`, `schema.d.ts`).
`trace_api.main` does not mount these stubs; real services replace them from M2 on.
"""

from __future__ import annotations

from fastapi import FastAPI

from trace_api.problems import register_handlers
from trace_api.routers import auth, builds, cases, claims, health, review, sources, versions
from trace_api.routers import eval as eval_router

API_PREFIX = "/api/v1"
CONTRACT_VERSION = "1"


def build_contract_app() -> FastAPI:
    app = FastAPI(
        title="TRACE API",
        version=CONTRACT_VERSION,
        description="TRACE contract (contracts-v1). Errors are RFC 9457 problem+json.",
        docs_url=None,
        redoc_url=None,
    )
    register_handlers(app)
    app.include_router(health.router)  # probes are not versioned
    for module in (auth, cases, sources, builds, versions, claims, review, eval_router):
        app.include_router(module.router, prefix=API_PREFIX)
    return app
