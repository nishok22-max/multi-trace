"""build_case (stage signature only; body arrives in M2/M3)."""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.models.case import CaseVersion, Manifest
from trace_core.models.config import ConfigBundle
from trace_core.models.records import Decision
from trace_core.ports import EnginePorts


def build_case(
    manifest: Manifest,
    config: ConfigBundle,
    decisions: Sequence[Decision],
    ports: EnginePorts,
) -> CaseVersion:
    raise NotImplementedError("M2/M3")
