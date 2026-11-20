"""FakeTelemetryReader: in-memory series with a UTC `ts` column."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trace_core.canonical import canonical_sha256


@dataclass(frozen=True)
class FakeTable:
    columns: dict[str, list[Any]]

    @property
    def num_rows(self) -> int:
        return len(next(iter(self.columns.values()), []))

    @property
    def column_names(self) -> list[str]:
        return list(self.columns)

    def to_pydict(self) -> dict[str, list[Any]]:
        return {k: list(v) for k, v in self.columns.items()}


class FakeTelemetryReader:
    """`series` maps series_id -> columns, one of which is `ts` (fixed-width UTC strings)."""

    def __init__(self, series: dict[str, dict[str, list[Any]]]) -> None:
        self._series = series

    def read(self, series_id: str, start: str, end: str) -> FakeTable:
        data = self._series[series_id]  # unknown series: KeyError (fail closed)
        keep = [i for i, ts in enumerate(data["ts"]) if start <= ts < end]  # half-open
        return FakeTable({name: [col[i] for i in keep] for name, col in data.items()})

    def partition_sha(self, series_id: str) -> str:
        return canonical_sha256(self._series[series_id])
