"""The six-check Comparability Gate (B-08 minimal; SYSTEM_DESIGN 7.1).

Checks are evaluated in order and recorded in order; evaluation stops at the first check that
cannot pass. Failing 1-4 gives "cant_compare", failing 5 gives "cant_tell", and check 6 applies the
phrase quantifier. Supported pairing in M2: a text claim with a quantifier phrase against a
day-level sensor state claim. Everything else fails closed as "cant_compare".

TODO(M3): error/failure/maintenance rows as supporting context and as ∀ violations, the ∃ rule,
numeric-vs-numeric tolerance, held claims, log-coverage in the agree rule.
"""

from __future__ import annotations

from trace_core.compare.quantifiers import (
    SensorState,
    phrase_rule_for,
    sensor_state_of,
)
from trace_core.ids import comparison_id
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import PhraseRule
from trace_core.models.evidence import TextSpanPointer
from trace_core.models.records import (
    ComparisonRecord,
    Envelope,
    GateCheck,
    GateCheckName,
    Outcome,
)
from trace_core.models.time import Interval
from trace_core.normalise.time import local_date
from trace_core.stage_types import GateContext


def _check(n: int, name: GateCheckName, ok: bool, detail: str) -> GateCheck:
    return GateCheck.model_validate({"n": n, "name": name, "pass": ok, "detail": detail})


def _fmt(x: float) -> str:
    return f"{x:.2f}"


def _record(
    a: ClaimRecord,
    b: ClaimRecord,
    ctx: GateContext,
    checks: list[GateCheck],
    outcome: Outcome,
    reason: str,
) -> ComparisonRecord:
    return ComparisonRecord(
        comparison_id=comparison_id([a.claim_id, b.claim_id], ctx.config_hash),
        claim_a=a.claim_id,
        claim_b=b.claim_id,
        config_hash=ctx.config_hash,
        checks=checks,
        outcome=outcome,
        reason=reason,
    )


def _stop(
    a: ClaimRecord,
    b: ClaimRecord,
    ctx: GateContext,
    checks: list[GateCheck],
    outcome: Outcome,
    reason: str,
) -> ComparisonRecord:
    return _record(a, b, ctx, checks, outcome, reason)


def _entity_name(claim: ClaimRecord) -> str:
    return claim.subject.mention or claim.subject.entity_id or "unresolved"


