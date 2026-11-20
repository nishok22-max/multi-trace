"""rerun_after_decision (stage signature only; body arrives in M3)."""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.models.case import CaseVersion
from trace_core.models.config import ConfigBundle
from trace_core.models.records import Decision
from trace_core.ports import Clock


def rerun_after_decision(
    parent: CaseVersion,
    decisions: Sequence[Decision],
    config: ConfigBundle,
    clock: Clock,
) -> CaseVersion:
    raise NotImplementedError("M2/M3")
