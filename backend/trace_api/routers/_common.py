"""Shared declarations for the contract stubs (IMPLEMENTATION_PLAN C.4)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Header, Path, Query

from trace_core.models.api_io import Problem
from trace_core.models.base import CaseId, ClaimId, EntityId, ReviewId, SourceId

# Every write needs the CSRF header (SYSTEM_DESIGN 13). Enforced by middleware later;
# declared here so the generated client must send it.
CsrfHeader = Annotated[str, Header(alias="X-TRACE-CSRF")]

Cid = Annotated[CaseId, Path()]
Version = Annotated[int, Path(ge=1)]
Sid = Annotated[SourceId, Path()]
Bid = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
ClaimPath = Annotated[ClaimId, Path()]
Eid = Annotated[EntityId, Path()]
Rid = Annotated[ReviewId, Path()]

Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=500)]

# Error bodies are RFC 9457 problems (declared as application/json here; the server sends
# application/problem+json).
ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": Problem, "description": "Not signed in"},
    403: {"model": Problem, "description": "Role not allowed"},
    404: {"model": Problem, "description": "Unknown case or id (also for another case's id)"},
    422: {"model": Problem, "description": "Validation error"},
    501: {"model": Problem, "description": "Contract stub: not implemented yet"},
}

# Cache policy (PRD 13): versioned reads are `private, max-age=31536000, immutable` with
# ETag = manifest_hash and Vary: Cookie; latest, recheck and every write are `no-store`.
IMMUTABLE = "Cache-Control: private, max-age=31536000, immutable; ETag = manifest_hash."
NO_STORE = "Cache-Control: no-store."
