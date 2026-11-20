"""MemBlobStore: content-addressed bytes in memory."""

from __future__ import annotations

import hashlib
import io
from typing import BinaryIO

from trace_core.errors import PayloadTooLarge
from trace_core.models.evidence import BlobRef

_CHUNK = 64 * 1024


class MemBlobStore:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put(self, stream: BinaryIO, *, max_bytes: int) -> BlobRef:
        digest = hashlib.sha256()
        buf = bytearray()
        while chunk := stream.read(_CHUNK):
            buf += chunk
            if len(buf) > max_bytes:
                raise PayloadTooLarge("stream exceeds max_bytes")
            digest.update(chunk)
        sha = digest.hexdigest()
        self._blobs.setdefault(sha, bytes(buf))  # existing hash is a no-op
        return BlobRef(sha256=sha, size=len(buf))

    def open(self, sha: str) -> BinaryIO:
        return io.BytesIO(self._blobs[sha])

    def exists(self, sha: str) -> bool:
        return sha in self._blobs
