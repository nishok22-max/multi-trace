"""Image reader (stage signature only; body arrives in M3)."""

from __future__ import annotations

from trace_core.models.config import ConfigBundle
from trace_core.models.records import Source
from trace_core.ports import EnginePorts
from trace_core.stage_types import ReadResult


def read_image(src: Source, blob: bytes, cfg: ConfigBundle, ports: EnginePorts) -> ReadResult:
    raise NotImplementedError("M2/M3")
