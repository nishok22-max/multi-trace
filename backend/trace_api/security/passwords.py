"""Password hashing (A-09, S1): argon2id with the library's current defaults.

Unknown users cost the same as known ones: `verify_password` against a fixed dummy hash, so login
timing does not reveal whether a username exists. Hashing is bounded by a semaphore so a login
flood cannot exhaust memory (argon2 is memory-hard).
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MAX_CONCURRENT_HASHES = 4
_gate = threading.BoundedSemaphore(MAX_CONCURRENT_HASHES)
_hasher = PasswordHasher()  # argon2id
_DUMMY = _hasher.hash("dummy-password-for-constant-work")


def hash_password(password: str) -> str:
    with _gate:
        return _hasher.hash(password)


def verify_password(
    stored: str | None, password: str, *, verify: Callable[[str, str], bool] | None = None
) -> bool:
    """True iff `password` matches `stored`. `stored=None` (unknown user) does the same work
    against a dummy hash and returns False."""
    target = stored if stored is not None else _DUMMY
    with _gate:
        try:
            ok = verify(target, password) if verify else _hasher.verify(target, password)
        except (VerificationError, InvalidHashError):
            ok = False
    return ok and stored is not None
