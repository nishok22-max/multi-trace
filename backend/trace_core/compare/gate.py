"""The six-check Comparability Gate (stage signature only)."""

from __future__ import annotations

from trace_core.models.claims import ClaimRecord
from trace_core.models.records import ComparisonRecord
from trace_core.stage_types import GateContext


def gate(a: ClaimRecord, b: ClaimRecord, ctx: GateContext) -> ComparisonRecord:
    raise NotImplementedError("M2/M3")
