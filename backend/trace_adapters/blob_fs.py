"""FsBlobStore: content-addressed bytes on disk. Hash-only paths (no user-supplied names)."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from trace_core.errors import PayloadTooLarge
from trace_core.models.evidence import BlobRef

_CHUNK = 64 * 1024


class FsBlobStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, sha: str) -> Path:
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("not a sha256")
        return self._root / sha[:2] / sha

    def put(self, stream: BinaryIO, *, max_bytes: int) -> BlobRef:
        digest = hashlib.sha256()
        size = 0
        fd, tmp_name = tempfile.mkstemp(dir=self._root)
        try:
            with os.fdopen(fd, "wb") as tmp:
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise PayloadTooLarge("stream exceeds max_bytes")
                    digest.update(chunk)
                    tmp.write(chunk)
            sha = digest.hexdigest()
            target = self._path(sha)
            if not target.exists():  # an existing hash is a no-op
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp_name, target)
        finally:
            if Path(tmp_name).exists():
                Path(tmp_name).unlink()
        return BlobRef(sha256=sha, size=size)

    def open(self, sha: str) -> BinaryIO:
        return self._path(sha).open("rb")

    def exists(self, sha: str) -> bool:
        return self._path(sha).is_file()
