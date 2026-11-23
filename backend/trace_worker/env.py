"""Build identity (A.3): engine_sha, lockfile hash, build_key. No decoder is imported here, so
`trace_api` may use it (the API computes the build key; only the child decodes files)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path

import trace_core
from trace_core.canonical import CANON_VERSION, canonical_sha256
from trace_core.ids import config_hash
from trace_core.models.case import Manifest
from trace_core.models.config import ConfigBundle
from trace_core.stage_types import SnapshotHashes

_BACKEND = Path(__file__).resolve().parents[1]
UNLOCKED = "0" * 64


def engine_sha() -> str:
    """sha256 over the bytes of every trace_core module (path-sorted): ties a version to code."""
    root = Path(trace_core.__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def lockfile_hash() -> str:
    lock = _BACKEND / "uv.lock"
    return hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else UNLOCKED


def build_key(manifest: Manifest, config: ConfigBundle, decision_ids: Sequence[str] = ()) -> str:
    """sha256(source shas || config_hash || decision ids || engine_sha || lockfile)."""
    return canonical_sha256(
        {
            "sources": sorted(s.sha256 for s in manifest.sources),
            "config_hash": config_hash(config),
            "decisions": sorted(decision_ids),
            "engine_sha": engine_sha(),
            "lockfile_hash": lockfile_hash(),
        }
    )


def snapshot_hashes(config: ConfigBundle, pdfium_version: str) -> SnapshotHashes:
    return SnapshotHashes(
        config_hash=config_hash(config),
        engine_sha=engine_sha(),
        lockfile_hash=lockfile_hash(),
        canon_version=CANON_VERSION,
        tesseract_version="none",  # P0 build: no OCR runs (image reading is M3)
        traineddata_sha="none",
        pdfium_version=pdfium_version,
        tzdata_version=metadata.version("tzdata"),
    )
