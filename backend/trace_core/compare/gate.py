"""The six-check Comparability Gate (B-08 minimal; SYSTEM_DESIGN 7.1).

Checks are evaluated in order and recorded in order; evaluation stops at the first check that
cannot pass. Failing 1-4 gives "cant_compare", failing 5 gives "cant_tell", and check 6 applies the
phrase quantifier. Supported pairing in M2: a text claim with a quantifier phrase against a
day-level sensor state claim. Everything else fails closed as "cant_compare".

Error/failure/maintenance rows inside the window violate a ∀ phrase, and "agree" also needs a
declared log coverage of the window. Two numbers in the same unit are judged by the documented
tolerance (`_numeric_pair`).
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
from trace_core.normalise.time import local_date, overlaps
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


def _unit_vs_telemetry(
    a: ClaimRecord, b: ClaimRecord, ctx: GateContext, checks: list[GateCheck]
) -> ComparisonRecord | None:
    """Checks 2-4 for a documented physical unit vs `sensor_native` telemetry (PRD 10.5)."""
    if {a.unit_status, b.unit_status} != {"known", "sensor_native"}:
        return None
    same_attribute = a.attribute == b.attribute
    checks.append(_check(2, "same_attribute", same_attribute, f"{a.attribute} vs {b.attribute}"))
    if not same_attribute:
        return _stop(
            a, b, ctx, checks, "cant_compare", "They can't be compared: attributes do not map"
        )
    ta, tb = a.temporal.valid_time, b.temporal.valid_time
    if (
        not isinstance(ta, Interval)
        or not isinstance(tb, Interval)
        or not max(ta.start, tb.start) < min(ta.end, tb.end)
    ):
        checks.append(_check(3, "time_overlap", False, "time unknown or intervals do not overlap"))
        return _stop(
            a, b, ctx, checks, "cant_compare", "They can't be compared: time does not overlap"
        )
    checks.append(_check(3, "time_overlap", True, "valid times overlap"))
    checks.append(
        _check(
            4,
            "comparable_terms",
            False,
            "physical unit vs telemetry in undocumented sensor units: never converted",
        )
    )
    return _stop(
        a, b, ctx, checks, "cant_compare", "They can't be compared: telemetry unit undocumented"
    )


def _exists(
    a: ClaimRecord,
    b: ClaimRecord,
    ctx: GateContext,
    checks: list[GateCheck],
    rule: PhraseRule,
    state: SensorState,
    numbers: str,
) -> ComparisonRecord:
    """∃ phrase (PRD 10.4): agree if a violation on the phrase's side is observed; disagree only
    with full coverage and no violation; otherwise we can't tell. Missing data never disagrees."""
    side = rule.side if rule.side in ("upper", "lower") else "both"
    hit = state.violated_on(side)
    if hit:
        checks.append(_check(6, "beyond_variation", True, f"{numbers}: {side} violation observed"))
        return _record(
            a,
            b,
            ctx,
            checks,
            "agree",
            f"∃ claim '{rule.phrase}' observed: robust z {_fmt(state.t_d)} is above the alarm "
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
            "disagree",
            f"∃ claim '{rule.phrase}' not observed: robust z {_fmt(state.t_d)} stays within "
            f"threshold {_fmt(state.t_star)} with 100% coverage",
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


EVENT_ATTRIBUTES = frozenset({"error_event", "failure_event", "maintenance_action"})


def _events_in_window(text: ClaimRecord, window: Interval, ctx: GateContext) -> list[ClaimRecord]:
    """Event rows of the same machine whose hour lies inside the claim's half-open window."""
    entity = text.subject.entity_id
    out: list[ClaimRecord] = []
    for event in ctx.events:
        vt = event.temporal.valid_time
        if (
            event.subject.entity_id == entity
            and event.attribute in EVENT_ATTRIBUTES
            and isinstance(vt, Interval)
            and max(vt.start, window.start) < min(vt.end, window.end)
        ):
            out.append(event)
    return sorted(out, key=lambda e: e.claim_id)


def _logs_cover(window: Interval, ctx: GateContext) -> bool:
    """True only if a declared coverage period contains the whole window (half-open)."""
    return any(p.start <= window.start and window.end <= p.end for p in ctx.log_coverage)


def _number(claim: ClaimRecord) -> tuple[float, str] | None:
    """The comparable number of a claim: the normalised value in its canonical unit when there
    is one, else the raw value with its own unit. None when it is not a number with a unit."""
    if claim.value_type != "numeric" or claim.unit_status != "known":
        return None
    value = claim.normalized_value if claim.normalized_value is not None else claim.value
    unit = claim.normalized_unit if claim.normalized_unit is not None else claim.unit
    if isinstance(value, bool) or not isinstance(value, int | float) or unit is None:
        return None
    return float(value), unit


def _numeric_pair(
    a: ClaimRecord, b: ClaimRecord, ctx: GateContext, checks: list[GateCheck]
) -> ComparisonRecord | None:
    """numeric vs numeric (PRD 10.5): disagree iff |a - b| > max(abs_tol, rel_tol * |ref|,
    resolution_a + resolution_b). Tolerances come from the config (sensor datasheets); without
    one for the attribute nothing is judged. Different units cannot be compared."""
    first, second = _number(a), _number(b)
    if first is None or second is None:
        return None
    tz = ctx.config.case.plant_tz
    same_attribute = a.attribute == b.attribute
    checks.append(_check(2, "same_attribute", same_attribute, f"{a.attribute} vs {b.attribute}"))
    if not same_attribute:
        return _stop(
            a, b, ctx, checks, "cant_compare", "They can't be compared: attributes do not map"
        )
    ta, tb = a.temporal.valid_time, b.temporal.valid_time
    if (
        not isinstance(ta, Interval)
        or not isinstance(tb, Interval)
        or not max(ta.start, tb.start) < min(ta.end, tb.end)
        or ta.granularity != tb.granularity
    ):
        checks.append(_check(3, "time_overlap", False, "time unknown, apart, or different grain"))
        return _stop(
            a, b, ctx, checks, "cant_compare", "They can't be compared: time does not overlap"
        )
    day = local_date(max(ta.start, tb.start), tz).strftime("%d %b %Y")
    checks.append(_check(3, "time_overlap", True, f"both cover {day} (plant-local)"))
    tolerance = next((t for t in ctx.config.tolerances if t.attribute == a.attribute), None)
    if first[1] != second[1] or tolerance is None:
        why = (
            f"units differ ({first[1]} vs {second[1]})"
            if first[1] != second[1]
            else f"no documented tolerance for {a.attribute}"
        )
        checks.append(_check(4, "comparable_terms", False, why))
        return _stop(
            a, b, ctx, checks, "cant_compare", "They can't be compared: terms do not match"
        )
    checks.append(
        _check(4, "comparable_terms", True, f"same unit {first[1]}; tolerance documented")
    )
    checks.append(_check(5, "data_both_sides", True, "a number on both sides"))
    limit = max(
        tolerance.abs_tol,
        tolerance.rel_tol * abs(first[0]),
        2 * tolerance.resolution,
    )
    gap = abs(first[0] - second[0])
    detail = f"|a - b| = {gap:.6g} {first[1]} vs allowed {limit:.6g}"
    checks.append(_check(6, "beyond_variation", True, detail))
    if gap > limit:
        return _record(
            a, b, ctx, checks, "disagree", f"The numbers differ beyond tolerance: {detail}"
        )
    return _record(a, b, ctx, checks, "agree", f"The numbers agree within tolerance: {detail}")


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

    # A physical unit against undocumented telemetry units can never be compared (promise 5).
    mismatch = _unit_vs_telemetry(a, b, ctx, checks)
    if mismatch is not None:
        return mismatch

    # Two authored numbers in the same physical unit: the tolerance rule (PRD 10.5).
    numeric = _numeric_pair(a, b, ctx, checks)
    if numeric is not None:
        return numeric

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
    overlap = overlaps(ta, tb)
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
        and sorted(env.scope) == sorted(rule.scope_channels)  # the envelope of the phrase's scope
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
    if rule.quantifier == "exists":
        return _exists(a, b, ctx, checks, rule, state, numbers)
    logged = _events_in_window(text, ta, ctx)
    if state.violated or logged:
        why = (
            f"{numbers}: violation observed"
            if state.violated
            else f"{len(logged)} error/failure/maintenance event(s) logged in the window"
        )
        checks.append(_check(6, "beyond_variation", True, why))
        reason = (
            f"∀ claim '{rule.phrase}' violated: robust max-z {_fmt(state.t_d)} is above the "
            f"alarm band threshold {_fmt(state.t_star)}"
            if state.violated
            else f"∀ claim '{rule.phrase}' violated: {len(logged)} error/failure/maintenance "
            "event(s) logged in the window"
        )
        return _record(a, b, ctx, checks, "disagree", reason)
    covered = _logs_cover(ta, ctx)
    if state.full_coverage and not covered:
        checks.append(
            _check(6, "beyond_variation", False, f"{numbers}: event logs do not cover the window")
        )
        return _record(
            a,
            b,
            ctx,
            checks,
            "cant_tell",
            "We can't tell: no event log declares coverage of the whole window; "
            "no data is never normal",
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
