"""Shared fixtures. Network is disabled globally via pytest-socket (see pyproject addopts)."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest
import pytest_socket
from hypothesis import HealthCheck, settings

from trace_eval.holdout import HOLDOUT_ENV, HOLDOUT_PATH_PART  # imported before the audit hook

# Hypothesis profiles (TEST_PLAN 1.3): precommit is derandomised; ci and nightly go deeper.
settings.register_profile(
    "precommit",
    max_examples=200,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile("ci", max_examples=1000, deadline=None)
settings.register_profile("nightly", max_examples=10000, deadline=None)
settings.load_profile("precommit")


@pytest.fixture
def loopback_only() -> Iterator[None]:
    """In-process ASGI test clients need an event-loop socketpair on Windows (loopback).
    Allow loopback hosts only for that test; every other host stays blocked (S10, T-40)."""
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(["127.0.0.1", "::1"], allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket(allow_unix_socket=True)
        pytest_socket.socket_allow_hosts([], allow_unix_socket=True)


# ------------------------------------------------------------------------------ holdout quarantine
# A holdout-marked test runs only under `make eval-holdout` (TRACE_HOLDOUT_RUN=1). Any other test
# that opens a path under seed/faults/holdout/ is stopped by an audit hook (TEST_PLAN 1.5).
_HOLDOUT_ALLOWED = False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get(HOLDOUT_ENV) == "1":
        return
    skip = pytest.mark.skip(reason="holdout tests run only under `make eval-holdout`")
    for item in items:
        if "holdout" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _holdout_scope(request: pytest.FixtureRequest) -> Iterator[None]:
    global _HOLDOUT_ALLOWED
    _HOLDOUT_ALLOWED = request.node.get_closest_marker("holdout") is not None
    try:
        yield
    finally:
        _HOLDOUT_ALLOWED = False


def _audit(event: str, args: tuple[object, ...]) -> None:
    if event != "open" or _HOLDOUT_ALLOWED or not args:
        return
    mode = args[1] if len(args) > 1 and isinstance(args[1], str) else "r"
    if any(flag in mode for flag in "wax+"):
        return  # only READING holdout data is forbidden (a test may create its own fixture)
    target = args[0]
    if isinstance(target, str | os.PathLike) and HOLDOUT_PATH_PART in os.fspath(target).replace(
        "\\", "/"
    ):
        raise PermissionError("a dev test may not open holdout data")


sys.addaudithook(_audit)
