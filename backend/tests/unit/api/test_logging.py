"""A-10 / S10: the log scrubber. Named: test_no_secret_in_logs_or_responses (sentinel key, seeded
passwords, a malformed login) and test_logs_contain_no_document_text."""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from fastapi.testclient import TestClient

from tests.unit.api.test_auth import CSRF, PASSWORD, Env
from trace_api import deps
from trace_api.logging import REDACTED, configure_logging, scrub
from trace_api.main import create_app

SENTINEL_KEY = "gsk_SENTINEL1234567890"
DOCUMENT_TEXT = "Machine 21 ran normally through both shifts and nothing was wrong"


@pytest.fixture
def logs() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    configure_logging(stream)
    yield stream
    configure_logging()  # back to stderr


def _lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def test_scrubber_redacts_by_key_and_by_value() -> None:
    out = scrub(
        None,
        "info",
        {
            "event": "login",
            "password": PASSWORD,
            "quote": DOCUMENT_TEXT,
            "headers": {"cookie": "trace_session=abc", "x": "fine"},
            "note": f"used {SENTINEL_KEY} and Bearer abc.def",
            "count": 3,
        },
    )
    assert out["password"] == out["quote"] == REDACTED
    assert out["headers"] == {"cookie": REDACTED, "x": "fine"}
    assert SENTINEL_KEY not in out["note"] and "abc.def" not in out["note"]  # type: ignore[operator]
    assert out["event"] == "login" and out["count"] == 3


def test_logs_contain_no_document_text(logs: io.StringIO) -> None:
    log = structlog.get_logger("test")
    log.info("page read", text=DOCUMENT_TEXT, ocr_text=DOCUMENT_TEXT, prompt=DOCUMENT_TEXT)
    try:
        raise ValueError(DOCUMENT_TEXT)  # a decoder error message can carry the document
    except ValueError as exc:
        log.error("read failed", exc_info=exc)
    out = logs.getvalue()
    assert DOCUMENT_TEXT not in out and "ran normally" not in out
    assert _lines(logs)[1]["exception_type"] == "ValueError"


def test_no_secret_in_logs_or_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loopback_only: None, logs: io.StringIO
) -> None:
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TRACE_DEV_AUTH", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", SENTINEL_KEY)
    env = Env(tmp_path)
    app = create_app()
    app.dependency_overrides[deps.get_auth_repo] = lambda: env.repo
    bodies: list[str] = []
    with TestClient(app, base_url="http://127.0.0.1") as client:
        calls = [
            client.post(
                "/api/v1/auth/login", json={"username": "rita", "password": PASSWORD}, headers=CSRF
            ),
            client.post(
                "/api/v1/auth/login", json={"username": "rita", "password": "wrong"}, headers=CSRF
            ),
            client.post(
                "/api/v1/auth/login",
                content=b'{"username": 5',
                headers={**CSRF, "Content-Type": "application/json"},
            ),
            client.post("/api/v1/auth/login", json={"username": "rita"}, headers=CSRF),
            client.get("/api/v1/auth/me"),
            client.get("/healthz"),
        ]
        for res in calls:
            bodies.append(res.text)
            bodies.append(json.dumps(dict(res.headers)))
        token = client.cookies.get("trace_session")
    everything = logs.getvalue() + "\n".join(bodies)
    assert PASSWORD not in logs.getvalue() and "wrong" not in logs.getvalue()
    assert SENTINEL_KEY not in everything
    assert token and token not in logs.getvalue()  # the session token never reaches a log
    access = [line for line in _lines(logs) if line.get("event") == "request"]
    assert access and all(set(line) >= {"method", "path", "status"} for line in access)
    assert PASSWORD not in "\n".join(bodies)  # and never echoed back in a response
