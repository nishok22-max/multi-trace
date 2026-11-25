"""Real-telemetry evaluation worlds (D-09). The base data is the genuine PdM telemetry and event
logs of a machine; only the planted fault is synthetic, so the quiet days the false-alarm rate is
measured on are real days. Everything is driven by `random.Random(seed)`; the planted truth is
known by construction.

The dataset is a third-party download (`seed/dataset/*.csv`, never committed); this module only
reads it.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped, unused-ignore]
import pyarrow as pa
import pyarrow.parquet as pq

from trace_adapters.blob_fs import FsBlobStore
from trace_adapters.fakes.cache import DictExtractionCache
from trace_adapters.fakes.clock import FixedClock
from trace_adapters.fakes.llm import FakeLlm, IdentityRedactor
from trace_adapters.fakes.ocr import FakeOcr
from trace_adapters.fakes.pdf import FakePdfReader
from trace_adapters.telemetry_parquet import ParquetTelemetryReader, series_filename
from trace_core.models.case import Case, Manifest
from trace_core.models.records import CoveragePeriod, Source
from trace_core.normalise.time import (
    fmt_utc,
    local_day_bounds,
    local_naive_to_utc,
    parse_utc,
)
from trace_core.ports import EnginePorts
from trace_core.read.sensor import telemetry_series_id
from trace_eval.injector import PlantedFault, plant
from trace_eval.worlds import (
    ABNORMAL,
    CHANNELS,
    EXPECTED,
    NOW,
    SPIKE_SPREADS,
    TZ,
    EvalCase,
    machine_id,
    note_text,
)

MAD_TO_SIGMA = 1.4826
EVENT_MARGIN_DAYS = 5
EDGE_DAYS = 8
LOGS = (
    ("errors", "PdM_errors.csv"),
    ("maint", "PdM_maint.csv"),
    ("failures", "PdM_failures.csv"),
)


@dataclass
class RealData:
    """The telemetry of the chosen machines and every machine's event lines, read once."""

    frames: dict[int, pd.DataFrame]  # machine -> ts (UTC string) + channels
    event_lines: dict[tuple[str, int], list[bytes]]  # (log, machine) -> raw CSV lines
    log_headers: dict[str, bytes]
    event_days: dict[int, set[date]]  # machine -> plant-local dates with an event
    coverage: CoveragePeriod
    models: dict[int, str]  # machine -> model name


def dataset_available(dataset: Path) -> bool:
    return all(
        (dataset / f).is_file()
        for f in (
            "PdM_telemetry.csv",
            "PdM_errors.csv",
            "PdM_maint.csv",
            "PdM_failures.csv",
            "PdM_machines.csv",
        )
    )


def machine_numbers(dataset: Path) -> list[int]:
    return sorted(int(m) for m in pd.read_csv(dataset / "PdM_machines.csv")["machineID"])


