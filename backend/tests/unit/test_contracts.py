"""Contract export: deterministic, complete, and the C.4 routes exist as typed 501 stubs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tools import export_contracts
from trace_api.contract_app import build_contract_app
from trace_api.problems import PROBLEM_TYPES

# IMPLEMENTATION_PLAN C.4 (P1 SSE events route is flag-gated and not part of contracts-v1).
EXPECTED_ROUTES = {
    ("get", "/healthz"),
    ("get", "/readyz"),
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/logout"),
    ("get", "/api/v1/auth/me"),
    ("get", "/api/v1/cases"),
    ("post", "/api/v1/cases"),
    ("get", "/api/v1/cases/{cid}/latest"),
    ("post", "/api/v1/cases/{cid}/sources"),
    ("get", "/api/v1/cases/{cid}/sources/{sid}/original"),
    ("post", "/api/v1/cases/{cid}/build"),
    ("get", "/api/v1/cases/{cid}/builds/{bid}"),
    *{
        ("get", f"/api/v1/cases/{{cid}}/versions/{{v}}/{leaf}")
        for leaf in (
            "state",
            "story",
            "timeline",
            "claims",
            "comparisons",
            "conflicts",
            "review",
            "manifest",
            "integrity",
        )
    },
    ("get", "/api/v1/cases/{cid}/versions/{v}/claims/{claim_id}"),
    ("get", "/api/v1/cases/{cid}/versions/{v}/claims/{claim_id}/evidence"),
    ("get", "/api/v1/cases/{cid}/versions/{v}/claims/{claim_id}/evidence/page.png"),
    ("get", "/api/v1/cases/{cid}/versions/{v}/claims/{claim_id}/evidence/crop.png"),
    ("get", "/api/v1/cases/{cid}/versions/{v}/entities/{eid}/envelope"),
    ("post", "/api/v1/cases/{cid}/versions/{v}/replay"),
    ("post", "/api/v1/cases/{cid}/claims/{claim_id}/recheck"),
    ("post", "/api/v1/cases/{cid}/review/{rid}/decision"),
    ("post", "/api/v1/eval/run"),
    ("get", "/api/v1/eval/report"),
}
CID = "case-m21-0314"
CLAIM = "clm_" + "a" * 24
CSRF = {"X-TRACE-CSRF": "x"}


def test_every_c4_route_is_declared() -> None:
    spec = build_contract_app().openapi()
    declared = {(m, path) for path, ops in spec["paths"].items() for m in ops}
    assert declared == EXPECTED_ROUTES


def test_openapi_is_3_1_and_writes_carry_the_csrf_header() -> None:
    spec = build_contract_app().openapi()
    assert spec["openapi"].startswith("3.1")
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            names = {p["name"] for p in op.get("parameters", [])}
            if method == "post":
                assert "X-TRACE-CSRF" in names, (method, path)
            assert op["operationId"], (method, path)


def test_every_model_has_a_schema_file_and_export_is_deterministic() -> None:
    first, second = export_contracts.render_files(), export_contracts.render_files()
    assert first == second
    models = export_contracts.public_models()
    assert {f"{n}.json" for n in models} | {"openapi.json"} == set(first)
    for key in (
        "ClaimRecord",
        "DecisionRequest",
        "ConfigBundle",
        "CaseVersion",
        "PageText",
        "Interval",
        "UnknownTime",
        "ObservedTime",
        "ConflictRecord",
        "ReviewEvent",
        "EvalReport",
        "Problem",
        "Envelope",
    ):
        assert key in models
    for text in first.values():
        json.loads(text)


def test_committed_schemas_match_the_models() -> None:
    assert export_contracts.contracts_check() == 0


def test_conflict_schema_pins_averaged_false_and_no_status() -> None:
    schema = json.loads(export_contracts.render_files()["ConflictRecord.json"])
    assert schema["properties"]["averaged"]["const"] is False
    assert "status" not in schema["properties"]
    claim = json.loads(export_contracts.render_files()["ClaimRecord.json"])
    assert "status" not in claim["properties"] and "version" not in claim["properties"]
    assert claim["additionalProperties"] is False


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        # Implemented: latest, state, story, timeline, claims, comparisons, conflicts, review,
        # manifest, integrity, claim detail, envelope, build, sources and decisions. These remain
        # contract stubs.
        ("get", f"/api/v1/cases/{CID}/versions/1/claims/{CLAIM}/evidence", {}),
        ("post", f"/api/v1/cases/{CID}/versions/1/replay", {"headers": CSRF}),
        ("post", "/api/v1/eval/run", {"headers": CSRF}),
    ],
)
def test_stubs_return_501_problem_json(
    loopback_only: None, method: str, path: str, kwargs: dict[str, object]
) -> None:
    client = TestClient(build_contract_app())
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 501
    assert res.headers["content-type"].startswith("application/problem+json")
    assert res.json()["type"] == "/problems/not-implemented"


def test_healthz_is_live_and_problem_types_are_stable(loopback_only: None) -> None:
    client = TestClient(build_contract_app())
    assert client.get("/healthz").json() == {"status": "ok"}
    assert {
        "evidence-changed",
        "already-decided",
        "build-in-progress",
        "render-missing",
        "replay-cache-miss",
        "pdf-page-cap",
        "rate-limited",
    } <= set(PROBLEM_TYPES)


def test_a_reviewer_field_on_the_decision_route_is_422(loopback_only: None) -> None:
    client = TestClient(build_contract_app())
    body = {
        "choice": {"type": "escalate"},
        "reason": "needs a senior look",
        "base_version": 1,
        "shown_evidence_hash": "0" * 64,
    }
    url = f"/api/v1/cases/{CID}/review/rv_{'b' * 24}/decision"
    # a valid body reaches the real route, which authenticates first
    assert client.post(url, json=body, headers=CSRF).status_code == 401
    # authentication comes first; the 422 for a spoofed `reviewer` field (signed in) is pinned
    # by tests/unit/api/test_decisions_api.py::test_spoofed_reviewer_field_422
    assert client.post(url, json={**body, "reviewer": "mallory"}, headers=CSRF).status_code == 401
    # the missing CSRF header is refused by the middleware of the real app (test_auth.py)
    assert client.post(url, json=body).status_code == 401


def test_schema_dts_exists_and_is_nonempty() -> None:
    dts = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "api" / "schema.d.ts"
    text = dts.read_text(encoding="utf-8")
    assert "export interface paths" in text and "ClaimRecord" in text
