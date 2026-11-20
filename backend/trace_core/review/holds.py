"""Review holds (stage signature only)."""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.records import Decision, ReviewEvent, ReviewItem


def apply_holds(
    claims: Sequence[ClaimRecord],
    review_items: Sequence[ReviewItem],
    events: Sequence[ReviewEvent],
    decisions: Sequence[Decision],
    cfg: ConfigBundle,
) -> tuple[list[ClaimRecord], list[ClaimRecord]]:
    """Returns (eligible, held). Uses pre-confidence."""
    raise NotImplementedError("M2/M3")
