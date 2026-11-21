"""seed_build: create the M2 skeleton case (blobs, derived sources, case + sources rows).

Reads the downloaded PdM CSVs (never committed), derives the case-scoped artifacts (one Parquet
partition for the machine, event-log slices), stores the authored files as blobs and registers
the case and its sources. The raw full-size files are registered as held sources: they are the
provenance of the derived ones and are never read directly.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import yaml

from tools import verify_seed
from trace_adapters.blob_fs import FsBlobStore
from trace_adapters.clock import SystemClock
from trace_adapters.config_loader import load_config_bundle
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_adapters.telemetry_split import file_sha256, split_events, split_telemetry
from trace_core.models.case import Case
from trace_core.models.records import Source
from trace_core.normalise.time import fmt_utc, local_day_bounds

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "seed"
DATASET = SEED / "dataset"
HELD_RAW = "raw source: read only through its case-scoped derived slice"
LOGS = (("errors", "PdM_errors.csv"), ("maint", "PdM_maint.csv"), ("failures", "PdM_failures.csv"))


def skeleton_config() -> dict[str, str]:
    return yaml.safe_load((SEED / "skeleton_case.yaml").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def seed_skeleton(data_dir: Path) -> str:
    """Idempotent: running it again appends nothing new. Returns the case id."""
    problems = verify_seed.verify()
    if problems:
        raise SystemExit("seed bytes do not match SHA256SUMS: " + "; ".join(problems))
    missing = [
        f for f in ("PdM_telemetry.csv", *[n for _, n in LOGS]) if not (DATASET / f).is_file()
    ]
    if missing:
        raise SystemExit("missing dataset files in seed/dataset: " + ", ".join(missing))

    cfg = skeleton_config()
    case_id, entity, machine = cfg["case_id"], cfg["entity_id"], int(cfg["machine"])
    tz = load_config_bundle().case.plant_tz
    now = fmt_utc(SystemClock().now_utc())
    blobs = FsBlobStore(data_dir / "blobs")
    derived_dir = data_dir / "derived"

    def blob(path: Path) -> tuple[str, int]:
        ref = blobs.put(io.BytesIO(path.read_bytes()), max_bytes=25 * 1024 * 1024)
        return ref.sha256, ref.size

    def source(source_id: str, **fields: object) -> Source:
        base: dict[str, object] = {
            "source_id": source_id,
            "case_id": case_id,
            "ingested_at": now,
            "synthetic": False,
        }
        return Source.model_validate({**base, **fields})

    sources: list[Source] = []
    pdf_sha, pdf_size = blob(SEED / cfg["report"])
    sources.append(
        source(
            "report-0805",
            modality="text",
            sha256=pdf_sha,
            size=pdf_size,
            mime="application/pdf",
            origin="seed/" + cfg["report"],
            synthetic=True,
        )
    )
    label_sha, label_size = blob(SEED / "labels.yaml")
    sources.append(
        source(
            "labels",
            modality="text",
            sha256=label_sha,
            size=label_size,
            mime="application/x-yaml",
            origin="seed/labels.yaml",
            synthetic=True,
        )
    )

    raw_tel = DATASET / "PdM_telemetry.csv"
    sources.append(
        source(
            "pdm-telemetry-csv",
            modality="sensor",
            sha256=file_sha256(raw_tel),
            size=raw_tel.stat().st_size,
            mime="text/csv",
            origin="seed/dataset/PdM_telemetry.csv",
            held_reason=HELD_RAW,
        )
    )
    for part in split_telemetry(raw_tel, derived_dir, [machine], tz):
        sources.append(
            source(
                f"telemetry-machine-{machine}",
                modality="sensor",
                sha256=part.sha256,
                size=part.path.stat().st_size,
                mime="application/vnd.apache.parquet",
                origin=f"derived:{part.series_or_name}",
                derived_from_sources=["pdm-telemetry-csv"],
            )
        )
    for kind, name in LOGS:
        raw = DATASET / name
        raw_id = f"pdm-{kind}-csv"
        sources.append(
            source(
                raw_id,
                modality="table",
                sha256=file_sha256(raw),
                size=raw.stat().st_size,
                mime="text/csv",
                origin=f"seed/dataset/{name}",
                held_reason=HELD_RAW,
            )
        )
        part = split_events(raw, derived_dir / f"events_{kind}_m{machine}.csv", [machine])
        sha, size = blob(part.path)
        sources.append(
            source(
                f"events-{kind}-machine-{machine}",
                modality="table",
                sha256=sha,
                size=size,
                mime="text/csv",
                origin=f"derived:{name}",
                derived_from_sources=[raw_id],
            )
        )

    start, end = local_day_bounds(date.fromisoformat(cfg["day"]), tz)
    case = Case(
        case_id=case_id,
        title=cfg["title"],
        entities=[entity],
        window_start=start,
        window_end=end,
        plant_tz=tz,
        created_at=now,
    )
    SqliteClaimStore(data_dir / "trace.db").append(case_id, [case, *sources])
    return case_id
