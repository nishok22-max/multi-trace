"""A-09 / C-09: sessions, CSRF, host/origin checks, security headers. Named tests as in
IMPLEMENTATION_PLAN M4: test_login_lockout_5_in_5min, test_session_rotated_on_login,
test_session_token_stored_hashed, test_session_absolute_expiry, test_login_requires_csrf_header,
test_cross_origin_form_post_403, test_write_requires_json_and_csrf, test_foreign_host_header_400,
test_login_unknown_user_constant_work, test_login_concurrency_bounded,
test_lan_without_tls_refuses_start, test_html_responses_have_csp_header_with_frame_ancestors,
test_original_download_headers, test_viewer_cannot_start_a_build."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.factories import make_case
from trace_adapters.fakes.clock import FixedClock
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_api import deps
from trace_api.main import create_app
from trace_api.security import passwords
from trace_api.security.headers import original_download_headers
from trace_api.security.sessions import (
    COOKIE,
    SESSION_TTL,
    AuthRepository,
    BadCredentials,
    token_hash,
)
from trace_api.settings import assert_safe_bind

CSRF = {"X-TRACE-CSRF": "1"}
PASSWORD = "correct horse battery staple"
JSON = {**CSRF, "Content-Type": "application/json"}
LOGIN = {"username": "rita", "password": PASSWORD}


class Env:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.clock = FixedClock("2015-08-06T04:00:00Z")
        SqliteClaimStore(root / "trace.db")  # migrations
        self.repo = AuthRepository(root / "trace.db", self.clock)
        self.repo.create_user("u-rita", "rita", "Rita Reviewer", "reviewer", PASSWORD)
        self.repo.create_user("u-vik", "vik", "Vik Viewer", "viewer", PASSWORD)
        SqliteClaimStore(root / "trace.db").append(make_case().case_id, [make_case()])


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TRACE_DEV_AUTH", raising=False)
    return Env(tmp_path)


@pytest.fixture
def client(env: Env, loopback_only: None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[deps.get_auth_repo] = lambda: env.repo
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def _login(client: TestClient, user: str = "rita", password: str = PASSWORD) -> int:
    return client.post(
        "/api/v1/auth/login", json={"username": user, "password": password}, headers=CSRF
    ).status_code


def test_login_me_logout_roundtrip(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    res = client.post("/api/v1/auth/login", json=LOGIN, headers=CSRF)
    assert res.status_code == 200 and res.json()["role"] == "reviewer"
    assert res.headers["cache-control"] == "no-store"
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/v1/auth/me").json()["user_id"] == "u-rita"
    assert client.post("/api/v1/auth/logout", headers=CSRF).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_requires_csrf_header(client: TestClient) -> None:
    assert client.post("/api/v1/auth/login", json=LOGIN).status_code == 403


def test_write_requires_json_and_csrf(client: TestClient) -> None:
    case = make_case().case_id
    assert client.post(f"/api/v1/cases/{case}/build").status_code == 403  # no header
    form = client.post(f"/api/v1/cases/{case}/build", data={"a": "b"}, headers=CSRF)
    assert form.status_code == 415
    assert form.headers["content-type"].startswith("application/problem+json")


def test_cross_origin_form_post_403(client: TestClient) -> None:
    res = client.post(
        "/api/v1/auth/login",
        data={"username": "rita", "password": PASSWORD},
        headers={"Origin": "http://evil.example", **CSRF},
    )
    assert res.status_code == 403
    same = client.post(
        "/api/v1/auth/login", json=LOGIN, headers={"Origin": "http://127.0.0.1", **CSRF}
    )
    assert same.status_code == 200


def test_foreign_host_header_400(client: TestClient) -> None:
    res = client.get("/api/v1/auth/me", headers={"Host": "attacker.example"})
    assert res.status_code == 400


def test_wrong_password_and_unknown_user_look_identical(client: TestClient) -> None:
    wrong = client.post(
        "/api/v1/auth/login", json={"username": "rita", "password": "nope"}, headers=CSRF
    )
    unknown = client.post(
        "/api/v1/auth/login", json={"username": "ghost", "password": "nope"}, headers=CSRF
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_lockout_5_in_5min(client: TestClient, env: Env) -> None:
    for _ in range(5):
        assert _login(client, password="bad") == 401
    assert _login(client) == 429  # locked even with the right password
    env.clock.set("2015-08-06T04:05:01Z")  # the window has passed
    assert _login(client) == 200


def test_session_rotated_on_login(client: TestClient) -> None:
    client.post("/api/v1/auth/login", json=LOGIN, headers=CSRF)
    first = client.cookies.get(COOKIE)
    client.post("/api/v1/auth/login", json=LOGIN, headers=CSRF)
    second = client.cookies.get(COOKIE)
    assert first and second and first != second
    stale = TestClient(client.app, base_url="http://127.0.0.1", cookies={COOKIE: first})
    assert stale.get("/api/v1/auth/me").status_code == 401  # the old token was revoked


def test_session_token_stored_hashed(client: TestClient, env: Env) -> None:
    client.post("/api/v1/auth/login", json=LOGIN, headers=CSRF)
    token = client.cookies.get(COOKIE)
    assert token
    rows = sqlite3.connect(env.root / "trace.db").execute("SELECT token_sha256 FROM sessions")
    stored = [r[0] for r in rows]
    assert stored == [token_hash(token)] and token not in stored


def test_session_absolute_expiry(client: TestClient, env: Env) -> None:
    client.post("/api/v1/auth/login", json=LOGIN, headers=CSRF)
    env.clock.set("2015-08-06T11:59:59Z")
    assert client.get("/api/v1/auth/me").status_code == 200  # activity does not extend it
    env.clock.set("2015-08-06T12:00:00Z")  # 8 h after login
    assert SESSION_TTL.total_seconds() == 8 * 3600
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_unknown_user_constant_work(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Spy:
        def __init__(self, real: object) -> None:
            self.real = real

        def verify(self, stored: str, password: str) -> bool:
            calls.append(stored)
            return bool(self.real.verify(stored, password))  # type: ignore[attr-defined]

        def hash(self, password: str) -> str:
            return str(self.real.hash(password))  # type: ignore[attr-defined]

    monkeypatch.setattr(passwords, "_hasher", Spy(passwords._hasher))
    for name in ("rita", "ghost"):
        with pytest.raises(BadCredentials):
            env.repo.login(name, "nope")
    assert len(calls) == 2  # the unknown user cost one full verification too
    assert calls[1] == passwords._DUMMY


def test_login_concurrency_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    live = peak = 0
    lock = threading.Lock()

    def slow(stored: str, password: str) -> bool:
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.05)
        with lock:
            live -= 1
        return False

    threads = [
        threading.Thread(
            target=passwords.verify_password, args=(None, "x"), kwargs={"verify": slow}
        )
        for _ in range(passwords.MAX_CONCURRENT_HASHES * 3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert 1 <= peak <= passwords.MAX_CONCURRENT_HASHES


def test_lan_without_tls_refuses_start() -> None:
    assert_safe_bind("127.0.0.1", tls=False)
    assert_safe_bind("0.0.0.0", tls=True)  # noqa: S104
    with pytest.raises(RuntimeError):
        assert_safe_bind("0.0.0.0", tls=False)  # noqa: S104


def test_viewer_cannot_start_a_build(client: TestClient) -> None:
    client.post("/api/v1/auth/login", json={"username": "vik", "password": PASSWORD}, headers=CSRF)
    case = make_case().case_id
    res = client.post(f"/api/v1/cases/{case}/build", headers=JSON)
    assert res.status_code == 403


def test_html_responses_have_csp_header_with_frame_ancestors(
    tmp_path: Path, loopback_only: None
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    (dist / "csp-hashes.json").write_text(
        json.dumps({"scripts": ["'sha256-abc='"], "styles": []}), encoding="utf-8"
    )
    with TestClient(create_app(dist=dist), base_url="http://127.0.0.1") as c:
        res = c.get("/")
    csp = res.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "'sha256-abc='" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "public" not in res.headers.get("cache-control", "")


def test_api_responses_are_never_public(client: TestClient) -> None:
    res = client.get("/api/v1/auth/me")
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["cross-origin-resource-policy"] == "same-origin"


def test_original_download_headers() -> None:
    h = original_download_headers('../../evil".pdf')
    assert h["Content-Type"] == "application/octet-stream"
    assert (
        h["Content-Disposition"].startswith("attachment;") and ".." not in h["Content-Disposition"]
    )
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["Content-Security-Policy"].startswith("sandbox")
    assert h["Cross-Origin-Resource-Policy"] == "same-origin"