def gate(a: ClaimRecord, b: ClaimRecord, ctx: GateContext) -> ComparisonRecord:
    checks: list[GateCheck] = []
    cfg = ctx.config
    tz = cfg.case.plant_tz

    # ① same entity ------------------------------------------------------------------------
    same = (
        a.subject.link_status == "resolved"
        and b.subject.link_status == "resolved"
        and a.subject.entity_id is not None
        and a.subject.entity_id == b.subject.entity_id
    )
    detail = (
        f"{_entity_name(a)} = {_entity_name(b)} ({a.subject.entity_id})"
        if same
        else "entities differ or are not resolved"
    )
    checks.append(_check(1, "same_entity", same, detail))
    if not same:
        return _stop(
            a,
            b,
            ctx,
            checks,
            "cant_compare",
            "They can't be compared: different or unresolved entity",
        )

    # Orient: text side (quantifier phrase) and sensor side (day-level state).
    text, sensor = (a, b) if a.modality == "text" else (b, a)
    rule: PhraseRule | None = phrase_rule_for(text, cfg) if text.modality == "text" else None
    state: SensorState | None = sensor_state_of(sensor)

    # ② same attribute ---------------------------------------------------------------------
    attr_ok = rule is not None and state is not None and rule.attribute_group == sensor.attribute
    attr_detail = (
        f"'{rule.phrase}' ({rule.quantifier}: all channels in scope + no error events)"
        f" <-> {sensor.attribute}"
        if attr_ok and rule is not None
        else f"no comparable attribute mapping between {a.attribute} and {b.attribute}"
    )
    checks.append(_check(2, "same_attribute", attr_ok, attr_detail))
    if not attr_ok or rule is None or state is None:
        return _stop(
            a, b, ctx, checks, "cant_compare", "They can't be compared: attributes do not map"
        )

    # ③ time overlap, same granularity -------------------------------------------------------
    ta, tb = text.temporal.valid_time, sensor.temporal.valid_time
    if not isinstance(ta, Interval) or not isinstance(tb, Interval):
        checks.append(_check(3, "time_overlap", False, "time unknown on at least one side"))
        return _stop(a, b, ctx, checks, "cant_compare", "They can't be compared: time unknown")
    overlap = max(ta.start, tb.start) < min(ta.end, tb.end)
    same_granularity = ta.granularity == tb.granularity
    if not (overlap and same_granularity):
        why = (
            "intervals do not overlap"
            if not overlap
            else (f"granularity {ta.granularity} vs {tb.granularity}")
        )
        checks.append(_check(3, "time_overlap", False, why))
        return _stop(a, b, ctx, checks, "cant_compare", f"They can't be compared: {why}")
    day = local_date(ta.start, tz).strftime("%d %b %Y")
    checks.append(
        _check(
            3, "time_overlap", True, f"both cover {day} (plant-local), {ta.granularity} granularity"
        )
    )

    # ④ comparable terms -----------------------------------------------------------------------
    env: Envelope | None = next(
        (e for e in ctx.envelopes if e.envelope_id == state.pointer.envelope_id), None
    )
    terms_ok = (
        env is not None
        and sensor.unit_status == "sensor_native"
        and state.pointer.series_id == env.series_id
        and state.pointer.statistic == env.statistic
        and state.pointer.granularity == env.granularity
        and text.unit_status == "not_applicable"
    )
    if not terms_ok or env is None:
        checks.append(
            _check(
                4, "comparable_terms", False, "statistic, series or units do not match the envelope"
            )
        )
        return _stop(
            a, b, ctx, checks, "cant_compare", "They can't be compared: terms do not match"
        )
    checks.append(
        _check(
            4,
            "comparable_terms",
            True,
            f"sensor_native series {env.series_id}; statistic {env.statistic}/{env.granularity} "
            "matches the envelope",
        )
    )

    # ⑤ data on both sides -----------------------------------------------------------------------
    text_ev = text.evidence
    have_text = isinstance(text_ev, TextSpanPointer) and bool(text_ev.quote)
    have_sensor = state.pointer.n_points > 0
    if not (have_text and have_sensor):
        checks.append(_check(5, "data_both_sides", False, "no data on at least one side"))
        return _stop(a, b, ctx, checks, "cant_tell", "We can't tell: data missing")
    checks.append(
        _check(
            5,
            "data_both_sides",
            True,
            f"note present; {state.pointer.n_points} of {state.pointer.expected_points} readings "
            "present",
        )
    )

    # ⑥ beyond normal variation: apply the quantifier ---------------------------------------------
    numbers = f"T_D {_fmt(state.t_d)} vs T* {_fmt(state.t_star)} (envelope {env.envelope_id})"
    if rule.quantifier != "forall":
        checks.append(
            _check(6, "beyond_variation", False, "exists-quantifier phrases arrive in M3")
        )
        return _stop(
            a,
            b,
            ctx,
            checks,
            "cant_compare",
            "They can't be compared: quantifier not supported yet",
        )
    if state.violated:
        checks.append(_check(6, "beyond_variation", True, f"{numbers}: violation observed"))
        return _record(
            a,
            b,
            ctx,
            checks,
            "disagree",
            f"∀ claim '{rule.phrase}' violated: robust max-z {_fmt(state.t_d)} is above the alarm "
            f"band threshold {_fmt(state.t_star)}",
        )
    if state.full_coverage:
        checks.append(
            _check(6, "beyond_variation", True, f"{numbers}: no violation, 100% coverage")
        )
        return _record(
            a,
            b,
            ctx,
            checks,
            "agree",
            f"∀ claim '{rule.phrase}' held: robust max-z {_fmt(state.t_d)} within threshold "
            f"{_fmt(state.t_star)} with 100% coverage",
        )
    checks.append(
        _check(6, "beyond_variation", False, f"{numbers}: {state.missing_points} readings missing")
    )
    return _record(
        a,
        b,
        ctx,
        checks,
        "cant_tell",
        f"We can't tell (partial: {state.missing_points} of {state.pointer.expected_points} "
        "readings missing); no data is never normal",
    )
