"""FakePdfReader: serves pre-built PageText objects; renders a 1x1 grey PNG."""

from __future__ import annotations

import struct
import zlib

import numpy as np

from trace_core.models.evidence import PageText, Rect, RectPx
from trace_core.ports import RenderResult


def tiny_png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)  # 1x1, 8-bit greyscale
    raw = zlib.compress(b"\x00\xff", 1)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


class FakePdfReader:
    def __init__(self, pages: list[PageText]) -> None:
        self._pages = pages

    def page_count(self, pdf: bytes) -> int:
        return len(self._pages)

    def page_text(self, pdf: bytes, page: int) -> PageText:
        return self._pages[page]

    def render_png(
        self,
        pdf: bytes,
        page: int,
        dpi: int = 150,
        *,
        without_objects: frozenset[int] = frozenset(),
    ) -> RenderResult:
        _ = self._pages[page]  # IndexError for an unknown page, like a real reader
        return RenderResult(png=tiny_png(), gray=np.full((1, 1), 255, dtype=np.uint8))

    def pt_to_px(self, meta: PageText, rect: Rect, dpi: int) -> RectPx:
        s = dpi / 72.0
        return RectPx(
            x=round(rect.x * s), y=round(rect.y * s), w=round(rect.w * s), h=round(rect.h * s)
        )
