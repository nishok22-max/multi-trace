"""Sensor reader (stage signature only; body arrives in M2). The only module allowed
to aggregate readings (see tools/check_no_mean.py)."""

from __future__ import annotations

from trace_core.models.case import Case
from trace_core.models.config import ConfigBundle
from trace_core.ports import TelemetryReader
from trace_core.stage_types import SensorWindows


def read_sensor(telemetry: TelemetryReader, case: Case, cfg: ConfigBundle) -> SensorWindows:
    raise NotImplementedError("M2/M3")
