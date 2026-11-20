"""A-02 pypdfium2 checkpoint (IMPLEMENTATION_PLAN D.2): offsets, boxes, render round-trip."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from tests.fixtures.gen_pdf_fixtures import SIMPLE_FONT, SIMPLE_LINES
from trace_adapters.pdfium_reader import MAX_RENDER_PIXELS, PdfiumReader
from trace_core.errors import CapabilityMissing, RenderRefused
from trace_core.models.evidence import Rect, TextSpanPointer

PDF_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"
DPI = 150


@pytest.fixture(scope="module")
def reader() -> PdfiumReader:
    return PdfiumReader()


def _pdf(name: str) -> bytes:
    return (PDF_DIR / name).read_bytes()


def test_quote_equals_page_text_slice(reader: PdfiumReader) -> None:
    pt = reader.page_text(_pdf("simple.pdf"), 0)
    quote = "ran normally through both shifts"
    start = pt.text.index(quote)
    end = start + len(quote)
    pointer = TextSpanPointer(
        source_id="src-simple",
        sha256=hashlib.sha256(_pdf("simple.pdf")).hexdigest(),
        page=1,
        page_text_sha256=pt.page_text_sha256,
        text_canon_version=pt.text_canon_version,
        char_start=start,
        char_end=end,
        quote=pt.text[start:end],
        quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
    )
    assert pointer.quote == pt.text[pointer.char_start : pointer.char_end] == quote
    assert hashlib.sha256(pointer.quote.encode()).hexdigest() == pointer.quote_sha256
    # page_text_sha256 is the sha of the UTF-8 bytes of exactly this text, no NFC applied
    assert pt.page_text_sha256 == hashlib.sha256(pt.text.encode("utf-8")).hexdigest()
    assert pt.text_canon_version == "1"
    # the same call twice is byte-identical (determinism)
    assert reader.page_text(_pdf("simple.pdf"), 0) == pt


def test_generated_line_break_is_kept_and_flagged(reader: PdfiumReader) -> None:
    """PDFium inserts a generated CR LF between lines. It is part of the offsets, flagged, and
    has no box, so a quote may span it without shifting any later offset."""
    pt = reader.page_text(_pdf("simple.pdf"), 0)
    flagged = [i for i, g in enumerate(pt.generated) if g]
    assert flagged and all(pt.text[i] in "\r\n" for i in flagged)
    assert all(pt.char_boxes_pt[i] is None and pt.loose_boxes_pt[i] is None for i in flagged)
    first, second = SIMPLE_LINES[0][2], SIMPLE_LINES[1][2]
    start = pt.text.index(first)
    assert pt.text[start + len(first)] == "\r"  # the generated break sits right after line 1
    assert pt.text.index(second) == start + len(first) + 2


def test_surrogate_pair_offsets(reader: PdfiumReader) -> None:
    """One code point outside the BMP is two PDFium char indices but one text offset."""
    pt = reader.page_text(_pdf("surrogate.pdf"), 0)
    assert pt.text == "x\U0001f600y"
    assert len(pt.text) == 3
    assert pt.char_to_offset == [0, 1, 1, 2]  # indices 1 and 2 are one pair -> offset 1
    assert [len(pt.char_boxes_pt), len(pt.font_sizes), len(pt.generated)] == [3, 3, 3]
    assert pt.text[pt.char_to_offset[3]] == "y"
    assert pt.page_text_sha256 == hashlib.sha256(pt.text.encode("utf-8")).hexdigest()


def test_bbox_roundtrip_reportlab_fixture(reader: PdfiumReader) -> None:
    """pt box -> px box -> rendered pixels: ink is inside the box, and nothing is outside it."""
    pdf = _pdf("simple.pdf")
    pt = reader.page_text(pdf, 0)
    x, y, text = SIMPLE_LINES[0]
    quote = "Machine 21"
    start = pt.text.index(quote)
    boxes = [b for b in pt.char_boxes_pt[start : start + len(quote)] if b is not None]
    assert boxes
    left = min(b.x for b in boxes)
    bottom = min(b.y for b in boxes)
    right = max(b.x + b.w for b in boxes)
    top = max(b.y + b.h for b in boxes)
    # geometry from the generator: the string starts at x and sits on the baseline y
    assert left == pytest.approx(x, abs=2.0)  # tight box starts at the glyph's left bearing
    assert bottom == pytest.approx(y, abs=SIMPLE_FONT[1] * 0.25)  # descender-free letters
    assert top - bottom == pytest.approx(SIMPLE_FONT[1] * 0.72, abs=3.0)  # cap height ~0.72 em

    rect = Rect(x=left, y=bottom, w=right - left, h=top - bottom)
    px = reader.pt_to_px(pt, rect, DPI)
    gray = reader.render_png(pdf, 0, DPI).gray
    inside = gray[px.y : px.y + px.h, px.x : px.x + px.w]
    assert inside.size > 0 and int(inside.min()) < 100  # dark ink inside the box
    # an equally sized box 600 px to the right (on the page, past the text) is blank paper
    far = gray[px.y : px.y + px.h, px.x + 600 : px.x + 600 + px.w]
    assert far.size > 0 and int(far.min()) == 255
    assert np.count_nonzero(inside < 128) > 0


def test_pdf_huge_mediabox_render_refused(reader: PdfiumReader) -> None:
    pdf = _pdf("huge_mediabox.pdf")
    # text extraction still works on the huge page (no pixels involved)
    assert "tiny text" in reader.page_text(pdf, 0).text
    scale = DPI / 72.0
    assert (14400 * scale) ** 2 > MAX_RENDER_PIXELS  # the fixture really is over the cap
    with pytest.raises(RenderRefused):
        reader.render_png(pdf, 0, DPI)


def test_capability_probe_is_recorded_and_honest(reader: PdfiumReader) -> None:
    caps = reader.page_text(_pdf("simple.pdf"), 0).capabilities
    assert {"char_loop", "tight_boxes", "loose_boxes", "font_size", "generated_flag"} <= caps
    if "text_object" not in caps:  # this PDFium build has no FPDFText_GetTextObject
        pt = reader.page_text(_pdf("simple.pdf"), 0)
        assert set(pt.text_object_ids) == {-1} and pt.render_mode is None
        assert "render_mode" not in caps and "remove_object" not in caps
        with pytest.raises(CapabilityMissing):
            reader.render_png(_pdf("simple.pdf"), 0, DPI, without_objects=frozenset({0}))


def test_render_is_png_compress_level_1_and_grey_matches_page(reader: PdfiumReader) -> None:
    result = reader.render_png(_pdf("simple.pdf"), 0, DPI)
    assert result.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert result.gray.shape == (1754, 1241)  # A4 at 150 dpi
    assert result.gray.dtype == np.uint8 and int(result.gray.max()) == 255


def test_cropbox_and_rotation_are_reported(reader: PdfiumReader) -> None:
    pt = reader.page_text(_pdf("simple.pdf"), 0)
    assert pt.rotation == 0
    assert pt.cropbox.w == pytest.approx(595.2756, abs=0.01)
    assert pt.cropbox.h == pytest.approx(841.8898, abs=0.01)
    assert reader.binary_version().startswith("pypdfium2 4.")