def load_real(dataset: Path, machines: list[int]) -> RealData:
    wanted = set(machines)
    tel = pd.read_csv(dataset / "PdM_telemetry.csv")
    first_local = pd.to_datetime(tel["datetime"].iloc[0]).to_pydatetime()
    last_local = pd.to_datetime(tel["datetime"].iloc[-1]).to_pydatetime()
    tel = tel[tel["machineID"].isin(wanted)]
    stamps = (
        pd.to_datetime(tel["datetime"])
        .dt.tz_localize(TZ, ambiguous="raise", nonexistent="raise")
        .dt.tz_convert("UTC")
        .dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    tel = tel.assign(ts=stamps)
    frames = {
        n: tel.loc[tel["machineID"] == n, ["ts", *CHANNELS]].reset_index(drop=True)
        for n in machines
    }
    event_lines: dict[tuple[str, int], list[bytes]] = {}
    headers: dict[str, bytes] = {}
    days: dict[int, set[date]] = {n: set() for n in machines}
    for kind, name in LOGS:
        lines = (dataset / name).read_bytes().splitlines()
        headers[kind] = lines[0]
        for raw in lines[1:]:
            cells = raw.split(b",")
            n = int(cells[1].strip(b'"'))
            if n in wanted:
                event_lines.setdefault((kind, n), []).append(raw)
                days[n].add(pd.to_datetime(cells[0].decode()).date())
    models = {
        int(r.machineID): str(r.model)
        for r in pd.read_csv(dataset / "PdM_machines.csv").itertuples()
    }
    start = local_naive_to_utc(first_local, TZ)
    end = fmt_utc(parse_utc(local_naive_to_utc(last_local, TZ)) + timedelta(hours=1))
    return RealData(
        frames, event_lines, headers, days, CoveragePeriod(start=start, end=end), models
    )


def _local_days(frame: pd.DataFrame) -> dict[date, list[int]]:
    """plant-local date -> row positions (a day is [D 00:00, D+1 00:00) plant-local)."""
    by_day: dict[date, list[int]] = {}
    for position, ts in enumerate(frame["ts"]):
        local = pd.Timestamp(ts).tz_convert(TZ).date()
        by_day.setdefault(local, []).append(position)
    return by_day


def candidate_days(frame: pd.DataFrame, events: set[date]) -> list[date]:
    """Full days (24 rows) far from any event and from the edges of the data."""
    by_day = _local_days(frame)
    days = sorted(by_day)
    lo, hi = days[0] + timedelta(days=EDGE_DAYS), days[-1] - timedelta(days=EDGE_DAYS)
    out: list[date] = []
    for d in days:
        if len(by_day[d]) != 24 or not lo <= d <= hi:
            continue
        if any(abs((d - e).days) <= EVENT_MARGIN_DAYS for e in events):
            continue
        out.append(d)
    return out


def build_real_case(
    root: Path, data: RealData, n: int, kind: str, seed: int, case_id: str | None = None
) -> EvalCase:
    if kind not in EXPECTED:
        raise ValueError("unknown fault kind")
    rng = random.Random(seed)  # noqa: S311 (reproducible world, not security)
    frame = data.frames[n].copy()
    days = candidate_days(frame, data.event_days[n])
    if not days:
        raise ValueError(f"machine {n} has no usable quiet day")
    case_day = days[rng.randrange(len(days))]
    positions = _local_days(frame)[case_day]
    vib = frame["vibration"]
    centre = float(vib.median())
    scale = MAD_TO_SIGMA * float((vib - centre).abs().median())
    fault: PlantedFault | None = None
    if kind in ABNORMAL:
        fault = PlantedFault("m", case_day, "spike", "vibration", (rng.randint(2, 20),))
    elif kind in ("removed_source", "flatline"):
        start = rng.randint(0, 14)
        fault = PlantedFault(
            "m", case_day, "dropout" if kind == "removed_source" else "flatline", "vibration",
            tuple(range(start, start + 8)),
        )  # fmt: skip
    if fault is not None:
        day_values = {h: float(vib.iloc[p]) for h, p in enumerate(positions)}
        changed = plant(day_values, fault, centre=centre, scale=scale, spreads=SPIKE_SPREADS)
        column = frame["vibration"].astype("float64")
        for h, p in enumerate(positions):
            column.iloc[p] = changed.get(h, float("nan"))
        frame["vibration"] = column
    readings = {c: [float(v) for v in frame[c].iloc[positions] if v == v] for c in CHANNELS}
    history = {
        c: [float(v) for i, v in enumerate(frame[c]) if i not in set(positions) and v == v][:5000]
        for c in CHANNELS
    }

    derived = root / "derived"
    derived.mkdir(parents=True, exist_ok=True)
    machine = machine_id(n)
    series = telemetry_series_id(machine)
    table = pa.Table.from_pandas(frame[["ts", *CHANNELS]], preserve_index=False)
    pq.write_table(table, derived / series_filename(series), compression="zstd")
    tel = ParquetTelemetryReader(derived)
    blobs = FsBlobStore(root / "blobs")

    def put(content: bytes) -> tuple[str, int]:
        ref = blobs.put(io.BytesIO(content), max_bytes=20_000_000)
        return ref.sha256, ref.size

    note = note_text(kind, n, case_day)
    cid = case_id or f"real-{kind}-m{n}-s{seed}"
    base = {"case_id": cid, "ingested_at": NOW, "synthetic": False}
    sources: list[Source] = []
    sha, size = put(note.encode("utf-8"))
    sources.append(
        Source.model_validate(
            {
                **base,
                "source_id": "note",
                "modality": "text",
                "sha256": sha,
                "size": size,
                "mime": "text/plain",
                "origin": "eval:planted-note",
                "synthetic": True,
            }
        )  # fmt: skip
    )
    for log, _name in LOGS:
        lines = data.event_lines.get((log, n), [])
        content = b"\n".join([data.log_headers[log], *lines]) + b"\n"
        sha, size = put(content)
        sources.append(
            Source.model_validate(
                {
                    **base,
                    "source_id": f"events-{log}",
                    "modality": "table",
                    "sha256": sha,
                    "size": size,
                    "mime": "text/csv",
                    "origin": f"dataset:{log}",
                    "coverage_period": data.coverage.model_dump(),
                }
            )  # fmt: skip
        )
    sources.append(
        Source.model_validate(
            {
                **base,
                "source_id": "telemetry",
                "modality": "sensor",
                "sha256": tel.partition_sha(series),
                "size": (derived / series_filename(series)).stat().st_size,
                "mime": "application/vnd.apache.parquet",
                "origin": "dataset:telemetry+planted-fault",
            }
        )  # fmt: skip
    )
    start_utc, end_utc = local_day_bounds(case_day, TZ)
    case = Case(
        case_id=cid, title=f"{kind} on {machine}", entities=[machine], window_start=start_utc,
        window_end=end_utc, plant_tz=TZ, created_at=NOW,
    )  # fmt: skip
    ports = EnginePorts(
        blobs=blobs,
        pdf=FakePdfReader([]),
        ocr=FakeOcr(),
        telemetry=tel,
        cache=DictExtractionCache(),
        clock=FixedClock(NOW),
        llm=FakeLlm(),
        redactor=IdentityRedactor(),
    )
    return EvalCase(
        case_id=cid, kind=kind, machine=machine, day=case_day,
        manifest=Manifest(case=case, sources=sources), ports=ports, note=note,
        telemetry_dir=derived, readings=readings, history=history,
        expected=EXPECTED[kind], abnormal=kind in ABNORMAL,
    )  # fmt: skip
