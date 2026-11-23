"""build_case (M2 walking skeleton): source -> read -> normalise -> gate -> snapshot.

Pure: all bytes arrive through ports. The build child (trace_worker.build_runner) supplies the
real adapters; tests supply fakes. Review items, holds, decisions, scoring and the independence
graph are TODO(M3); this function refuses decisions and any LLM/VLM mode rather than ignoring them.
"""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.canonical import CANON_VERSION
from trace_core.ids import config_hash
from trace_core.labels import LABELS_SOURCE_ID, apply_labels, parse_labels
from trace_core.models.case import CaseVersion, Manifest, VersionRecords
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.records import Decision, ReviewItem
from trace_core.normalise.entities import resolve_entities
from trace_core.normalise.envelopes import learn_envelopes
from trace_core.normalise.gaps import detect_gaps
from trace_core.normalise.sensor_state import derive_sensor_state
from trace_core.normalise.time import fmt_utc, resolve_time
from trace_core.normalise.units import normalise_units
from trace_core.pipeline import compare_and_score, order_claims
from trace_core.ports import EnginePorts
from trace_core.read.image import read_image
from trace_core.read.sensor import read_sensor
from trace_core.read.table import EVENT_ATTRIBUTE_NAMES, read_table
from trace_core.read.text import read_plaintext, read_text
from trace_core.score.confidence import score_pre
from trace_core.snapshot.manifest import ZERO, SnapshotInput, snapshot
from trace_core.stage_types import SnapshotHashes

PDF_MIME = "application/pdf"
CSV_MIME = "text/csv"
PLAIN_MIMES = frozenset({"text/plain", "text/markdown"})


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
    held_items: list[ReviewItem] = []
    for src in sorted(manifest.sources, key=lambda s: s.source_id):
        if src.held_reason is not None:
            continue
        if src.source_id == LABELS_SOURCE_ID:
            labels = parse_labels(ports.blobs.open(src.sha256).read())
        elif src.modality == "text" and src.mime == PDF_MIME:
            got = read_text(src, ports.blobs.open(src.sha256).read(), config, ports)
            read.extend(got.claims)
            held_items.extend(got.review_items)
        elif src.modality == "text" and src.mime in PLAIN_MIMES:
            read.extend(read_plaintext(src, ports.blobs.open(src.sha256).read(), config).claims)
        elif src.modality == "image":
            got = read_image(src, ports.blobs.open(src.sha256).read(), config, ports)
            read.extend(got.claims)
            held_items.extend(got.review_items)
        elif src.modality == "table" and src.mime == CSV_MIME:
            read.extend(read_table(src, ports.blobs.open(src.sha256).read(), config).claims)
        # sensor sources are read through the telemetry port
    windows = read_sensor(ports.telemetry, manifest.case, config)

    # 2 NORMALISE -----------------------------------------------------------------------------
    opened_at = fmt_utc(ports.clock.now_utc())
    read, entity_items = resolve_entities(read, config, opened_at=opened_at)
    review_items = [*held_items, *entity_items]
    read = score_pre(normalise_units(resolve_time(read, config), config), config)
    events = [c for c in read if c.attribute in EVENT_ATTRIBUTE_NAMES]
    envelopes = learn_envelopes(
        ports.telemetry, events, manifest.sources, manifest.case, config.ontology, config
    )
    windows = windows.model_copy(
        update={
            "gap_claims": [*windows.gap_claims, *detect_gaps(windows, events, envelopes, config)]
        }
    )
    states = derive_sensor_state(windows, envelopes, config)
    claims = order_claims(
        apply_labels(
            [*read, *windows.claims, *windows.gap_claims, *states],
            labels,
            config.case.plant_tz,
        )
    )

    # 3-4 COMPARE + TRUST ---------------------------------------------------------------------
    claims, comparisons, conflicts = compare_and_score(
        claims, review_items, [], [], envelopes, manifest.sources, config, cfg_hash
    )

    # 5 SNAPSHOT ------------------------------------------------------------------------------
    records = VersionRecords(
        claims=claims,
        comparisons=comparisons,
        conflicts=conflicts,
        envelopes=sorted(envelopes, key=lambda e: (-len(e.scope), e.envelope_id)),
        review_items=sorted(review_items, key=lambda r: r.review_id),
        decisions=[],
    )
    return snapshot(
        manifest.case,
        parent,
        SnapshotInput(records=records, sources=list(manifest.sources)),
        snap_hashes,
        ports.clock,
    )
