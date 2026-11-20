"""PdfReader contract, run against the fake and the real pdfium adapter."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from tests.factories import make_page_text
from trace_adapters.fakes import FakePdfReader
from trace_adapters.pdfium_reader import PdfiumReader
from trace_core.models.evidence import Rect
from trace_core.ports import PdfReader

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "pdf" / "simple.pdf"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

FACTORIES: dict[str, Callable[[], PdfReader]] = {
    "fake": lambda: FakePdfReader([make_page_text()]),
    "pdfium": PdfiumReader,
}


@pytest.fixture(params=list(FACTORIES))
def reader(request: pytest.FixtureRequest) -> PdfReader:
    return FACTORIES[request.param]()


@pytest.fixture
def pdf() -> bytes:
    return FIXTURE.read_bytes()


def test_page_count(reader: PdfReader, pdf: bytes) -> None:
    assert reader.page_count(pdf) == 1


def test_page_text_is_self_consistent(reader: PdfReader, pdf: bytes) -> None:
    pt = reader.page_text(pdf, 0)
    assert pt.page_text_sha256 == hashlib.sha256(pt.text.encode("utf-8")).hexdigest()
    n = len(pt.text)
    assert n > 0
    assert len(pt.char_boxes_pt) == len(pt.loose_boxes_pt) == len(pt.font_sizes) == n
    assert len(pt.generated) == len(pt.text_object_ids) == n
    assert all(0 <= off < n for off in pt.char_to_offset)
    assert pt.char_to_offset == sorted(pt.char_to_offset)  # monotonic


def test_unknown_page_raises(reader: PdfReader, pdf: bytes) -> None:
    with pytest.raises(IndexError):
        reader.page_text(pdf, 5)
    with pytest.raises(IndexError):
        reader.render_png(pdf, 5)


def test_render_png_returns_png_and_2d_grey(reader: PdfReader, pdf: bytes) -> None:
    result = reader.render_png(pdf, 0)
    assert result.png.startswith(PNG_MAGIC)
    assert result.gray.ndim == 2 and result.gray.dtype == np.uint8


def test_pt_to_px_scales_by_dpi(reader: PdfReader, pdf: bytes) -> None:
    pt = reader.page_text(pdf, 0)
    rect = Rect(x=72.0, y=700.0, w=72.0, h=14.4)
    px150 = reader.pt_to_px(pt, rect, 150)
    px300 = reader.pt_to_px(pt, rect, 300)
    assert px150.w >= 150 and px150.h >= 30  # 72 pt = 150 px at 150 dpi, rounded outward
    assert abs(px300.w - 2 * px150.w) <= 2 and abs(px300.h - 2 * px150.h) <= 2
