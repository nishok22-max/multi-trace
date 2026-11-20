"""PdfiumReader: implements PdfReader on pypdfium2 (IMPLEMENTATION_PLAN D.2, ADR-06).

Child-only adapter: `trace_api` must never import this module (import-linter contract
"trace_api never decodes untrusted files"). Rendering and decoding happen in the build child.

Design (D.2):
- our own char loop over FPDFText_CountChars / FPDFText_GetUnicode; UTF-16 surrogate pairs
  are joined (two PDFium indices -> one text offset); generated chars are kept and flagged;
  no NFC here (a normalised view with an offset map belongs to the rules layer);
- `page_text_sha256` = sha256 of the UTF-8 bytes of `text`;
- boxes: tight (`loose=False`) for geometry, loose for the size rule; generated and
  zero-area tight boxes are None;
- capability probe: this PDFium build (126.0.6462.0) has no FPDFText_GetTextObject, so text
  objects are unavailable. `text_object_ids` is -1 everywhere and `render_mode` / `fill_alpha`
  are None; the visibility check must use the lower-assurance per-char crop fallback;
- render: 150 dpi, pixel cap (40 M px) checked from the CropBox BEFORE rendering,
  grey from `to_numpy()`, PNG at compress_level=1.
"""

from __future__ import annotations

import hashlib
import io
import math

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from numpy.typing import NDArray

from trace_core.errors import CapabilityMissing, RenderRefused
from trace_core.models.evidence import PageText, Rect, RectPx
from trace_core.ports import RenderResult

TEXT_CANON_VERSION = "1"
MAX_RENDER_PIXELS = 40_000_000
_LOOSE_MIN_HEIGHT_PT = 4.0
_REPLACEMENT = "�"


def _capabilities() -> frozenset[str]:
    caps = {"char_loop", "tight_boxes", "loose_boxes", "font_size"}
    for name, raw_name in (
        ("generated_flag", "FPDFText_IsGenerated"),
        ("text_object", "FPDFText_GetTextObject"),
        ("render_mode", "FPDFTextObj_GetTextRenderMode"),
        ("fill_color", "FPDFText_GetFillColor"),
        ("remove_object", "FPDFPage_RemoveObject"),
    ):
        if hasattr(pdfium_c, raw_name):
            caps.add(name)
    if "text_object" not in caps:
        caps.discard("render_mode")  # a render mode needs a text object to ask about
        caps.discard("remove_object")  # object removal needs to know which object to remove
    return frozenset(caps)


def _rect(box: tuple[float, float, float, float]) -> Rect:
    left, bottom, right, top = box
    return Rect(x=left, y=bottom, w=right - left, h=top - bottom)


