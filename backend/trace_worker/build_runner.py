"""Build child (A-08 minimal): a `multiprocessing` spawn target.

Never imports `trace_api`. Decoders (pypdfium2) are imported lazily inside `run_build`, so
merely importing this module is safe for the API process. The child calls `build_case` and
commits every record in ONE transaction, then writes status and a heartbeat to the builds row.

Guards (`trace_worker.child_guard`): self-deadline and parent-liveness watch are started first, so
a runaway or orphaned child ends itself. The parent kills the whole process tree on timeout and
sweeps stale builds at start (`trace_worker.sweep`).
TODO(M3/A-08): RLIMIT_AS (needs the measured peak VM), per-stage timings.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

HEARTBEAT_SECONDS = 5.0
SELF_DEADLINE_SECONDS = 170.0  # a little under the parent's timeout (BUILD_TIMEOUT_SECONDS)
_ALLOWED_ENV = frozenset(
    {
        "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME",
        "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "SYSTEMDRIVE", "PYTHONHASHSEED",
        "PYTHONPATH", "VIRTUAL_ENV", "LANG", "LC_ALL",
    }
)  # fmt: skip


@dataclass(frozen=True)
class BuildPaths:
    db: str
    blobs: str
    derived: str
    renders: str = ""


def scrub_env() -> None:
    """Allowlisted environment: no API keys reach the decoder process (A.3)."""
    for key in list(os.environ):
        if key not in _ALLOWED_ENV and not key.startswith("TRACE_"):
            del os.environ[key]
    for key in ("GROQ_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(key, None)
    os.environ["ARROW_DEFAULT_MEMORY_POOL"] = "system"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"


def run_build(paths: BuildPaths, case_id: str, build_id: str) -> None:
    """Spawn target. Exit code 0 on success; any failure marks the row `failed` and exits 1."""
    scrub_env()
    import multiprocessing

    from trace_worker.child_guard import start_deadline, start_parent_watch

    start_deadline(SELF_DEADLINE_SECONDS)
    parent = multiprocessing.parent_process()
    if parent is not None:
        start_parent_watch(parent.is_alive)
    from trace_adapters.blob_fs import FsBlobStore
    from trace_adapters.clock import SystemClock
    from trace_adapters.config_loader import load_config_bundle
    from trace_adapters.fakes.cache import DictExtractionCache
    from trace_adapters.fakes.llm import FakeLlm, IdentityRedactor
    from trace_adapters.fakes.ocr import FakeOcr
    from trace_adapters.image_prep import PillowImagePrep
    from trace_adapters.pdfium_reader import PdfiumReader
    from trace_adapters.sqlite.builds import BuildRepository
    from trace_adapters.sqlite.store import SqliteClaimStore
    from trace_adapters.telemetry_parquet import ParquetTelemetryReader
    from trace_core.build import build_case
    from trace_core.normalise.time import fmt_utc
    from trace_core.ports import EnginePorts
    from trace_worker.env import snapshot_hashes

    clock = SystemClock()
    repo = BuildRepository(paths.db)
    store = SqliteClaimStore(paths.db)
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            repo.heartbeat(build_id, fmt_utc(clock.now_utc()))

    repo.mark_running(build_id, fmt_utc(clock.now_utc()))
    threading.Thread(target=beat, daemon=True).start()
    try:
        started = time.monotonic()
        manifest = store.load_manifest(case_id)
        if manifest is None:
            raise LookupError("unknown case")
        config = load_config_bundle()
        ports = EnginePorts(
            blobs=FsBlobStore(paths.blobs),
            pdf=PdfiumReader(),
            ocr=FakeOcr(),  # OCR/VLM/LLM are off in the P0 build
            telemetry=ParquetTelemetryReader(paths.derived),
            cache=DictExtractionCache(),  # TODO(M3): persistent extraction cache
            clock=clock,
            llm=FakeLlm(),
            redactor=IdentityRedactor(),
            image_prep=PillowImagePrep(),
        )
        version = build_case(
            manifest,
            config,
            [],
            ports,
            parent=store.latest(case_id),
            hashes=snapshot_hashes(config, PdfiumReader.binary_version()),
        )
        built = time.monotonic()
        store.commit_build(version, manifest)  # ONE transaction
        committed = time.monotonic()
        if paths.renders:  # cited pages and crops: the API serves only what is cached here
            from pathlib import Path

            from trace_worker.prerender import prerender

            prerender(version, ports.blobs, Path(paths.renders))
        done = time.monotonic()
        repo.finish_ok(
            build_id,
            version.version,
            {
                "build_case": int((built - started) * 1000),
                "commit": int((committed - built) * 1000),
                "render": int((done - committed) * 1000),
            },
            {
                "claims": len(version.records.claims),
                "comparisons": len(version.records.comparisons),
                "conflicts": len(version.records.conflicts),
            },
            fmt_utc(clock.now_utc()),
        )
    except Exception as exc:
        # Never exception text: it may carry document content (HARDENING S-logs).
        repo.finish_failed(build_id, "failed", type(exc).__name__, fmt_utc(clock.now_utc()))
        raise SystemExit(1) from None
    finally:
        stop.set()
