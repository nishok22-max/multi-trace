"""DictExtractionCache: write-once; a replay-mode miss is an error (never a skip)."""

from __future__ import annotations

import hashlib
from typing import Literal

from trace_core.errors import CacheModeError, CacheWriteOnceViolation, ReplayCacheMiss
from trace_core.models.evidence import CacheKey


class DictExtractionCache:
    def __init__(
        self,
        mode: Literal["record", "replay"] = "record",
        entries: dict[CacheKey, bytes] | None = None,
    ) -> None:
        self._mode: Literal["record", "replay"] = mode
        self._entries: dict[CacheKey, bytes] = dict(entries or {})

    @property
    def mode(self) -> Literal["record", "replay"]:
        return self._mode

    def get(self, key: CacheKey) -> bytes | None:
        hit = self._entries.get(key)
        if hit is None and self._mode == "replay":
            raise ReplayCacheMiss("no recorded artifact for this key")
        return hit

    def put(self, key: CacheKey, artifact: bytes) -> str:
        if self._mode == "replay":
            raise CacheModeError("cache is read-only in replay mode")
        existing = self._entries.get(key)
        if existing is not None and existing != artifact:
            raise CacheWriteOnceViolation("key already holds a different artifact")
        self._entries.setdefault(key, artifact)
        return hashlib.sha256(artifact).hexdigest()

    def replay_view(self) -> DictExtractionCache:
        """A read-only replay copy of what was recorded."""
        return DictExtractionCache("replay", self._entries)
