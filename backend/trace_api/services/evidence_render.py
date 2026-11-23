"""What the proof view needs (FR-UI-2). The API never decodes an untrusted file: it serves PNGs the
build child pre-rendered (a miss is 404 `render-missing`) and reads plain rows from stored CSV and
Parquet. Pointers are the only input; no path ever comes from the request."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from trace_adapters.blob_fs import FsBlobStore
from trace_adapters.telemetry_parquet import ParquetTelemetryReader
from trace_api.settings import Settings
from trace_core.models.case import CaseVersion, EvidenceRender
from trace_core.models.claims import ClaimRecord
from trace_core.models.evidence import (
    ImageRegionPointer,
    SensorWindowPointer,
    TableCellPointer,
    TextSpanPointer,
)
from trace_core.normalise.time import hours_in
from trace_worker.render_paths import crop_path, oriented_path, page_png_path

ROW_CONTEXT = 25
"""Table windows show this many rows either side of the cited cell (FR-UI-2)."""
Row = dict[str, str | int | float | None]


def artifact_path(settings: Settings, claim: ClaimRecord, which: str) -> Path | None:
    """The cached PNG of a claim ('page' or 'crop'), or None when it was never rendered."""
    ev = claim.evidence
    path: Path | None = None
    if isinstance(ev, TextSpanPointer) and ev.page is not None and which == "page":
        path = page_png_path(settings.renders_dir, ev.sha256, ev.page)
    elif isinstance(ev, ImageRegionPointer):
        path = (
            oriented_path(settings.renders_dir, ev.sha256)
            if which == "page"
            else crop_path(settings.renders_dir, ev.sha256, ev.crop_sha256)
        )
    return path if path is not None and path.is_file() else None


def table_window(settings: Settings, ev: TableCellPointer) -> list[Row]:
    blobs = FsBlobStore(settings.blobs_dir)
    if not blobs.exists(ev.sha256):
        return []
    rows = list(csv.reader(io.StringIO(blobs.open(ev.sha256).read().decode("utf-8"))))
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    first = max(0, ev.row - ROW_CONTEXT)
    out: list[Row] = []
    for index in range(first, min(len(body), ev.row + ROW_CONTEXT + 1)):
        record: Row = {"row": index}
        record.update(
            {name: body[index][i] for i, name in enumerate(header) if i < len(body[index])}
        )
        out.append(record)
    return out


def sensor_window(settings: Settings, ev: SensorWindowPointer) -> list[Row]:
    reader = ParquetTelemetryReader(settings.derived_dir)
    series = ev.series_id.split("/")
    base = "/".join(series[:2])  # a gap pointer names `telemetry/<machine>/<channel>`
    data = reader.read(base, ev.start, ev.end).to_pydict()
    by_ts: dict[str, Row] = {}
    for i, ts in enumerate(data["ts"]):
        row = by_ts.setdefault(str(ts), {"ts": str(ts)})
        for channel in ev.channels:
            value = data.get(channel, [None] * (i + 1))[i]
            if value is not None:
                row[channel] = float(value)
    return [by_ts[h] for h in hours_in(ev.start, ev.end) if h in by_ts]


def render(
    settings: Settings, cid: str, version: CaseVersion, claim: ClaimRecord
) -> EvidenceRender:
    ev = claim.evidence
    if ev is None:
        raise LookupError("inferred claim without its own evidence")
    base = f"/api/v1/cases/{cid}/versions/{version.version}/claims/{claim.claim_id}/evidence"
    page = artifact_path(settings, claim, "page")
    crop = artifact_path(settings, claim, "crop")
    rows: list[Row] | None = None
    if isinstance(ev, TableCellPointer):
        rows = table_window(settings, ev)
    elif isinstance(ev, SensorWindowPointer):
        rows = sensor_window(settings, ev)
    wants_png = isinstance(ev, TextSpanPointer | ImageRegionPointer)
    cached = page is not None or crop is not None
    return EvidenceRender(
        claim_id=claim.claim_id,
        pointer=ev,
        render_status="cached" if cached or not wants_png else "missing",
        page_png=f"{base}/page.png" if page is not None else None,
        crop_png=f"{base}/crop.png" if crop is not None else None,
        window_rows=rows,
    )
