"""A-06: the image reader. Named: test_decimal_drop_69_goes_to_review,
test_exif6_bbox_alignment_and_no_gps, plus reader disagreement and fail-closed paths."""

from __future__ import annotations

import hashlib
import io
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from tests.factories import make_source, sha
from tests.unit.engine.test_gaps import CFG
from trace_adapters.blob_fs import FsBlobStore
from trace_adapters.fakes.cache import DictExtractionCache
from trace_adapters.fakes.clock import FixedClock
from trace_adapters.fakes.llm import FakeLlm, IdentityRedactor
from trace_adapters.fakes.ocr import FakeOcr
from trace_adapters.image_prep import PillowImagePrep
from trace_adapters.pdfium_reader import PdfiumReader
from trace_adapters.telemetry_parquet import ParquetTelemetryReader
from trace_core.errors import RenderRefused
from trace_core.models.config import Gauge
from trace_core.models.evidence import ImageRegionPointer, OcrConfig, OcrResult, OcrWord, Rect
from trace_core.ports import EnginePorts
from trace_core.read.image import read_image

GAUGE = Gauge(gauge_id="G1", attribute="pressure", unit="bar", min_value=0.0, max_value=10.0)
CONFIG = CFG.model_copy(update={"gauges": [GAUGE]})
NUMBER_BOX = Rect(x=10, y=10, w=30, h=12)


def _result(number: str, unit: str = "bar") -> OcrResult:
    return OcrResult(
        words=[
            OcrWord(text=number, bbox=NUMBER_BOX, conf=90.0),
            OcrWord(text=unit, bbox=Rect(x=50, y=10, w=24, h=12), conf=88.0),
        ],
        text=f"{number} {unit}",
        engine_version="fake",
    )


class _Disagreeing(FakeOcr):
    def reread_region(self, png: bytes, bbox: Rect, cfg: OcrConfig) -> OcrResult:
        return OcrResult(words=[], text="4.7", engine_version="fake")


