"""B-03/B-08: the ∃ quantifier and per-phrase scopes. Named: test_envelope_per_phrase_scope,
test_exists_*: agree on a violation, disagree only with full coverage, never on missing data."""

from __future__ import annotations

import pytest

from tests.skeleton.world import World, build_version, synthetic_world
from tests.unit.engine.test_gate import CFG, COVER, _ctx
from trace_core.compare.gate import gate
from trace_core.ids import build_claim
from trace_core.models.case import CaseVersion
from trace_core.models.claims import ClaimRecord
from trace_core.models.evidence import SensorWindowPointer, TextSpanPointer
from trace_core.normalise.sensor_state import STATE_RULE


def _version(root, **kwargs) -> CaseVersion:  # type: ignore[no-untyped-def]
    return build_version(synthetic_world(root, **kwargs))


@pytest.fixture(scope="module")
def spike(tmp_path_factory: pytest.TempPathFactory) -> CaseVersion:
    return _version(tmp_path_factory.mktemp("spike"), spike=True)


@pytest.fixture(scope="module")
def calm(tmp_path_factory: pytest.TempPathFactory) -> CaseVersion:
    return _version(tmp_path_factory.mktemp("calm-exists"), spike=False)


@pytest.fixture(scope="module")
def partial(tmp_path_factory: pytest.TempPathFactory) -> CaseVersion:
    return _version(tmp_path_factory.mktemp("partial-exists"), spike=False, drop_hours=(3, 4))


def _channel_state(version: CaseVersion, attribute: str) -> ClaimRecord:
    return next(
        c
        for c in version.records.claims
        if c.attribute == attribute and c.method.rule_id == STATE_RULE
    )


def _text(version: CaseVersion, phrase_class: str, value: str, attribute: str) -> ClaimRecord:
    """A reader-style claim for an ∃ phrase, on the same machine and day as the state claim."""
    base = next(c for c in version.records.claims if c.modality == "text")
    fields = base.model_dump(mode="python")
    quote = f"{value} {attribute} was noticed on this shift"
    ev = TextSpanPointer.model_validate(base.evidence.model_dump())  # type: ignore[union-attr]
    fields.update(
        attribute=attribute,
        value=value,
        statement=quote,
        method={**fields["method"], "rule_id": f"phrase.{phrase_class}"},
        evidence=ev.model_copy(update={"quote": quote}),
    )
    return build_claim(**fields)


def test_envelope_per_phrase_scope(spike: CaseVersion) -> None:
    scopes = {tuple(e.scope) for e in spike.records.envelopes}
    assert ("vibration",) in scopes and ("pressure",) in scopes
    assert max(len(e.scope) for e in spike.records.envelopes) == 4  # the all-channel family stays
    first = spike.records.envelopes[0]
    assert len(first.scope) == 4  # the all-channel envelope sorts first (API and tests rely on it)
    # a channel envelope is its own conformal quantile, not the all-channel one
    vib = next(e for e in spike.records.envelopes if e.scope == ["vibration"])
    assert vib.T_star != first.T_star and vib.n == first.n
    assert set(vib.med) == set(vib.mad) == {"vibration"}


def test_scope_state_claims_are_per_channel_and_unpaired_noise_free(spike: CaseVersion) -> None:
    state = _channel_state(spike, "vibration")
    ev = state.evidence
    assert isinstance(ev, SensorWindowPointer) and ev.channels == ["vibration"]
    assert isinstance(state.value, dict) and {"T_D_upper", "T_D_lower"} <= set(state.value)
    # no spurious comparison against raw windows: only the ∀ report claim is compared in the
    # skeleton world (its PDF has no ∃ phrase), against the all-channel state only
    assert len(spike.records.comparisons) == 1


def test_exists_high_vibration_agrees_on_a_spike(spike: CaseVersion) -> None:
    text = _text(spike, "vibration_high", "high", "vibration")
    state = _channel_state(spike, "vibration")
    record = gate(text, state, _ctx(spike, [], [COVER]))
    assert record.outcome == "agree" and record.checks[-1].passed
    assert "observed" in record.reason
    assert gate(state, text, _ctx(spike, [], [COVER])).outcome == "agree"  # order-free


def test_exists_disagrees_only_with_full_coverage_and_no_violation(calm: CaseVersion) -> None:
    text = _text(calm, "vibration_high", "high", "vibration")
    state = _channel_state(calm, "vibration")
    record = gate(text, state, _ctx(calm, [], [COVER]))
    assert record.outcome == "disagree" and "100% coverage" in record.reason


def test_exists_with_missing_data_cannot_tell(partial: CaseVersion) -> None:
    text = _text(partial, "vibration_high", "high", "vibration")
    state = _channel_state(partial, "vibration")
    record = gate(text, state, _ctx(partial, [], [COVER]))
    assert record.outcome == "cant_tell" and "missing" in record.reason


def test_a_phrase_is_judged_against_its_own_scope_only(spike: CaseVersion) -> None:
    """An all-channel ∀ claim against a single-channel state is refused at check 4, and an ∃
    claim against the all-channel state likewise (the envelope scope must equal the phrase's)."""
    forall = next(c for c in spike.records.claims if c.modality == "text")
    vibration = _channel_state(spike, "vibration")
    vib_as_group = build_claim(
        **{**vibration.model_dump(mode="python"), "attribute": "operating_state"}
    )
    record = gate(forall, vib_as_group, _ctx(spike, [], [COVER]))
    assert record.outcome == "cant_compare" and record.checks[-1].n == 4
    exists = _text(spike, "vibration_high", "high", "vibration")
    overall = next(
        c
        for c in spike.records.claims
        if c.attribute == "operating_state" and c.method.rule_id == STATE_RULE
    )
    wrong = build_claim(**{**overall.model_dump(mode="python"), "attribute": "vibration"})
    assert gate(exists, wrong, _ctx(spike, [], [COVER])).outcome == "cant_compare"


def test_lower_side_uses_the_lower_statistic(calm: CaseVersion) -> None:
    from trace_core.compare.quantifiers import sensor_state_of

    state = sensor_state_of(_channel_state(calm, "vibration"))
    assert state is not None
    assert state.violated_on("upper") == (
        state.t_upper is not None and state.t_upper > state.t_star
    )
    assert state.violated_on("lower") == (
        state.t_lower is not None and state.t_lower > state.t_star
    )
    assert CFG.ontology.phrases  # the rules come from the ontology, not the code
    assert isinstance(World, type)
