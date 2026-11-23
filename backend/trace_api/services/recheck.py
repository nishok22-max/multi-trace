"""Claim re-check (FR-UI-2 "re-checked just now"): re-hash the stored bytes and re-derive the
cited value from them. A mismatch is shown as "evidence changed"; nothing is ever repaired.

Per pointer kind:
- text_span: source bytes hash, page-text artifact hash, quote == page_text[start:end];
- table_cell: source bytes hash, the cited line's bytes hash, the cell re-parsed;
- sensor_window: Parquet partition hash and the window digest recomputed from the readings;
- image_region: source bytes hash and the oriented-image artifact hash.
An inferred claim passes only if every extracted ancestor passes.
Rate limit: 30 per minute per user (429 `rate-limited`).
"""

from __future__ import annotations

import csv
import hashlib
import io
import threading
import time
from collections import deque

from trace_adapters.blob_fs import FsBlobStore
from trace_adapters.telemetry_parquet import ParquetTelemetryReader
from trace_api.settings import Settings
from trace_core.canonical import canonical_sha256
from trace_core.models.case import CaseVersion, RecheckResult
from trace_core.models.claims import ClaimRecord
from trace_core.models.evidence import (
    ImageRegionPointer,
    SensorWindowPointer,
    TableCellPointer,
    TextSpanPointer,
)
from trace_core.read.sensor import RAW_STATISTIC, window_digest
from trace_worker.render_paths import oriented_path, page_text_path

LIMIT = 30
WINDOW_SECONDS = 60.0


class RateLimiter:
    """Sliding window per key. `clock` is injectable for tests."""

    def __init__(self, limit: int = LIMIT, window: float = WINDOW_SECONDS) -> None:
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        stamp = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and stamp - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(stamp)
            return True


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _stored(settings: Settings, sha: str) -> bytes | None:
    blobs = FsBlobStore(settings.blobs_dir)
    return blobs.open(sha).read() if blobs.exists(sha) else None


def _text(settings: Settings, ev: TextSpanPointer) -> RecheckResult:
    source = _stored(settings, ev.sha256)
    source_ok = source is not None and _sha(source) == ev.sha256
    artifact = (
        page_text_path(settings.renders_dir, ev.sha256, ev.page).read_bytes()
        if ev.page is not None
        and page_text_path(settings.renders_dir, ev.sha256, ev.page).is_file()
        else source  # a plain-text document is its own page text
    )
    artifact_ok = artifact is not None and _sha(artifact) == ev.page_text_sha256
    value_ok = False
    if artifact is not None:
        text = artifact.decode("utf-8", errors="replace")
        value_ok = text[ev.char_start : ev.char_end] == ev.quote
    input_ok = _sha(ev.quote.encode("utf-8")) == ev.quote_sha256
    return RecheckResult(
        match=source_ok and artifact_ok and input_ok and value_ok,
        source_sha_ok=source_ok,
        artifact_sha_ok=artifact_ok,
        input_sha_ok=input_ok,
        value_ok=value_ok,
    )


def _table(settings: Settings, ev: TableCellPointer) -> RecheckResult:
    source = _stored(settings, ev.sha256)
    source_ok = source is not None and _sha(source) == ev.sha256
    input_ok = value_ok = False
    if source is not None and ev.row_byte_offset <= len(source):
        line = source[ev.row_byte_offset :].split(b"\n", 1)[0].rstrip(b"\r")
        input_ok = _sha(line) == ev.row_sha256
        try:
            cells = next(csv.reader(io.StringIO(line.decode("utf-8"))))
            value_ok = ev.raw_value in cells
        except (UnicodeDecodeError, StopIteration):
            value_ok = False
    return RecheckResult(
        match=source_ok and input_ok and value_ok,
        source_sha_ok=source_ok,
        artifact_sha_ok=source_ok,
        input_sha_ok=input_ok,
        value_ok=value_ok,
    )


