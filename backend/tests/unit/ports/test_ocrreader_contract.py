"""OcrReader contract (fake now; the Tesseract adapter joins in M3)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from trace_adapters.fakes import FakeOcr
from trace_core.models.evidence import OcrConfig, OcrResult, OcrWord, Rect
from trace_core.ports import OcrReader

RESULT = OcrResult(
    words=[
        OcrWord(text="4.2", bbox=Rect(x=10, y=10, w=20, h=10), conf=91.0),
        OcrWord(text="bar", bbox=Rect(x=40, y=10, w=20, h=10), conf=88.0),
        OcrWord(text="far", bbox=Rect(x=400, y=300, w=20, h=10), conf=70.0),
    ],
    text="4.2 bar far",
    engine_version="fake",
)
FACTORIES: dict[str, Callable[[], OcrReader]] = {"fake": lambda: FakeOcr(RESULT)}


@pytest.fixture(params=list(FACTORIES))
def ocr(request: pytest.FixtureRequest) -> OcrReader:
    return FACTORIES[request.param]()


def test_read_words(ocr: OcrReader) -> None:
    out = ocr.read_words(b"png", OcrConfig())
    assert [w.text for w in out.words] == ["4.2", "bar", "far"] and out.engine_version


def test_reread_region_returns_only_words_inside(ocr: OcrReader) -> None:
    out = ocr.reread_region(b"png", Rect(x=0, y=0, w=100, h=50), OcrConfig())
    assert [w.text for w in out.words] == ["4.2", "bar"]
    assert out.text == "4.2 bar"


def test_reread_empty_region(ocr: OcrReader) -> None:
    assert ocr.reread_region(b"png", Rect(x=900, y=900, w=5, h=5), OcrConfig()).words == []
