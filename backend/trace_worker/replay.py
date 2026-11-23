"""Verify replay (FR-UI-8): rebuild a version from stored artifacts and compare the manifest hash.

Runs in a spawned child (it decodes PDFs). v1 is rebuilt from the sources; every later version is
rebuilt by applying that version's stored decisions to the previous rebuilt version, exactly as the
decision service did. The result is the rebuilt manifest hash of the requested version; the caller
compares it with the stored one. Nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass

from trace_worker.build_runner import BuildPaths, scrub_env


@dataclass(frozen=True)
class ReplayOutcome:
    manifest_hash: str
    ok: bool


def replay_manifest(paths: BuildPaths, case_id: str, version: int) -> str:
    """The manifest hash of `version` rebuilt from stored artifacts (pure of the stored version)."""
    from trace_adapters.blob_fs import FsBlobStore
    from trace_adapters.clock import SystemClock
    from trace_adapters.config_loader import load_config_bundle
    from trace_adapters.fakes.cache import DictExtractionCache
    from trace_adapters.fakes.llm import FakeLlm, IdentityRedactor
    from trace_adapters.fakes.ocr import FakeOcr
    from trace_adapters.image_prep import PillowImagePrep
    from trace_adapters.pdfium_reader import PdfiumReader
    from trace_adapters.sqlite.store import SqliteClaimStore
    from trace_adapters.telemetry_parquet import ParquetTelemetryReader
    from trace_core.build import build_case
    from trace_core.ports import EnginePorts
    from trace_core.rerun import rerun_after_decision
    from trace_worker.env import snapshot_hashes

    store = SqliteClaimStore(paths.db)
    manifest = store.load_manifest(case_id)
    stored = [store.get_version(case_id, n) for n in range(1, version + 1)]
    if manifest is None or any(v is None for v in stored):
        raise LookupError("unknown case or version")
    config = load_config_bundle()
    ports = EnginePorts(
        blobs=FsBlobStore(paths.blobs),
        pdf=PdfiumReader(),
        ocr=FakeOcr(),
        telemetry=ParquetTelemetryReader(paths.derived),
        cache=DictExtractionCache(),
        clock=SystemClock(),
        llm=FakeLlm(),
        redactor=IdentityRedactor(),
        image_prep=PillowImagePrep(),
    )
    rebuilt = build_case(
        manifest,
        config,
        [],
        ports,
        hashes=snapshot_hashes(config, PdfiumReader.binary_version()),
    )
    seen: set[str] = set()
    for step in stored[1:]:
        assert step is not None  # noqa: S101
        new = [d for d in step.records.decisions if d.decision_id not in seen]
        seen.update(d.decision_id for d in step.records.decisions)
        rebuilt = rerun_after_decision(rebuilt, new, config, ports.clock)
    return rebuilt.manifest_hash


def replay_target(paths: BuildPaths, case_id: str, version: int, out: object) -> None:
    """Spawn target: puts `("ok", hash)` or `("error", type name)` on the queue."""
    scrub_env()
    try:
        out.put(("ok", replay_manifest(paths, case_id, version)))  # type: ignore[attr-defined]
    except Exception as exc:  # never exception text: it can hold document content
        out.put(("error", type(exc).__name__))  # type: ignore[attr-defined]