def _png(size: tuple[int, int] = (80, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _ports(tmp_path: Path, ocr: FakeOcr, prep: bool = True) -> EnginePorts:
    return EnginePorts(
        blobs=FsBlobStore(tmp_path / "b"),
        pdf=PdfiumReader(),
        ocr=ocr,
        telemetry=ParquetTelemetryReader(tmp_path / "d"),
        cache=DictExtractionCache(),
        clock=FixedClock("2015-08-06T04:00:00Z"),
        llm=FakeLlm(),
        redactor=IdentityRedactor(),
        image_prep=PillowImagePrep() if prep else None,
    )


def _read(tmp_path: Path, ocr: FakeOcr, prep: bool = True):  # type: ignore[no-untyped-def]
    src = make_source(modality="image", mime="image/png", sha256=sha("photo"))
    return read_image(src, _png(), CONFIG, _ports(tmp_path, ocr, prep))


def test_a_clean_reading_is_one_extracted_numeric_claim(tmp_path: Path) -> None:
    result = _read(tmp_path, FakeOcr(_result("4.2")))
    (claim,) = result.claims
    assert result.review_items == []
    assert claim.claim_type == "extracted" and claim.modality == "image"
    assert (claim.value, claim.unit, claim.unit_status) == (4.2, "bar", "known")
    ev = claim.evidence
    assert isinstance(ev, ImageRegionPointer)
    assert ev.read_text == ev.reread_text == "4.2" and ev.bbox == NUMBER_BOX
    assert ev.sha256 == hashlib.sha256(PillowImagePrep().orient(_png())).hexdigest()
    assert claim.subject.link_status == "unresolved"  # a photo names no machine: a reviewer decides


def test_decimal_drop_69_goes_to_review(tmp_path: Path) -> None:
    """OCR reads "69" on a 0-10 bar gauge: probably 6.9. It is held, never corrected."""
    result = _read(tmp_path, FakeOcr(_result("69")))
    assert result.claims == []
    (item,) = result.review_items
    assert item.type == "implausible_value" and item.claim_ids == []
    assert item.mention_keys[0].locator.startswith("img:")
    wild = _read(tmp_path, FakeOcr(_result("420")))
    assert [i.type for i in wild.review_items] == ["implausible_value"]  # out of range, not a drop


def test_a_second_read_that_disagrees_is_held(tmp_path: Path) -> None:
    result = _read(tmp_path, _Disagreeing(_result("4.2")))
    assert result.claims == [] and [i.type for i in result.review_items] == ["reader_disagreement"]


def test_unknown_unit_or_ambiguous_gauge_gives_no_reading(tmp_path: Path) -> None:
    assert _read(tmp_path, FakeOcr(_result("4.2", "furlongs"))).claims == []
    twin = CONFIG.model_copy(
        update={"gauges": [GAUGE, GAUGE.model_copy(update={"gauge_id": "G2"})]}
    )
    src = make_source(modality="image", mime="image/png", sha256=sha("photo"))
    ports = _ports(tmp_path, FakeOcr(_result("4.2")))
    assert read_image(src, _png(), twin, ports).claims == []  # two gauges share the unit: no guess


def test_without_an_image_decoder_the_reader_fails_closed(tmp_path: Path) -> None:
    result = _read(tmp_path, FakeOcr(_result("4.2")), prep=False)
    assert result.claims == [] and [i.type for i in result.review_items] == ["unsupported_page"]
    assert replace(_ports(tmp_path, FakeOcr()), image_prep=None).image_prep is None


def _exif6_jpeg() -> bytes:
    """A 60x40 stored image with EXIF orientation 6 (rotate 90 CW on display) and GPS data; a red
    marker sits at stored (5..15, 5..15), so after orientation it is at x in 25..35, y in 5..15."""
    img = Image.new("RGB", (60, 40), (255, 255, 255))
    for x in range(5, 15):
        for y in range(5, 15):
            img.putpixel((x, y), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (12.0, 58.0, 3.0), "E", (80.0, 14.0, 30.0)
    exif[0x8825] = gps
    exif[0x010F] = "SecretCam"  # Make
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif, quality=100, subsampling=0)
    return buf.getvalue()


def test_exif6_bbox_alignment_and_no_gps() -> None:
    raw = _exif6_jpeg()
    assert b"SecretCam" in raw and Image.open(io.BytesIO(raw)).getexif().get_ifd(0x8825)
    prep = PillowImagePrep()
    png = prep.orient(raw)
    with Image.open(io.BytesIO(png)) as out:
        assert out.size == (40, 60)  # rotated: width and height swap
        assert not out.getexif() and not out.info.get("exif")  # no EXIF, no GPS in the derived PNG
        red, green, blue = out.getpixel((30, 10))  # JPEG is lossy: near, not exact
        assert red > 240 and green < 20 and blue < 20  # the marker followed the rotation
        assert min(out.getpixel((5, 5))) > 240
    assert b"SecretCam" not in png and b"GPS" not in png and b"Exif" not in png
    # a bbox in oriented pixels crops exactly the marker, and the crop hash is recomputable
    marker = prep.crop_sha256(png, Rect(x=25.0, y=5.0, w=10.0, h=10.0))
    with Image.open(io.BytesIO(png)) as out:
        pixels = out.convert("RGB").crop((25, 5, 35, 15)).tobytes()
    assert marker == hashlib.sha256(b"10x10:" + pixels).hexdigest()  # independently recomputed
    assert prep.crop_sha256(png, Rect(x=0.0, y=0.0, w=10.0, h=10.0)) != marker


def test_an_oversized_image_is_refused_before_decoding() -> None:
    buf = io.BytesIO()
    Image.new("1", (8000, 6000)).save(buf, format="PNG")  # 48 Mpx, tiny on disk
    with pytest.raises(RenderRefused):
        PillowImagePrep().orient(buf.getvalue())
