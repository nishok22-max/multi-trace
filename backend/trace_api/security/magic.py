"""Upload classification (A-07, HARDENING S2): a magic-byte allowlist, never the client's word.

Allowed: PDF, PNG, JPEG, CSV, TXT, MD. No SVG, TIFF, XLSX, HTML or archives in the MVP. The file
extension must agree with the sniffed content (a PDF named `.csv`, or HTML named `.txt`, is
refused). Pixel counts are read from the PNG/JPEG headers without decoding (the API never decodes
untrusted files); an image above the render cap is refused.
Storage is hash-only, so the client's file name is only ever a sanitised display label.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

MAX_IMAGE_PIXELS = 40_000_000
"""Same cap as the PDF render path (PdfiumReader.MAX_RENDER_PIXELS)."""
_MAX_NAME = 128
_PNG = b"\x89PNG\r\n\x1a\n"
_TEXT_EXT = {".csv": "csv", ".txt": "txt", ".md": "md"}
_BINARY_EXT = {".pdf": "pdf", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}
_MIME = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "csv": "text/csv",
    "txt": "text/plain",
    "md": "text/markdown",
}
_MARKUP = re.compile(
    rb"^\s*(<\?xml|<!doctype|<html|<svg|<script|<head|<body|<iframe)", re.IGNORECASE
)


class UnsupportedMedia(Exception):
    """Refused upload. `reason` is a constant phrase (never file content)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Detected:
    kind: str
    mime: str
    display_name: str


def safe_display_name(name: str) -> str:
    """Basename only, control characters and path separators removed, length-capped. Never used
    as a path: blobs are stored under their hash."""
    base = re.split(r"[\\/]", name.replace("\x00", ""))[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable()).strip(" .")
    if not cleaned:
        raise UnsupportedMedia("empty file name")
    return cleaned[:_MAX_NAME]


def _extension(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot != -1 else ""


def _png_pixels(data: bytes) -> int:
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise UnsupportedMedia("malformed PNG")
    width, height = struct.unpack(">II", data[16:24])
    return int(width) * int(height)


def _jpeg_pixels(data: bytes) -> int:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return int(width) * int(height)
        i += 2 + length
    raise UnsupportedMedia("malformed JPEG")


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(_PNG):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None


def classify(name: str, data: bytes) -> Detected:
    """Classify the leading bytes of an upload (the whole file for text; text is also checked
    for NUL bytes and markup in the part given). Raises `UnsupportedMedia`."""
    display = safe_display_name(name)
    ext = _extension(display)
    sniffed = _sniff(data)
    if sniffed is None:
        if data[:4] in (b"PK\x03\x04", b"II*\x00", b"MM\x00*") or data[:2] == b"\x1f\x8b":
            raise UnsupportedMedia("archive, TIFF or spreadsheet formats are not accepted")
        if b"\x00" in data or _MARKUP.match(data):
            raise UnsupportedMedia("not plain text")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            if len(data) < 4096:
                raise UnsupportedMedia("not UTF-8 text") from None
            # a long prefix may end inside a multi-byte character: re-check without the tail
            try:
                data[:-4].decode("utf-8")
            except UnicodeDecodeError:
                raise UnsupportedMedia("not UTF-8 text") from None
        kind = _TEXT_EXT.get(ext)
        if kind is None:
            raise UnsupportedMedia("extension does not match a text file")
        return Detected(kind, _MIME[kind], display)
    if _BINARY_EXT.get(ext) != sniffed:
        raise UnsupportedMedia("extension does not match the file content")
    if sniffed in ("png", "jpeg"):
        pixels = _png_pixels(data) if sniffed == "png" else _jpeg_pixels(data)
        if pixels > MAX_IMAGE_PIXELS:
            raise UnsupportedMedia("image exceeds the pixel cap")
    return Detected(sniffed, _MIME[sniffed], display)
