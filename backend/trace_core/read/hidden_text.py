"""Hidden-text guard (A-04, HARDENING T-06): a span with any invisible non-whitespace character
produces no claim; it opens one `hidden_text` review item instead.

This PDFium build has no text-object API (see PdfiumReader), so render mode and fill alpha are
unavailable. Visibility is therefore checked with the lower-assurance per-character fallback:

- size rule: font size below `MIN_FONT_PT` (4 pt);
- CropBox rule: the character box does not intersect the page CropBox;
- box rule: a non-generated character with no tight box (zero area);
- pixel rule: the rendered grey crop of the character's tight box has a standard deviation below
  `MIN_PIXEL_STD` (8): white-on-white, fully transparent, or covered by another object.

Anything that cannot be checked (rotated page, empty crop) is held: fail closed. The rules are
pure; the caller supplies the crop function (it owns the page render).
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from trace_core.errors import CapabilityMissing
from trace_core.models.evidence import PageText, Rect

MIN_FONT_PT = 4.0
MIN_PIXEL_STD = 8.0
RENDER_DPI = 150

CropFn = Callable[[Rect], NDArray[np.uint8] | None]
"""Grey pixels of a rectangle in PDF points, or None when it lies outside the render."""

FALLBACK_NOTE = "visibility checked by the pixel fallback (lower assurance)"


def _intersects(a: Rect, b: Rect) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def _std(pixels: NDArray[np.uint8]) -> float:
    values = pixels.astype(np.float64).ravel()
    centre = float(values.sum()) / values.size
    return math.sqrt(float(((values - centre) ** 2).sum()) / values.size)


def hidden_reasons(page: PageText, start: int, end: int, crop: CropFn) -> list[str]:
    """Sorted distinct reasons why some non-whitespace character in `text[start:end]` is not
    visible; empty means every such character is visible."""
    reasons: set[str] = set()
    for i in range(max(0, start), min(end, len(page.text))):
        if page.text[i].isspace() or page.generated[i]:
            continue
        if page.font_sizes[i] < MIN_FONT_PT:
            reasons.add("font_below_4pt")
        box = page.char_boxes_pt[i]
        if box is None:
            reasons.add("zero_area_box")
            continue
        if not _intersects(box, page.cropbox):
            reasons.add("outside_cropbox")
            continue
        try:
            pixels = crop(box)
        except CapabilityMissing:
            reasons.add("visibility_unverifiable")
            continue
        if pixels is None or pixels.size == 0:
            reasons.add("visibility_unverifiable")
        elif _std(pixels) < MIN_PIXEL_STD:
            reasons.add("invisible_pixels")
    return sorted(reasons)
