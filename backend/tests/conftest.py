"""Shared fixtures. Network is disabled globally via pytest-socket (see pyproject addopts)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import pytest_socket
from hypothesis import HealthCheck, settings

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
