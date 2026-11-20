"""Entity resolution (stage signature only)."""

from __future__ import annotations

from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.records import ReviewItem


def resolve_entities(
    claims: list[ClaimRecord], cfg: ConfigBundle
) -> tuple[list[ClaimRecord], list[ReviewItem]]:
    raise NotImplementedError("M2/M3")
