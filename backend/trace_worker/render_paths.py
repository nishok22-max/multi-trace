"""Where pre-rendered artifacts live (pure paths: no decoder is imported, so `trace_api` may use
this module to SERVE what the build child rendered, but never to render)."""

from __future__ import annotations

from pathlib import Path


def page_png_path(renders: Path, source_sha: str, page: int) -> Path:
    return renders / source_sha / f"p{page}.png"


def page_text_path(renders: Path, source_sha: str, page: int) -> Path:
    return renders / source_sha / f"p{page}.txt"


def oriented_path(renders: Path, oriented_sha: str) -> Path:
    return renders / oriented_sha / "oriented.png"


def crop_path(renders: Path, oriented_sha: str, crop_sha: str) -> Path:
    return renders / oriented_sha / f"crop_{crop_sha}.png"
