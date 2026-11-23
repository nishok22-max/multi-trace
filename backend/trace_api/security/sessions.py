"""Opaque server-side sessions and login throttling (A-09, S1).

- The cookie holds a random opaque token; only its sha256 is stored (`sessions.token_sha256`).
- A login always mints a NEW token and revokes the one presented (rotation); sessions end at an
  absolute expiry (`SESSION_TTL`) regardless of activity.
- 5 failed logins for a username within 5 minutes lock that username out for the rest of the
  window; the lock is checked before any password work.
Time always comes from the injected clock.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from trace_adapters.sqlite.store import connect
from trace_api.security.passwords import hash_password, verify_password
from trace_core.models.evidence import Role
from trace_core.normalise.time import fmt_utc, parse_utc
from trace_core.ports import Clock

COOKIE = "trace_session"
SESSION_TTL = timedelta(hours=8)
LOCKOUT_FAILURES = 5
LOCKOUT_WINDOW = timedelta(minutes=5)


class LockedOut(Exception):
    """Too many failed logins for this username in the window."""


class BadCredentials(Exception):
    """Wrong username or password (the two are indistinguishable)."""


@dataclass(frozen=True)
class User:
    user_id: str
    username: str
    display_name: str
    role: Role


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthRepository:
    def __init__(self, path: Path | str, clock: Clock) -> None:
        self._path = str(path)
        self._clock = clock

    def _now(self) -> str:
        return fmt_utc(self._clock.now_utc())

    def _tx(self) -> sqlite3.Connection:
        conn = connect(self._path)
        conn.execute("BEGIN IMMEDIATE")
        return conn

    # ---------------------------------------------------------------------------- users
    def create_user(
        self, user_id: str, username: str, display_name: str, role: Role, password: str
    ) -> None:
        stored = hash_password(password)
        conn = self._tx()
        try:
            conn.execute(
                "INSERT INTO users(user_id, username, display_name, role, password_hash,"
                " disabled, created_at) VALUES (?,?,?,?,?,0,?)",
                (user_id, username, display_name, role, stored, self._now()),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # --------------------------------------------------------------------------- login
    def login(
        self, username: str, password: str, presented_token: str | None = None
    ) -> tuple[str, User]:
        """Returns (new opaque token, user). Raises LockedOut / BadCredentials."""
        now = self._clock.now_utc()
        since = fmt_utc(now - LOCKOUT_WINDOW)
        conn = connect(self._path)
        try:
            failures = conn.execute(
                "SELECT COUNT(*) FROM login_attempts WHERE username=? AND success=0 AND at>?",
                (username, since),
            ).fetchone()[0]
            if failures >= LOCKOUT_FAILURES:
                raise LockedOut
            row = conn.execute(
                "SELECT user_id, username, display_name, role, password_hash, disabled"
                " FROM users WHERE username=?",
                (username,),
            ).fetchone()
        finally:
            conn.close()
        stored = row[4] if row is not None and not row[5] else None
        ok = verify_password(stored, password)
        tx = self._tx()
        try:
            tx.execute(
                "INSERT INTO login_attempts(username, at, success) VALUES (?,?,?)",
                (username, self._now(), 1 if ok else 0),
            )
            if not ok:
                tx.execute("COMMIT")
                raise BadCredentials
            if presented_token:
                tx.execute(
                    "DELETE FROM sessions WHERE token_sha256=?", (token_hash(presented_token),)
                )
            token = secrets.token_urlsafe(32)
            stamp = self._now()
            tx.execute(
                "INSERT INTO sessions(token_sha256, user_id, created_at, last_seen_at, expires_at)"
                " VALUES (?,?,?,?,?)",
                (token_hash(token), row[0], stamp, stamp, fmt_utc(now + SESSION_TTL)),
            )
            tx.execute("COMMIT")
        except (BadCredentials, LockedOut):
            raise
        except BaseException:
            tx.execute("ROLLBACK")
            raise
        finally:
            tx.close()
        return token, User(row[0], row[1], row[2], row[3])

    # ------------------------------------------------------------------------- sessions
    def lookup(self, token: str | None) -> User | None:
        if not token:
            return None
        conn = connect(self._path)
        try:
            row = conn.execute(
                "SELECT u.user_id, u.username, u.display_name, u.role, s.expires_at, u.disabled"
                " FROM sessions s JOIN users u ON u.user_id = s.user_id WHERE s.token_sha256=?",
                (token_hash(token),),
            ).fetchone()
        finally:
            conn.close()
        if row is None or row[5]:
            return None
        if parse_utc(row[4]) <= self._clock.now_utc():  # absolute expiry, activity never extends
            self.logout(token)
            return None
        return User(row[0], row[1], row[2], row[3])

    def logout(self, token: str | None) -> None:
        if not token:
            return
        tx = self._tx()
        try:
            tx.execute("DELETE FROM sessions WHERE token_sha256=?", (token_hash(token),))
            tx.execute("COMMIT")
        finally:
            tx.close()
