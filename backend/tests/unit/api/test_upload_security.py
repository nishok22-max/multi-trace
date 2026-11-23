"""A-07: upload classification and streaming caps. Named: test_300mb_rejected_streaming,
test_chunked_upload_without_length_capped, test_upload_refused_when_disk_below_1gb,
test_hostile_corpus[html_as_pdf, svg, traversal_name, bomb_png, pdf_renamed_csv, html_renamed_txt,
png_60mpx_rejected]."""

from __future__ import annotations

import asyncio
import struct
import zlib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.types import Message

from trace_api.security.magic import UnsupportedMedia, classify, safe_display_name
from trace_api.security.upload_asgi import (
    DOCUMENT_CAP,
    SLACK,
    TELEMETRY_CAP,
    UploadCapMiddleware,
    ensure_free_space,
)

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n"


def _png(width: int, height: int) -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def _jpeg(width: int, height: int) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0\x00\x04\x00\x00" + sof + b"\xff\xd9"


@pytest.mark.parametrize(
    ("name", "data", "kind"),
    [
        ("report.pdf", PDF, "pdf"),
        ("photo.png", _png(100, 100), "png"),
        ("photo.JPG", _jpeg(100, 80), "jpeg"),
        ("log.csv", b'"datetime","machineID"\n2015-01-01 06:00:00,21\n', "csv"),
        ("note.txt", b"Machine 21 ran normally\n", "txt"),
        ("readme.md", b"# notes\n", "md"),
    ],
)
def test_allowlisted_types_are_accepted(name: str, data: bytes, kind: str) -> None:
    assert classify(name, data).kind == kind


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("html_as_pdf.pdf", b"<html><script>alert(1)</script></html>"),
        ("image.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'),
        ("image.png", b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
        ("pdf_renamed_csv.csv", PDF),
        ("html_renamed_txt.txt", b"<!DOCTYPE html><html><body>x</body></html>"),
        ("sheet.xlsx", b"PK\x03\x04" + b"\x00" * 30),
        ("scan.tif", b"II*\x00" + b"\x00" * 30),
        ("archive.zip", b"PK\x03\x04" + b"\x00" * 30),
        ("binary.txt", b"abc\x00def"),
        ("noext", b"just text"),
        ("png_60mpx_rejected.png", _png(8000, 7500)),
        ("huge.jpg", _jpeg(9000, 9000)),
        ("mismatch.png", PDF),
    ],
)
def test_hostile_corpus(name: str, data: bytes) -> None:
    with pytest.raises(UnsupportedMedia):
        classify(name, data)


def test_traversal_name_is_only_a_display_label() -> None:
    assert safe_display_name("../../etc/passwd") == "passwd"
    assert safe_display_name(r"..\..\windows\evil.pdf") == "evil.pdf"
    assert "\x00" not in safe_display_name("a\x00b.pdf")
    assert classify("../../x.pdf", PDF).display_name == "x.pdf"
    with pytest.raises(UnsupportedMedia):
        safe_display_name("../..")


def test_bomb_png_is_refused_from_its_header() -> None:
    with pytest.raises(UnsupportedMedia):
        classify("bomb.png", _png(65535, 65535))  # a few bytes on disk, gigapixels decoded


def test_disk_below_1gb_is_refused(tmp_path: Path) -> None:
    def usage(free: int) -> Callable[[Path], Any]:
        return lambda _: SimpleNamespace(free=free)

    assert not ensure_free_space(tmp_path, usage=usage(1024**3 - 1))
    assert ensure_free_space(tmp_path, usage=usage(1024**3))
    assert not ensure_free_space(tmp_path, needed=1, usage=usage(1024**3))


# ------------------------------------------------------------------------- ASGI middleware
class _Probe:
    """An app that reads the whole body, so a missing cap would pull every chunk."""

    def __init__(self) -> None:
        self.reached = False

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.reached = True
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


def _drive(
    path: str,
    chunks: int,
    chunk_size: int = SLACK,
    *,
    length: int | None = None,
    query: bytes = b"",
) -> tuple[list[Message], int, _Probe]:
    probe = _Probe()
    pulled = 0
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal pulled
        pulled += 1
        return {
            "type": "http.request",
            "body": b"x" * chunk_size,
            "more_body": pulled < chunks,
        }

    async def send(message: Message) -> None:
        sent.append(message)

    headers = [] if length is None else [(b"content-length", str(length).encode())]
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "query_string": query,
        "headers": headers,
    }
    asyncio.run(UploadCapMiddleware(probe)(scope, receive, send))
    return sent, pulled * chunk_size, probe


def test_300mb_rejected_streaming(loopback_only: None) -> None:
    """A declared 300 MB body is refused without reading a single byte."""
    sent, read, probe = _drive("/api/v1/cases/c1/sources", 1, length=300 * 1024 * 1024)
    assert sent[0]["status"] == 413 and read == 0 and not probe.reached
    assert dict(sent[0]["headers"])[b"content-type"] == b"application/problem+json"


def test_chunked_upload_without_length_capped(loopback_only: None) -> None:
    chunks = (300 * 1024 * 1024) // SLACK
    sent, read, _ = _drive("/api/v1/cases/c1/sources", chunks)
    assert sent[0]["status"] == 413
    assert read <= DOCUMENT_CAP + SLACK  # bytes read <= cap + one chunk


def test_telemetry_cap_is_larger_and_other_paths_are_untouched(loopback_only: None) -> None:
    sent, _, probe = _drive("/api/v1/cases/c1/sources", 600, query=b"kind=telemetry")
    assert sent[0]["status"] == 201 and probe.reached  # 37 MB is fine for telemetry
    chunks = (TELEMETRY_CAP + 2 * SLACK) // SLACK
    sent, read, _ = _drive("/api/v1/cases/c1/sources", chunks, query=b"kind=telemetry")
    assert sent[0]["status"] == 413 and read <= TELEMETRY_CAP + SLACK
    sent, _, probe = _drive("/api/v1/cases/c1/builds", 1000)
    assert sent[0]["status"] == 201 and probe.reached
