"""Seeded evaluation worlds (D-06). One case = one machine with a few weeks of hourly telemetry, a
written note and an event log, with a fault PLANTED (or none) on the case day. The truth is known
by construction; the engine's answer is whatever `build_case` computes.

Everything is driven by `random.Random(seed)`; nothing here reads the clock or the environment.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

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
from trace_core.normalise.time import hours_in, local_day_bounds
from trace_core.ports import EnginePorts
from trace_core.read.sensor import telemetry_series_id
from trace_eval.injector import PlantedFault, plant

TZ = "Asia/Kolkata"
CHANNELS = ("volt", "rotate", "pressure", "vibration")
CENTRE = {"volt": 170.0, "rotate": 450.0, "pressure": 100.0, "vibration": 40.0}
SPREAD = {"volt": 15.0, "rotate": 50.0, "pressure": 10.0, "vibration": 5.0}
HISTORY_DAYS = 40
CASE_OFFSET = 22  # the case day is this many days after the first day of history
FIRST_DAY = date(2015, 6, 1)
SPIKE_SPREADS = 15.0
NOW = "2015-08-06T04:00:00Z"

Kind = str
KINDS: tuple[Kind, ...] = (
    "contradicting_note",
    "late_timestamp",
    "removed_source",
    "flatline",
    "quiet_control",
)
# the outcome the engine must give: ∀ "ran normally" against the day's sensor state
EXPECTED: dict[Kind, str] = {
    "contradicting_note": "disagree",
    "late_timestamp": "disagree",
    "removed_source": "cant_tell",
    "flatline": "cant_tell",
    "quiet_control": "agree",
}
ABNORMAL: frozenset[Kind] = frozenset({"contradicting_note", "late_timestamp"})


@dataclass
class EvalCase:
    case_id: str
    kind: Kind
    machine: str
    day: date
    manifest: Manifest
    ports: EnginePorts
    note: str
    telemetry_dir: Path
    readings: dict[str, list[float]] = field(default_factory=dict)
    history: dict[str, list[float]] = field(default_factory=dict)
    expected: str = ""
    abnormal: bool = False


def machine_id(n: int) -> str:
    return f"machine:{n}"


def note_text(kind: Kind, n: int, day: date) -> str:
    written = day + timedelta(days=1)
    if kind == "late_timestamp":
        # written the next morning, with no reporting period: "yesterday" must be resolved
        return (
            f"Report date: {written:%d %b %Y} 09:10\n"
            f"Machine {n} ran normally yesterday.\n"
            "Signed: shift supervisor (synthetic)\n"
        )
    return (
        f"Report date: {written:%d %b %Y} 09:10\n"
        f"Reporting period: {day:%d %b %Y}\n"
        f"Machine {n} ran normally through both shifts.\n"
        "Signed: shift supervisor (synthetic)\n"
    )


def _series(
    rng: random.Random, kind: Kind, case_day: date
) -> tuple[dict[str, list[object]], dict[str, list[float]], dict[str, list[float]]]:
    rows: dict[str, list[object]] = {"ts": [], **{c: [] for c in CHANNELS}}
    day_vals: dict[str, list[float]] = {c: [] for c in CHANNELS}
    history: dict[str, list[float]] = {c: [] for c in CHANNELS}
    fault = None
    if kind in ABNORMAL:
        fault = PlantedFault("m", case_day, "spike", "vibration", (rng.randint(2, 20),))
    elif kind == "removed_source":
        start = rng.randint(0, 14)
        fault = PlantedFault("m", case_day, "dropout", "vibration", tuple(range(start, start + 8)))
    elif kind == "flatline":
        start = rng.randint(0, 14)
        fault = PlantedFault("m", case_day, "flatline", "vibration", tuple(range(start, start + 8)))
    for offset in range(HISTORY_DAYS):
        day = FIRST_DAY + timedelta(days=offset)
        stamps = hours_in(*local_day_bounds(day, TZ))
        values = {
            c: {h: CENTRE[c] + SPREAD[c] * rng.gauss(0.0, 1.0) for h in range(len(stamps))}
            for c in CHANNELS
        }
        if day == case_day and fault is not None:
            values["vibration"] = plant(
                values["vibration"],
                fault,
                centre=CENTRE["vibration"],
                scale=SPREAD["vibration"],
                spreads=SPIKE_SPREADS,
            )
        for h, ts in enumerate(stamps):
            present = {c: values[c].get(h) for c in CHANNELS}
            if all(v is None for v in present.values()):
                continue
            rows["ts"].append(ts)
            for c in CHANNELS:
                rows[c].append(present[c])
                if present[c] is not None:
                    (day_vals if day == case_day else history)[c].append(float(present[c]))  # type: ignore[arg-type]
    return rows, day_vals, history


def build_case_world(root: Path, n: int, kind: Kind, seed: int) -> EvalCase:
    """Write one case into `root` and return everything needed to build and judge it."""
    if kind not in EXPECTED:
        raise ValueError("unknown fault kind")
    rng = random.Random(seed)  # noqa: S311 (reproducible world, not security)
    case_day = FIRST_DAY + timedelta(days=CASE_OFFSET)
    case_id = f"eval-{kind}-m{n}-s{seed}"
    machine = machine_id(n)
    rows, day_vals, history = _series(rng, kind, case_day)
    derived = root / "derived"
    derived.mkdir(parents=True, exist_ok=True)
    series = telemetry_series_id(machine)
    pq.write_table(pa.table(rows), derived / series_filename(series))
    blobs = FsBlobStore(root / "blobs")
    note = note_text(kind, n, case_day)
    log = f'"datetime","machineID","errorID"\n2015-01-02 06:00:00,{n},"error1"\n'

    def put(data: str) -> tuple[str, int]:
        import io

        ref = blobs.put(io.BytesIO(data.encode("utf-8")), max_bytes=1_000_000)
        return ref.sha256, ref.size

    note_sha, note_size = put(note)
    log_sha, log_size = put(log)
    tel = ParquetTelemetryReader(derived)
    coverage = CoveragePeriod(start="2015-01-01T00:00:00Z", end="2016-01-01T00:00:00Z")
    base = {"case_id": case_id, "ingested_at": NOW, "synthetic": True}
    sources = [
        Source.model_validate(
            {
                **base,
                "source_id": "note",
                "modality": "text",
                "sha256": note_sha,
                "size": note_size,
                "mime": "text/plain",
                "origin": "eval:planted-note",
            }  # fmt: skip
        ),
        Source.model_validate(
            {
                **base,
                "source_id": "events-errors",
                "modality": "table",
                "sha256": log_sha,
                "size": log_size,
                "mime": "text/csv",
                "origin": "eval:log",
                "coverage_period": coverage.model_dump(),
            }  # fmt: skip
        ),
        Source.model_validate(
            {
                **base,
                "source_id": "telemetry",
                "modality": "sensor",
                "sha256": tel.partition_sha(series),
                "size": (derived / series_filename(series)).stat().st_size,
                "mime": "application/vnd.apache.parquet",
                "origin": "eval:planted-telemetry",
            }  # fmt: skip
        ),
    ]
    start, end = local_day_bounds(case_day, TZ)
    case = Case(
        case_id=case_id, title=f"{kind} on {machine}", entities=[machine], window_start=start,
        window_end=end, plant_tz=TZ, created_at=NOW,
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
        case_id=case_id, kind=kind, machine=machine, day=case_day,
        manifest=Manifest(case=case, sources=sources), ports=ports, note=note,
        telemetry_dir=derived, readings=day_vals, history=history,
        expected=EXPECTED[kind], abnormal=kind in ABNORMAL,
    )  # fmt: skip
