"""Adapter-side derived sources (IMPLEMENTATION_PLAN C.3b).

`split_telemetry` writes one Parquet partition per machine (UTC `ts`, duplicates preserved, no
resampling or averaging). `split_events` keeps the raw CSV lines of the machines of interest
byte for byte, so `row_sha256` pointers stay verifiable. Both return the sha256 of the artifact
and of the raw file it was derived from.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from trace_adapters.telemetry_parquet import series_filename


@dataclass(frozen=True)
class DerivedSource:
    series_or_name: str
    path: Path
    sha256: str
    rows: int
    parent_sha256: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def split_telemetry(
    csv_path: Path, out_dir: Path, machines: Iterable[int], plant_tz: str
) -> list[DerivedSource]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(csv_path)
    parent = file_sha256(csv_path)
    stamps = (
        pd.to_datetime(frame["datetime"])
        .dt.tz_localize(plant_tz, ambiguous="raise", nonexistent="raise")
        .dt.tz_convert("UTC")
        .dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    frame = frame.assign(ts=stamps).drop(columns=["datetime"])
    channels = [c for c in frame.columns if c not in ("ts", "machineID")]
    derived: list[DerivedSource] = []
    for machine in sorted(set(machines)):
        part = frame.loc[frame["machineID"] == machine, ["ts", *channels]]
        series_id = f"telemetry/machine:{machine}"
        path = out_dir / series_filename(series_id)
        pq.write_table(pa.Table.from_pandas(part, preserve_index=False), path, compression="zstd")
        derived.append(DerivedSource(series_id, path, file_sha256(path), len(part), parent))
    return derived


def split_events(csv_path: Path, out_path: Path, machines: Iterable[int]) -> DerivedSource:
    wanted = {str(m).encode() for m in machines}
    lines = csv_path.read_bytes().splitlines()
    kept = [lines[0]] + [ln for ln in lines[1:] if ln.split(b",")[1].strip(b'"') in wanted]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"\n".join(kept) + b"\n")
    return DerivedSource(
        out_path.name, out_path, file_sha256(out_path), len(kept) - 1, file_sha256(csv_path)
    )
