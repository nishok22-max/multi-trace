"""Pre-render the pages and crops that claims cite (A-02, SYSTEM_DESIGN 14.2).

The API never decodes an untrusted file, so every PNG the proof view shows is made here, in the
build child, and served from cache only (a miss is `render-missing`). Layout under `renders/`:

  <source sha256>/p<N>.png        server-rendered page (150 dpi, annotations drawn)
  <source sha256>/p<N>.txt        the page text artifact the claim's offsets index into
  <oriented sha256>/oriented.png  EXIF-oriented, metadata-stripped photo
  <oriented sha256>/crop.png      the pixels inside the cited bbox (named by the crop hash)
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image

from trace_adapters.image_prep import PillowImagePrep
from trace_adapters.pdfium_reader import PdfiumReader
from trace_core.models.case import CaseVersion
from trace_core.models.evidence import ImageRegionPointer, TextSpanPointer
from trace_core.ports import BlobStore
from trace_worker.render_paths import crop_path, oriented_path, page_png_path, page_text_path

DPI = 150


def _write(path: Path, data: bytes) -> None:
    if path.is_file():
        return  # content-addressed: an existing artifact is the same artifact
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _crop_png(png: bytes, x: float, y: float, w: float, h: float) -> bytes:
    with Image.open(io.BytesIO(png)) as img:
        box = (int(x), int(y), int(x + w + 0.999), int(y + h + 0.999))
        out = io.BytesIO()
        img.convert("RGB").crop(box).save(out, format="PNG", compress_level=1)
        return out.getvalue()


def prerender(version: CaseVersion, blobs: BlobStore, renders: Path) -> int:
    """Render what the version's claims cite. Returns the number of artifacts written."""
    reader = PdfiumReader()
    prep = PillowImagePrep()
    sources = {s.source_id: s for s in version.views.state.sources}
    written = 0
    for claim in version.records.claims:
        ev = claim.evidence
        if isinstance(ev, TextSpanPointer) and ev.page is not None:
            target = page_png_path(renders, ev.sha256, ev.page)
            if target.is_file() or not blobs.exists(ev.sha256):
                continue
            blob = blobs.open(ev.sha256).read()
            _write(target, reader.render_png(blob, ev.page - 1, DPI).png)
            text = reader.page_text(blob, ev.page - 1).text
            _write(page_text_path(renders, ev.sha256, ev.page), text.encode("utf-8"))
            written += 2
        elif isinstance(ev, ImageRegionPointer):
            src = sources.get(ev.source_id)
            if src is None or not blobs.exists(src.sha256):
                continue
            oriented = prep.orient(blobs.open(src.sha256).read())
            if hashlib.sha256(oriented).hexdigest() != ev.sha256:
                continue  # the artifact would not match the pointer: never serve a wrong image
            _write(oriented_path(renders, ev.sha256), oriented)
            _write(
                crop_path(renders, ev.sha256, ev.crop_sha256),
                _crop_png(oriented, ev.bbox.x, ev.bbox.y, ev.bbox.w, ev.bbox.h),
            )
            written += 2
    return written
