"""A-04: hidden-text guard (T-06). Named: test_white_text_pdf_zero_claims_one_review,
test_partial_hidden_span_held, test_covered_text_held,
test_visibility_fallback_labelled_lower_assurance."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas

from tests.factories import make_source, sha
from tests.unit.engine.test_gaps import CFG
from trace_adapters.blob_fs import FsBlobStore
from trace_adapters.fakes.cache import DictExtractionCache
from trace_adapters.fakes.clock import FixedClock
from trace_adapters.fakes.llm import FakeLlm, IdentityRedactor
from trace_adapters.fakes.ocr import FakeOcr
from trace_adapters.pdfium_reader import PdfiumReader
from trace_adapters.telemetry_parquet import ParquetTelemetryReader
from trace_core.models.records import Source
from trace_core.ports import EnginePorts
from trace_core.read.hidden_text import FALLBACK_NOTE
from trace_core.read.text import read_text
from trace_core.score.confidence import score_pre
from trace_core.stage_types import ReadResult

LINE = "ran normally on this shift"
Draw = Callable[[Canvas], None]


def _pdf(draw: Draw) -> bytes:
    buf = io.BytesIO()
    canvas = Canvas(buf, pagesize=(595.2756, 841.8898), pageCompression=0, invariant=1)
    draw(canvas)
    canvas.save()
    return buf.getvalue()


def _read(tmp_path: Path, draw: Draw) -> ReadResult:
    ports = EnginePorts(
        blobs=FsBlobStore(tmp_path / "blobs"),
        pdf=PdfiumReader(),
        ocr=FakeOcr(),
        telemetry=ParquetTelemetryReader(tmp_path / "derived"),
        cache=DictExtractionCache(),
        clock=FixedClock("2015-08-06T04:00:00Z"),
        llm=FakeLlm(),
        redactor=IdentityRedactor(),
    )
    src: Source = make_source(sha256=sha("hidden"))
    return read_text(src, _pdf(draw), CFG, ports)


def _visible(c: Canvas) -> None:
    c.setFont("Helvetica", 14)
    c.drawString(72, 700, f"Machine 21 {LINE}")


def _white(c: Canvas) -> None:
    c.setFillColorRGB(1, 1, 1)
    _visible(c)


def _partial(c: Canvas) -> None:
    c.setFont("Helvetica", 14)
    c.drawString(72, 700, "Machine 21 ")
    c.setFillColorRGB(1, 1, 1)
    c.drawString(72 + c.stringWidth("Machine 21 "), 700, "did NOT ")
    c.setFillColorRGB(0, 0, 0)
    c.drawString(72 + c.stringWidth("Machine 21 did NOT "), 700, LINE)


def _covered(c: Canvas) -> None:
    _visible(c)
    c.setFillColorRGB(0, 0, 0)
    c.rect(60, 690, 400, 30, stroke=0, fill=1)  # an opaque block drawn over the text


def _tiny(c: Canvas) -> None:
    c.setFont("Helvetica", 2)
    c.drawString(72, 700, f"Machine 21 {LINE}")


def test_visible_text_still_gives_a_claim(tmp_path: Path) -> None:
    result = _read(tmp_path, _visible)
    assert len(result.claims) == 1 and result.review_items == []
    assert result.claims[0].subject.entity_id == "machine:21"


@pytest.mark.parametrize("draw", [_white, _tiny], ids=["white_text", "font_below_4pt"])
def test_white_text_pdf_zero_claims_one_review(tmp_path: Path, draw: Draw) -> None:
    result = _read(tmp_path, draw)
    assert result.claims == []
    assert [i.type for i in result.review_items] == ["hidden_text"]


def test_partial_hidden_span_held(tmp_path: Path) -> None:
    """A visible phrase whose line contains an invisible negation is held, not read."""
    result = _read(tmp_path, _partial)
    assert result.claims == []
    assert [i.type for i in result.review_items] == ["hidden_text"]


def test_covered_text_held(tmp_path: Path) -> None:
    result = _read(tmp_path, _covered)
    assert result.claims == []
    assert [i.type for i in result.review_items] == ["hidden_text"]


def test_hidden_review_item_is_stable_and_keyed_by_mention(tmp_path: Path) -> None:
    one = _read(tmp_path / "a", _white).review_items
    two = _read(tmp_path / "b", _white).review_items
    assert one == two and one[0].mention_keys[0].locator.startswith("p1:")


def test_visibility_fallback_labelled_lower_assurance(tmp_path: Path) -> None:
    (claim,) = _read(tmp_path, _visible).claims
    assert claim.confidence.components["visibility_fallback"] == 1.0
    (scored,) = score_pre([claim], CFG)
    assert scored.confidence.components["visibility_fallback"] == 1.0
    assert FALLBACK_NOTE in (scored.confidence.note or "")