def _sensor(settings: Settings, claim: ClaimRecord, ev: SensorWindowPointer) -> RecheckResult:
    reader = ParquetTelemetryReader(settings.derived_dir)
    series = "/".join(ev.series_id.split("/")[:2])
    try:
        partition_ok = reader.partition_sha(series) == ev.partition_sha256
        data = reader.read(series, ev.start, ev.end).to_pydict()
    except FileNotFoundError:
        return RecheckResult(
            match=False,
            source_sha_ok=False,
            artifact_sha_ok=False,
            input_sha_ok=False,
            value_ok=False,
        )
    channel = ev.channels[0]
    seen: dict[str, set[float]] = {}
    for ts, value in zip(data["ts"], data.get(channel, []), strict=False):
        if value is not None:
            seen.setdefault(str(ts), set()).add(float(value))
    readings = {h: next(iter(v)) for h, v in sorted(seen.items()) if len(v) == 1}
    if ev.statistic == RAW_STATISTIC:
        digest_ok = window_digest(series, channel, ev.start, ev.end, readings) == ev.window_sha256
        value_ok = digest_ok and len(readings) == ev.n_points
    elif ev.statistic == "hourly_peak" and isinstance(claim.value, dict):
        reading = claim.value.get("reading")
        value_ok = readings.get(ev.start) == reading
        digest_ok = (
            canonical_sha256(
                {"series": ev.series_id, "channel": channel, "ts": ev.start, "reading": reading}
            )
            == ev.window_sha256
        )
    else:  # gap pointers hash their own coordinates; the partition hash is what can change
        digest_ok = value_ok = True
    return RecheckResult(
        match=partition_ok and digest_ok and value_ok,
        source_sha_ok=partition_ok,
        artifact_sha_ok=partition_ok,
        input_sha_ok=digest_ok,
        value_ok=value_ok,
    )


def _image(settings: Settings, ev: ImageRegionPointer, source_sha: str | None) -> RecheckResult:
    source = _stored(settings, source_sha) if source_sha else None
    source_ok = source is not None and _sha(source) == source_sha
    path = oriented_path(settings.renders_dir, ev.sha256)
    artifact_ok = path.is_file() and _sha(path.read_bytes()) == ev.sha256
    return RecheckResult(
        match=source_ok and artifact_ok,
        source_sha_ok=source_ok,
        artifact_sha_ok=artifact_ok,
        input_sha_ok=artifact_ok,
        value_ok=artifact_ok,
    )


def _one(settings: Settings, version: CaseVersion, claim: ClaimRecord) -> RecheckResult | None:
    ev = claim.evidence
    if isinstance(ev, TextSpanPointer):
        return _text(settings, ev)
    if isinstance(ev, TableCellPointer):
        return _table(settings, ev)
    if isinstance(ev, SensorWindowPointer):
        return _sensor(settings, claim, ev)
    if isinstance(ev, ImageRegionPointer):
        sources = {s.source_id: s.sha256 for s in version.views.state.sources}
        return _image(settings, ev, sources.get(ev.source_id))
    return None


def recheck(settings: Settings, version: CaseVersion, claim: ClaimRecord) -> RecheckResult:
    by_id = {c.claim_id: c for c in version.records.claims}
    pending, seen = [claim], set[str]()
    results: list[RecheckResult] = []
    while pending:
        current = pending.pop()
        if current.claim_id in seen:
            continue
        seen.add(current.claim_id)
        if current.claim_type == "extracted":
            got = _one(settings, version, current)
            if got is not None:
                results.append(got)
        else:
            if (
                isinstance(current.evidence, SensorWindowPointer)
                and current.method.rule_id
                and (current.method.rule_id.startswith("excursion."))
            ):
                got = _one(settings, version, current)
                if got is not None:
                    results.append(got)
            pending.extend(by_id[i] for i in current.derived_from if i in by_id)
    if not results:
        return RecheckResult(
            match=False,
            source_sha_ok=False,
            artifact_sha_ok=False,
            input_sha_ok=False,
            value_ok=False,
        )
    return RecheckResult(
        match=all(r.match for r in results),
        source_sha_ok=all(r.source_sha_ok for r in results),
        artifact_sha_ok=all(r.artifact_sha_ok for r in results),
        input_sha_ok=all(r.input_sha_ok for r in results),
        value_ok=all(r.value_ok for r in results),
    )
