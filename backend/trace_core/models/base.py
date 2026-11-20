"""Base model classes and constrained ID types (IMPLEMENTATION_PLAN A.6, C.1)."""

from __future__ import annotations

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, StringConstraints


class CoreModel(BaseModel):
    """Frozen, extra-forbidding, strict. Base of every core-internal model."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    # Fields that hold wall-clock values. They are excluded from every record hash
    # (promise 8: hashes must not depend on when a build ran).
    wall_clock_fields: ClassVar[frozenset[str]] = frozenset()


class WireModel(BaseModel):
    """Frozen, extra-forbidding API model. Not strict: JSON bodies are coerced as usual."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    wall_clock_fields: ClassVar[frozenset[str]] = frozenset()


def _id(prefix: str) -> StringConstraints:
    return StringConstraints(pattern=rf"^{prefix}_[0-9a-f]{{24}}$")


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ClaimId = Annotated[str, _id("clm")]
ComparisonId = Annotated[str, _id("cmp")]
ConflictId = Annotated[str, _id("cf")]
ReviewId = Annotated[str, _id("rv")]
ReviewEventId = Annotated[str, _id("rve")]
DecisionId = Annotated[str, _id("dec")]
EnvelopeId = Annotated[str, _id("env")]

CaseId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
SourceId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
EntityId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]*:[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9_.-]+)*$"),
]
SeriesId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")]
