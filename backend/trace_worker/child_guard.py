"""Build-child guards (A-08, HARDENING S4): a runaway or orphaned decoder process must die.

- `start_deadline`: the child ends itself after a deadline (the parent's timeout is a second line);
- `start_parent_watch`: the child ends itself when its parent is gone (an orphan keeps no lock);
- `kill_tree`: the parent kills the child AND its grandchildren (Tesseract is a grandchild);
- `apply_rlimits`: an address-space cap where the platform has `resource` (POSIX); elsewhere it
  reports `False` and the caller must not claim a limit.
No decoder is imported here.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404 (taskkill on Windows; fixed arguments)
import sys
import threading
from collections.abc import Callable

DEADLINE_EXIT = 124
ORPHAN_EXIT = 125
_hard_exit: Callable[[int], None] = os._exit


def start_deadline(
    seconds: float, *, exit_fn: Callable[[int], None] | None = None
) -> threading.Timer:
    """End this process with exit code 124 after `seconds`."""
    timer = threading.Timer(seconds, lambda: (exit_fn or _hard_exit)(DEADLINE_EXIT))
    timer.daemon = True
    timer.start()
    return timer


def start_parent_watch(
    is_parent_alive: Callable[[], bool],
    *,
    interval: float = 1.0,
    exit_fn: Callable[[int], None] | None = None,
) -> threading.Event:
    """Poll the parent; when it is gone, end this process with exit code 125. Set the returned
    event to stop watching."""
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(interval):
            if not is_parent_alive():
                (exit_fn or _hard_exit)(ORPHAN_EXIT)
                return

    threading.Thread(target=watch, daemon=True, name="parent-watch").start()
    return stop


def kill_tree(pid: int) -> None:
    """Kill `pid` and every descendant. Never raises for an already-dead process."""
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603
            ["taskkill", "/PID", str(pid), "/T", "/F"],  # noqa: S607
            capture_output=True,
            check=False,
            timeout=30,
        )
        return
    import signal

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def apply_rlimits(max_address_space: int) -> bool:
    """Cap the address space (RLIMIT_AS). False where the platform cannot enforce it."""
    try:
        import resource
    except ImportError:
        return False
    resource.setrlimit(  # type: ignore[attr-defined,unused-ignore]
        resource.RLIMIT_AS,  # type: ignore[attr-defined,unused-ignore]
        (max_address_space, max_address_space),
    )
    return True
