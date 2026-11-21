"""build_case (M2 walking skeleton): source -> read -> normalise -> gate -> snapshot.

Pure: all bytes arrive through ports. The build child (trace_worker.build_runner) supplies the
real adapters; tests supply fakes. Review items, holds, decisions, scoring and the independence
graph are TODO(M3); this function refuses decisions and any LLM/VLM mode rather than ignoring them.
"""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.canonical import CANON_VERSION
from trace_core.compare.conflicts import group_conflicts
from trace_core.compare.gate import gate
from trace_core.compare.pairs import candidate_pairs
from trace_core.ids import config_hash
from trace_core.labels import LABELS_SOURCE_ID, apply_labels, parse_labels
from trace_core.models.case import CaseVersion, Manifest, VersionRecords
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.records import ComparisonRecord, Decision
from trace_core.models.time import Interval
from trace_core.normalise.envelopes import learn_envelopes
from trace_core.normalise.sensor_state import derive_sensor_state
from trace_core.ports import EnginePorts
from trace_core.read.sensor import read_sensor
from trace_core.read.table import EVENT_ATTRIBUTE_NAMES, read_table
from trace_core.read.text import read_text
from trace_core.snapshot.manifest import ZERO, SnapshotInput, snapshot
from trace_core.stage_types import GateContext, SnapshotHashes

PDF_MIME = "application/pdf"
CSV_MIME = "text/csv"


def _default_hashes(cfg_hash: str) -> SnapshotHashes:
    return SnapshotHashes(
        config_hash=cfg_hash,
        engine_sha="unknown",
        lockfile_hash=ZERO,
        canon_version=CANON_VERSION,
        tesseract_version="none",
        traineddata_sha="none",
        pdfium_version="unknown",
        tzdata_version="unknown",
    )


def _order(claims: Sequence[ClaimRecord]) -> list[ClaimRecord]:
    unique = {c.claim_id: c for c in claims}
    return sorted(
        unique.values(),
        key=lambda c: (
            c.temporal.valid_time.start if isinstance(c.temporal.valid_time, Interval) else "9999",
            c.claim_id,
        ),
    )


def build_case(
    manifest: Manifest,
    config: ConfigBundle,
    decisions: Sequence[Decision],
    ports: EnginePorts,
    *,
    parent: CaseVersion | None = None,
    hashes: SnapshotHashes | None = None,
) -> CaseVersion:
    if config.llm.llm_mode != "off" or config.llm.vlm_mode != "off":
        raise NotImplementedError("P1")  # the P0 build makes no model call
    if decisions:
        raise NotImplementedError("M3")  # rerun_after_decision
    cfg_hash = config_hash(config)
    snap_hashes = (
        _default_hashes(cfg_hash)
        if hashes is None
        else hashes.model_copy(update={"config_hash": cfg_hash})
    )

    # 1 READ ----------------------------------------------------------------------------------
    labels: dict[str, str] = {}
    read: list[ClaimRecord] = []
    for src in sorted(manifest.sources, key=lambda s: s.source_id):
        if src.held_reason is not None:
            continue
        if src.source_id == LABELS_SOURCE_ID:
            labels = parse_labels(ports.blobs.open(src.sha256).read())
        elif src.modality == "text" and src.mime == PDF_MIME:
            read.extend(read_text(src, ports.blobs.open(src.sha256).read(), config, ports).claims)
        elif src.modality == "table" and src.mime == CSV_MIME:
            read.extend(read_table(src, ports.blobs.open(src.sha256).read(), config).claims)
        # sensor sources are read through the telemetry port; image sources are M3
    windows = read_sensor(ports.telemetry, manifest.case, config)

    # 2 NORMALISE -----------------------------------------------------------------------------
    events = [c for c in read if c.attribute in EVENT_ATTRIBUTE_NAMES]
    envelopes = learn_envelopes(
        ports.telemetry, events, manifest.sources, manifest.case, config.ontology, config
    )
    states = derive_sensor_state(windows, envelopes, config)
    claims = _order(
        apply_labels(
            [*read, *windows.claims, *windows.gap_claims, *states],
            labels,
            config.case.plant_tz,
        )
    )

    # 3 COMPARE -------------------------------------------------------------------------------
    groups = {rule.attribute_group: rule.attribute_group for rule in config.ontology.phrases}
    ctx = GateContext(config=config, config_hash=cfg_hash, envelopes=envelopes)
    compared: dict[str, ComparisonRecord] = {}
    for a, b in candidate_pairs(claims, groups):
        record = gate(a, b, ctx)
        compared[record.comparison_id] = record
    comparisons = [compared[k] for k in sorted(compared)]
    conflicts = sorted(group_conflicts(comparisons, claims), key=lambda c: c.conflict_id)

    # 5 SNAPSHOT ------------------------------------------------------------------------------
    records = VersionRecords(
        claims=claims,
        comparisons=comparisons,
        conflicts=conflicts,
        envelopes=sorted(envelopes, key=lambda e: e.envelope_id),
        review_items=[],
        decisions=[],
    )
    return snapshot(
        manifest.case,
        parent,
        SnapshotInput(records=records, sources=list(manifest.sources)),
        snap_hashes,
        ports.clock,
    )
