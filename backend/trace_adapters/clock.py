"""SystemClock: the only place wall-clock time enters a build (core takes the Clock port)."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(UTC)
