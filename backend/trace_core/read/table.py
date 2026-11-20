"""Table reader (stage signature only; body arrives in M3)."""

from __future__ import annotations

from trace_core.models.config import ConfigBundle
from trace_core.models.records import Source
from trace_core.stage_types import ReadResult


def read_table(src: Source, blob: bytes, cfg: ConfigBundle) -> ReadResult:
    raise NotImplementedError("M2/M3")