def _grey(rgb_or_bgr: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Integer luma from a 3-channel (BGR) array: (29 B + 150 G + 77 R) / 256."""
    arr = rgb_or_bgr.astype(np.uint16)
    out = (29 * arr[..., 0] + 150 * arr[..., 1] + 77 * arr[..., 2]) >> 8
    return out.astype(np.uint8)


class PdfiumReader:
    """Stateless: every call opens and closes its own document."""

    def __init__(self) -> None:
        self.capabilities = _capabilities()

    @staticmethod
    def binary_version() -> str:
        """Goes into the extraction-cache key and the manifest."""
        return f"pypdfium2 {pdfium.version.PYPDFIUM_INFO} / PDFium {pdfium.version.PDFIUM_INFO}"

    # ------------------------------------------------------------------------ counts
    def page_count(self, pdf: bytes) -> int:
        doc = pdfium.PdfDocument(pdf)
        try:
            return len(doc)
        finally:
            doc.close()

    @staticmethod
    def _check_page(doc: pdfium.PdfDocument, page: int) -> None:
        if not 0 <= page < len(doc):
            raise IndexError("page index out of range")

    # -------------------------------------------------------------------------- text
    def page_text(self, pdf: bytes, page: int) -> PageText:
        doc = pdfium.PdfDocument(pdf)
        try:
            self._check_page(doc, page)
            pg = doc[page]
            tp = pg.get_textpage()
            try:
                return self._extract(pg, tp)
            finally:
                tp.close()
                pg.close()
        finally:
            doc.close()

    def _extract(self, pg: pdfium.PdfPage, tp: pdfium.PdfTextPage) -> PageText:
        count = tp.count_chars()
        raw_tp = tp.raw
        units = [int(pdfium_c.FPDFText_GetUnicode(raw_tp, i)) for i in range(count)]

        chars: list[str] = []
        char_to_offset: list[int] = []
        boxes: list[Rect | None] = []
        loose: list[Rect | None] = []
        sizes: list[float] = []
        generated: list[bool] = []

        i = 0
        while i < count:
            unit = units[i]
            span = 1
            if 0xD800 <= unit <= 0xDBFF and i + 1 < count and 0xDC00 <= units[i + 1] <= 0xDFFF:
                cp = 0x10000 + ((unit - 0xD800) << 10) + (units[i + 1] - 0xDC00)
                ch = chr(cp)
                span = 2
            elif unit == 0 or 0xD800 <= unit <= 0xDFFF:
                ch = _REPLACEMENT  # unmapped or lone surrogate: never raises, never guesses
            else:
                ch = chr(unit)
            offset = len(chars)
            for _ in range(span):
                char_to_offset.append(offset)
            is_generated = bool(pdfium_c.FPDFText_IsGenerated(raw_tp, i))
            chars.append(ch)
            generated.append(is_generated)
            sizes.append(float(pdfium_c.FPDFText_GetFontSize(raw_tp, i)))
            if is_generated:
                boxes.append(None)
                loose.append(None)
            else:
                tight = _rect(tp.get_charbox(i, loose=False))
                boxes.append(None if tight.w <= 0 or tight.h <= 0 else tight)
                loose.append(_rect(tp.get_charbox(i, loose=True)))
            i += span

        text = "".join(chars)
        return PageText(
            text=text,
            page_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            text_canon_version=TEXT_CANON_VERSION,
            char_to_offset=char_to_offset,
            char_boxes_pt=boxes,
            loose_boxes_pt=loose,
            font_sizes=sizes,
            generated=generated,
            text_object_ids=[-1] * len(chars),  # no text-object API in this build
            render_mode=None,
            fill_alpha=None,
            capabilities=self.capabilities,
            cropbox=_rect(pg.get_cropbox()),
            rotation=pg.get_rotation() % 360,
        )

    # ------------------------------------------------------------------------ render
    def render_png(
        self,
        pdf: bytes,
        page: int,
        dpi: int = 150,
        *,
        without_objects: frozenset[int] = frozenset(),
    ) -> RenderResult:
        if without_objects:
            raise CapabilityMissing("this PDFium build has no text-object API")
        doc = pdfium.PdfDocument(pdf)
        try:
            self._check_page(doc, page)
            pg = doc[page]
            try:
                scale = dpi / 72.0
                self._check_pixel_cap(pg, scale)  # BEFORE any pixel is allocated
                bitmap = pg.render(scale=scale)
                arr = bitmap.to_numpy()
                gray = _grey(arr)
                buf = io.BytesIO()
                bitmap.to_pil().save(buf, format="PNG", compress_level=1)
                return RenderResult(png=buf.getvalue(), gray=gray)
            finally:
                pg.close()
        finally:
            doc.close()

    @staticmethod
    def _check_pixel_cap(pg: pdfium.PdfPage, scale: float) -> None:
        crop = _rect(pg.get_cropbox())
        width, height = pg.get_size()
        w = max(crop.w, float(width))
        h = max(crop.h, float(height))
        pixels = math.ceil(w * scale) * math.ceil(h * scale)
        if pixels > MAX_RENDER_PIXELS:
            raise RenderRefused("page render exceeds the pixel cap")

    # ---------------------------------------------------------------------- geometry
    def pt_to_px(self, meta: PageText, rect: Rect, dpi: int) -> RectPx:
        """PDF points (origin bottom-left, y up) -> pixels (origin top-left), rounded outward.
        Rotation other than 0 is `unsupported_page` upstream, so it is refused here."""
        if meta.rotation != 0:
            raise CapabilityMissing("rotated pages are unsupported (P1-10)")
        s = dpi / 72.0
        crop = meta.cropbox
        x0 = (rect.x - crop.x) * s
        x1 = (rect.x + rect.w - crop.x) * s
        y0 = (crop.y + crop.h - (rect.y + rect.h)) * s
        y1 = (crop.y + crop.h - rect.y) * s
        left, top = math.floor(x0), math.floor(y0)
        return RectPx(x=left, y=top, w=math.ceil(x1) - left, h=math.ceil(y1) - top)
