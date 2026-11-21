"""ParquetTelemetryReader: one Parquet partition per series (derived source, sha256 pinned).

Duplicate rows are preserved; the `ts` column is a fixed-width UTC string, so string order is time
order and half-open `[start, end)` filters are exact.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from trace_core.models.time import UtcStr


def series_filename(series_id: str) -> str:
    return series_id.replace("/", "__").replace(":", "-") + ".parquet"


class ParquetTelemetryReader:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _path(self, series_id: str) -> Path:
        return self._root / series_filename(series_id)

    def read(self, series_id: str, start: UtcStr, end: UtcStr) -> pa.Table:
        path = self._path(series_id)
        if not path.is_file():
            raise FileNotFoundError("unknown series")  # fail closed
        return pq.read_table(path, filters=[("ts", ">=", start), ("ts", "<", end)])

    def partition_sha(self, series_id: str) -> str:
        digest = hashlib.sha256()
        with self._path(series_id).open("rb") as fh:
            while chunk := fh.read(1 << 20):
                digest.update(chunk)
        return digest.hexdigest()
