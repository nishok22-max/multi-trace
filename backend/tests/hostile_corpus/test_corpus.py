"""A-10: the hostile corpus, 13 files generated deterministically (nothing hostile is committed).
Every file is refused at the API door (classify) or yields no claim plus a review item in the
build child. Named: test_hostile_corpus[...]. Markers: `make hostile` runs `-k hostile`."""

from __future__ import annotations

import io
import struct
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from tests.unit.api.test_upload_security import _jpeg, _png
from tests.unit.engine.test_hidden_text import _covered, _partial, _read, _tiny, _white
from trace_api.security.magic import UnsupportedMedia, classify
from trace_core.models.evidence import PageText
from trace_core.read import text as text_module

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n"


def _pdf_with_pages(n: int) -> bytes:
    buf = io.BytesIO()
    canvas = Canvas(buf, pagesize=(400, 200), pageCompression=0, invariant=1)
    for page in range(n):
        canvas.setFont("Helvetica", 12)
        canvas.drawString(20, 100, f"Machine 21 ran normally on page {page + 1}")
        canvas.showPage()
    canvas.save()
    return buf.getvalue()


def _bomb_png() -> bytes:
    """A 100000 x 100000 grey PNG header: a few hundred bytes that would decode to 10 GB."""

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    ihdr = struct.pack(">IIBBBBB", 100_000, 100_000, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def _exif_gps_jpeg() -> bytes:
    exif = Image.Exif()
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (12.0, 58.0, 3.0)
    exif[0x8825] = gps
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 200, 200)).save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


# name -> (file name, bytes): refused at the API door
DOOR: dict[str, tuple[str, Callable[[], bytes]]] = {
    "html_as_pdf": ("report.pdf", lambda: b"<html><script>alert(document.cookie)</script></html>"),
    "svg": ("diagram.svg", lambda: b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'),
    "traversal_name_binary": ("../../../etc/passwd.exe", lambda: b"MZ\x90\x00"),
    "bomb_png": ("bomb.png", _bomb_png),
    "png_60mpx_rejected": ("big.png", lambda: _png(8000, 7500)),
    "pdf_renamed_csv": ("data.csv", lambda: PDF),
    "html_renamed_txt": ("note.txt", lambda: b"<!DOCTYPE html><html><body>x</body></html>"),
}


@pytest.mark.parametrize("name", sorted(DOOR))
def test_hostile_corpus_door(name: str) -> None:
    file_name, make = DOOR[name]
    with pytest.raises(UnsupportedMedia):
        classify(file_name, make())


def test_hostile_corpus_traversal_name_with_a_valid_body_is_only_a_label() -> None:
    detected = classify("../../../tmp/evil.pdf", PDF)
    assert detected.display_name == "evil.pdf"  # stored under its hash, never under this name


def test_hostile_corpus_exif_gps_jpeg_is_accepted_and_stripped_later() -> None:
    raw = _exif_gps_jpeg()
    assert classify("photo.jpg", raw).kind == "jpeg"  # accepted at the door; stripped by the child
    assert classify("ok.jpg", _jpeg(100, 100)).kind == "jpeg"


# name -> drawing: accepted at the door, but yields 0 claims and exactly one review item
BUILD_CHILD = {
    "white_text": _white,
    "hidden_negation": _partial,
    "covered": _covered,
    "tiny": _tiny,
}


@pytest.mark.parametrize("name", sorted(BUILD_CHILD))
def test_hostile_corpus_hidden_text(tmp_path: Path, name: str) -> None:
    assert classify(f"{name}.pdf", _pdf_with_pages(1)).kind == "pdf"
    result = _read(tmp_path, BUILD_CHILD[name])
    assert result.claims == [] and [i.type for i in result.review_items] == ["hidden_text"]


def test_hostile_corpus_xss_text_is_data_never_markup(tmp_path: Path) -> None:
    payload = "<img src=x onerror=alert(1)>"

    def draw(c: Canvas) -> None:
        c.setFont("Helvetica", 14)
        c.drawString(72, 700, f"{payload} Machine 21 ran normally on this shift")

    result = _read(tmp_path, draw)
    (claim,) = result.claims
    # only the verified quote and the resolved mention reach a claim; markup never does
    assert "<" not in claim.statement and "onerror" not in claim.statement
    assert claim.statement.count("\n") == 0 and claim.claim_type == "extracted"


def test_hostile_corpus_pdf_51_pages(tmp_path: Path) -> None:
    from tests.factories import make_source, sha
    from tests.unit.engine.test_gaps import CFG
    from tests.unit.engine.test_hidden_text import _read as read_pdf_bytes  # noqa: F401
    from tests.unit.engine.test_image import _ports
    from trace_adapters.fakes.ocr import FakeOcr
    from trace_core.read.text import read_text

    ports = _ports(tmp_path, FakeOcr())
    src = make_source(sha256=sha("many"))
    over = read_text(src, _pdf_with_pages(text_module.MAX_PAGES + 1), CFG, ports)
    assert over.claims == [] and [i.type for i in over.review_items] == ["pdf_page_cap"]
    at_cap = read_text(src, _pdf_with_pages(text_module.MAX_PAGES), CFG, ports)
    assert [i.type for i in at_cap.review_items] == [] and at_cap.claims  # exactly 50 is fine


def test_hostile_corpus_huge_mediabox_is_held_not_rendered(tmp_path: Path) -> None:
    from tests.factories import make_source, sha
    from tests.unit.engine.test_gaps import CFG
    from tests.unit.engine.test_image import _ports
    from trace_adapters.fakes.ocr import FakeOcr
    from trace_core.read.text import read_text

    buf = io.BytesIO()
    canvas = Canvas(buf, pagesize=(14400, 14400), pageCompression=0, invariant=1)
    canvas.setFont("Helvetica", 12)
    canvas.drawString(72, 14000, "Machine 21 ran normally on this shift")
    canvas.save()
    result = read_text(
        make_source(sha256=sha("huge")), buf.getvalue(), CFG, _ports(tmp_path, FakeOcr())
    )
    assert result.claims == []  # the render was refused, so visibility is unverifiable: held
    assert [i.type for i in result.review_items] == ["hidden_text"]


def test_hostile_corpus_rotated_and_scanned_pages_are_review_items(tmp_path: Path) -> None:
    from tests.factories import make_source, sha
    from tests.unit.engine.test_gaps import CFG
    from tests.unit.engine.test_image import _ports
    from trace_adapters.fakes.ocr import FakeOcr
    from trace_core.read.text import read_text

    def blank(rotate: int) -> bytes:
        buf = io.BytesIO()
        c = Canvas(buf, pagesize=(200, 200), pageCompression=0, invariant=1)
        if rotate:
            c.setPageRotation(rotate)
        c.setFont("Helvetica", 12)
        if rotate:
            c.drawString(20, 100, "Machine 21 ran normally on this shift")
        c.showPage()
        c.save()
        return buf.getvalue()

    ports = _ports(tmp_path, FakeOcr())
    scanned = read_text(make_source(sha256=sha("blank")), blank(0), CFG, ports)
    assert scanned.claims == [] and [i.type for i in scanned.review_items] == ["no_text_layer"]
    rotated = read_text(make_source(sha256=sha("rot")), blank(90), CFG, ports)
    assert rotated.claims == [] and [i.type for i in rotated.review_items] == ["unsupported_page"]
    assert PageText is not None
