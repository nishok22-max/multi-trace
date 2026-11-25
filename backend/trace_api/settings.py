"""Runtime settings, read from the environment at call time (so tests can monkeypatch).

`TRACE_DEV_AUTH=1` enables the fixed local "viewer" principal used before real auth (A-09, M3).
It defaults to OFF: with it off every case route answers 401.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUILD_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    dev_auth: bool
    build_timeout_s: int = BUILD_TIMEOUT_SECONDS

    @property
    def db_path(self) -> Path:
        return self.data_dir / "trace.db"

    @property
    def blobs_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def derived_dir(self) -> Path:
        return self.data_dir / "derived"

    @property
    def renders_dir(self) -> Path:
        return self.data_dir / "renders"

    @property
    def anchors_path(self) -> Path:
        override = os.environ.get("TRACE_ANCHORS")
        return Path(override) if override else REPO / "anchors" / "demo_roots.txt"


def load_settings() -> Settings:
    data_dir = os.environ.get("TRACE_DATA_DIR")
    return Settings(
        data_dir=Path(data_dir) if data_dir else REPO / "data",
        dev_auth=os.environ.get("TRACE_DEV_AUTH") == "1",
    )


LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def in_container() -> bool:
    """True only inside a container that asked for it: `TRACE_CONTAINER=1` AND the runtime's
    marker file. A plain `TRACE_CONTAINER=1` on a laptop does not widen the bind."""
    return os.environ.get("TRACE_CONTAINER") == "1" and Path("/.dockerenv").exists()


def assert_safe_bind(host: str, tls: bool) -> None:
    """Non-loopback binding (LAN) is refused unless TLS is configured (S1). Inside the container
    the process listens on all interfaces because docker-compose publishes the port on 127.0.0.1
    only (tests/unit/test_container.py checks that)."""
    if host not in LOOPBACK and not tls and not in_container():
        raise RuntimeError("refusing to listen beyond loopback without TLS")
