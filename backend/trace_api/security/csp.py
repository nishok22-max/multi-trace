"""Content-Security-Policy for the built frontend (C-09, S7). The inline script/style hashes
come from `dist/csp-hashes.json` (written by the frontend build), so no `unsafe-inline`."""

from __future__ import annotations

import json
from pathlib import Path

DOWNLOAD_CSP = "sandbox; default-src 'none'"


def build_csp(hashes: dict[str, list[str]]) -> str:
    scripts = " ".join(hashes.get("scripts", []))
    styles = " ".join(hashes.get("styles", []))
    return "; ".join(
        [
            "default-src 'none'",
            f"script-src 'self' {scripts}".strip(),
            f"style-src 'self' {styles}".strip(),
            "img-src 'self' data: blob:",
            "font-src 'self'",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "object-src 'none'",
        ]
    )


def load_csp(dist: Path) -> str:
    """Strict policy from the build's hash file. A missing file gives a hash-free policy (inline
    code simply does not run): fail closed."""
    path = dist / "csp-hashes.json"
    hashes = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return build_csp(hashes)
