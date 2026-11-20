"""FakeOcr: returns a canned OcrResult."""

from __future__ import annotations

from trace_core.models.evidence import OcrConfig, OcrResult, Rect


class FakeOcr:
    def __init__(self, result: OcrResult | None = None) -> None:
        self._result = result or OcrResult(words=[], text="", engine_version="fake")

    def read_words(self, png: bytes, cfg: OcrConfig) -> OcrResult:
        return self._result

    def reread_region(self, png: bytes, bbox: Rect, cfg: OcrConfig) -> OcrResult:
        inside = [
            w
            for w in self._result.words
            if bbox.x <= w.bbox.x
            and bbox.y <= w.bbox.y
            and w.bbox.x + w.bbox.w <= bbox.x + bbox.w
            and w.bbox.y + w.bbox.h <= bbox.y + bbox.h
        ]
        return OcrResult(
            words=inside,
            text=" ".join(w.text for w in inside),
            engine_version=self._result.engine_version,
            traineddata_sha=self._result.traineddata_sha,
        )
