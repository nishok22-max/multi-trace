"""Envelope learning (stage signature only; split-conformal robust max-z, PRD 10.3)."""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.models.case import Case
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle, Ontology
from trace_core.models.records import Envelope, Source
from trace_core.ports import TelemetryReader


def learn_envelopes(
    telemetry: TelemetryReader,
    events: Sequence[ClaimRecord],
    sources: Sequence[Source],
    case: Case,
    ontology: Ontology,
    cfg: ConfigBundle,
) -> list[Envelope]:
    """Per scope. Raises LogCoverageError when an event log does not cover a day."""
    raise NotImplementedError("M2/M3")
