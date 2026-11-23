"""PillowImagePrep: EXIF orientation, metadata stripping and crop hashing (A-06, S2/S3).

Child-only adapter (`trace_api` must never import PIL). A photo is rendered into a CLEAN image
(pixels only), so no EXIF, GPS or text chunk survives in the derived PNG. The pixel cap is checked
from the header before any pixel is decoded.
"""

from __future__ import annotations

import hashlib
import io
import math

from PIL import Image, ImageOps

from trace_core.errors import RenderRefused
from trace_core.models.evidence import Rect

MAX_PIXELS = 40_000_000


class PillowImagePrep:
    def orient(self, blob: bytes) -> bytes:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with Image.open(io.BytesIO(blob)) as img:
            width, height = img.size  # header only
            if width * height > MAX_PIXELS:
                raise RenderRefused("image exceeds the pixel cap")
            oriented = ImageOps.exif_transpose(img)
            rgb = oriented.convert("RGB")
        clean = Image.new("RGB", rgb.size)
        clean.paste(rgb)  # pixels only: no info dict, no EXIF, no GPS
        out = io.BytesIO()
        clean.save(out, format="PNG", compress_level=1)
        return out.getvalue()

    def crop_sha256(self, png: bytes, bbox: Rect) -> str:
        with Image.open(io.BytesIO(png)) as img:
            left, top = math.floor(bbox.x), math.floor(bbox.y)
            right, bottom = math.ceil(bbox.x + bbox.w), math.ceil(bbox.y + bbox.h)
            crop = img.convert("RGB").crop((left, top, right, bottom))
        header = f"{crop.width}x{crop.height}:".encode()
        return hashlib.sha256(header + crop.tobytes()).hexdigest()
