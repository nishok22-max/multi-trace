"""Gap detection (stage signature only)."""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.records import Envelope
from trace_core.stage_types import SensorWindows


def detect_gaps(
    windows: SensorWindows,
    events: Sequence[ClaimRecord],
    envelopes: Sequence[Envelope],
    cfg: ConfigBundle,
) -> list[ClaimRecord]:
    raise NotImplementedError("M2/M3")
