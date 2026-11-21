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


def load_settings() -> Settings:
    data_dir = os.environ.get("TRACE_DATA_DIR")
    return Settings(
        data_dir=Path(data_dir) if data_dir else REPO / "data",
        dev_auth=os.environ.get("TRACE_DEV_AUTH") == "1",
    )
