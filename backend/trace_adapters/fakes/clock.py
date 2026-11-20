"""FixedClock: tests use 2015-03-15T09:10:00Z unless they test the clock itself."""

from __future__ import annotations

from datetime import UTC, datetime

DEFAULT_NOW = "2015-03-15T09:10:00Z"


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(UTC)


class FixedClock:
    def __init__(self, iso: str = DEFAULT_NOW) -> None:
        self._now = _parse(iso)

    def now_utc(self) -> datetime:
        return self._now

    def set(self, iso: str) -> None:
        self._now = _parse(iso)
