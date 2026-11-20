"""Clock, LlmProposer and Redactor contracts (fakes)."""

from __future__ import annotations

from datetime import UTC, datetime

from trace_adapters.fakes import FakeLlm, FixedClock, IdentityRedactor
from trace_core.models.evidence import Proposal
from trace_core.ports import Clock, LlmProposer, Redactor


def test_fixed_clock_is_utc_and_stable() -> None:
    clock: Clock = FixedClock()
    now = clock.now_utc()
    assert now == datetime(2015, 3, 15, 9, 10, tzinfo=UTC)
    assert now.utcoffset() is not None and clock.now_utc() == now


def test_fixed_clock_can_be_set() -> None:
    clock = FixedClock()
    clock.set("2030-01-01T00:00:00Z")
    assert clock.now_utc().year == 2030


def test_redactor_round_trip() -> None:
    redactor: Redactor = IdentityRedactor()
    doc = redactor.redact("Pressure 4.2 bar")
    assert doc.text == "Pressure 4.2 bar" and doc.spans == []


def test_llm_returns_a_batch_and_is_deterministic() -> None:
    proposal = Proposal(quote="ran normally", attribute="operating_state", value="normal")
    llm: LlmProposer = FakeLlm([proposal])
    doc = IdentityRedactor().redact("text")
    first, second = llm.propose(doc, "p1"), llm.propose(doc, "p1")
    assert first == second and first.proposals == [proposal] and first.prompt_id == "p1"


def test_llm_defaults_to_no_proposals() -> None:
    assert FakeLlm().propose(IdentityRedactor().redact("x"), "p").proposals == []
