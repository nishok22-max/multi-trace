"""Unit normalisation (stage signature only)."""

from __future__ import annotations

from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle


def normalise_units(claims: list[ClaimRecord], cfg: ConfigBundle) -> list[ClaimRecord]:
    raise NotImplementedError("M2/M3")
