"""D-11 container hygiene, checked statically (no Docker needed): non-root, read-only root,
loopback-only publishing, no capabilities, no secrets in the build context. Named:
test_compose_ports_loopback_only, test_image_nonroot_readonly, test_image_secret_grep,
test_container_bind_rule. The image itself has NOT been built or scanned in this repository's
checks; see docs/MVP_FREEZE_NOTES.md."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from trace_api.settings import assert_safe_bind, in_container

REPO = Path(__file__).resolve().parents[3]
DOCKERFILE = (REPO / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICE = COMPOSE["services"]["trace"]


def test_compose_ports_loopback_only() -> None:
    assert SERVICE["ports"], "the app must be published"
    for port in SERVICE["ports"]:
        assert str(port).startswith("127.0.0.1:"), port  # never 0.0.0.0, never bare "8000:8000"


def test_image_nonroot_readonly() -> None:
    users = re.findall(r"^USER\s+(\S+)", DOCKERFILE, re.MULTILINE)
    assert users and users[-1] not in ("root", "0", "0:0")  # the last USER decides
    assert SERVICE["read_only"] is True and "/tmp" in SERVICE["tmpfs"]  # noqa: S108
    assert SERVICE["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in SERVICE["security_opt"]
    assert SERVICE["user"].split(":")[0] not in ("0", "root")
    assert SERVICE["pids_limit"] and SERVICE["mem_limit"]
    assert "privileged" not in SERVICE and "network_mode" not in SERVICE


def test_image_secret_grep() -> None:
    """Nothing secret-shaped in the Dockerfile or compose file, and the build context excludes
    every place a secret lives (`.env`, the credentials file, databases)."""
    for text in (DOCKERFILE, (REPO / "docker-compose.yml").read_text(encoding="utf-8")):
        assert not re.search(r"gsk_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{16,}|PRIVATE KEY", text)
        assert not re.search(
            r"(?im)^\s*(ENV|ARG)\s+\w*(KEY|SECRET|PASSWORD|TOKEN)\w*\s*=?\s*\S", text
        )
    ignore = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for needed in (
        ".env",
        "seed/credentials.local.txt",
        "**/*.db*",
        "data/",
        "**/.venv",
        "**/node_modules",
    ):
        assert needed in ignore, needed
    assert "COPY . " not in DOCKERFILE  # the context is copied by named directories only


def test_container_bind_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """0.0.0.0 is accepted only inside a container that asked for it; a laptop with the variable
    set (no /.dockerenv) still refuses."""
    monkeypatch.delenv("TRACE_CONTAINER", raising=False)
    with pytest.raises(RuntimeError):
        assert_safe_bind("0.0.0.0", tls=False)  # noqa: S104
    monkeypatch.setenv("TRACE_CONTAINER", "1")
    if not Path("/.dockerenv").exists():
        assert not in_container()
        with pytest.raises(RuntimeError):
            assert_safe_bind("0.0.0.0", tls=False)  # noqa: S104
    monkeypatch.setattr(Path, "exists", lambda self: str(self).replace("\\", "/") == "/.dockerenv")
    assert in_container()
    assert_safe_bind("0.0.0.0", tls=False)  # noqa: S104


@pytest.mark.xfail(
    strict=True,
    reason="base images are not pinned by digest: resolving digests needs registry access and "
    "changing a base-image digest is an ask-first change (CLAUDE.md)",
)
def test_images_pinned_by_digest() -> None:
    froms = re.findall(r"^FROM\s+(\S+)", DOCKERFILE, re.MULTILINE)
    assert froms and all("@sha256:" in f for f in froms)
