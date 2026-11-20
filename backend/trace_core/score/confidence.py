"""Confidence scoring (stage signatures only)."""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.records import ComparisonRecord
from trace_core.stage_types import Provenance


def score_pre(claims: Sequence[ClaimRecord], cfg: ConfigBundle) -> list[ClaimRecord]:
    """Pre-confidence; corroboration = 0."""
    raise NotImplementedError("M2/M3")


def score(
    claims: Sequence[ClaimRecord],
    comparisons: Sequence[ComparisonRecord],
    provenance: Provenance,
    cfg: ConfigBundle,
) -> list[ClaimRecord]:
    """Final confidence. Never alters holds."""
    raise NotImplementedError("M2/M3")
