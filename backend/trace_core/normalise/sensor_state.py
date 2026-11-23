"""Sensor state derivation (B-03 minimal): S-88 (day) and its hour-level child S-88.1.

Everything shown is computed here from the window claims and the learned envelope:
`T_D = max |z|` over the day's readings, compared with the conformal `T*` (PRD 10.3).
`value` of the day claim is structured (`state`, `T_D`, `T_star`) because the frozen
`SensorWindowPointer` has no field for the two numbers the gate and the card must show.

Unexplained flatline hours (normalise/gaps.py) do not count as coverage.
TODO(M3): partial-day statements and per-shift windows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from trace_core.canonical import canonical_sha256
from trace_core.ids import build_claim
from trace_core.models.claims import ClaimRecord, Confidence, Method, Subject
from trace_core.models.config import ConfigBundle
from trace_core.models.evidence import SensorWindowPointer
from trace_core.models.records import Envelope
from trace_core.models.time import Interval, ObservedTime, Temporal
from trace_core.normalise.envelopes import MAD_TO_SIGMA, STATISTIC, robust_z
from trace_core.normalise.time import hour_interval, local_date, local_hhmm
from trace_core.read.sensor import CHANNEL_ATTRIBUTE, RAW_STATISTIC
from trace_core.stage_types import SensorWindows

STATE_RULE = "state.abnormal_if_robust_max_z_gt_conformal_q95"
EXCURSION_RULE = "excursion.hourly_peak"


@dataclass(frozen=True)
class _Reading:
    z: float
    channel: str
    ts: str
    value: float
    window: ClaimRecord


def _fmt(x: float) -> str:
    return f"{x:.2f}"


def _pointer(claim: ClaimRecord) -> SensorWindowPointer:
    ev = claim.evidence
    if not isinstance(ev, SensorWindowPointer):
        raise TypeError("sensor claim without a sensor window pointer")
    return ev


def derive_sensor_state(
    windows: SensorWindows, envelopes: Sequence[Envelope], cfg: ConfigBundle
) -> list[ClaimRecord]:
    tz = cfg.case.plant_tz
    groups: dict[tuple[str, str, str], list[ClaimRecord]] = {}
    for claim in windows.claims:
        ev = claim.evidence
        entity = claim.subject.entity_id
        if (
            isinstance(ev, SensorWindowPointer)
            and ev.statistic == RAW_STATISTIC
            and entity is not None
            and isinstance(claim.value, dict)
        ):
            groups.setdefault((entity, ev.series_id, ev.start), []).append(claim)
    out: list[ClaimRecord] = []
    for (entity, series, _start), members in sorted(groups.items()):
        flat = [g for g in windows.gap_claims if _is_flatline(g, entity)]
        every = {_pointer(c).channels[0] for c in members}
        for env in sorted(envelopes, key=lambda e: (-len(e.scope), e.envelope_id)):
            if env.machine != entity or env.series_id != series:
                continue  # no envelope, no state claim (fail closed)
            scoped = [c for c in members if _pointer(c).channels[0] in env.scope]
            if not scoped:
                continue
            primary = set(env.scope) == every
            if not primary and len(env.scope) != 1:
                continue  # only the all-channel and single-channel scopes are judged
            out.extend(
                _day_claims(
                    entity,
                    env,
                    sorted(scoped, key=lambda c: c.claim_id),
                    cfg,
                    tz,
                    flat,
                    primary=primary,
                )
            )
    return out


def _is_flatline(gap: ClaimRecord, entity: str) -> bool:
    return (
        gap.subject.entity_id == entity
        and gap.attribute == "data_availability"
        and gap.value == "flatline"
        and isinstance(gap.evidence, SensorWindowPointer)
    )


def _flat_hours(flat: Sequence[ClaimRecord], channel: str, start: str, end: str) -> int:
    """Hours of `channel` inside [start, end) covered by an unexplained flatline: the readings
    are present but frozen, so they do not count as coverage (no data is never normal)."""
    total = 0
    for gap in flat:
        ev = gap.evidence
        if isinstance(ev, SensorWindowPointer) and ev.channels == [channel]:
            total += ev.expected_points if start <= ev.start and ev.end <= end else 0
    return total


def _day_claims(
    entity: str,
    env: Envelope,
    members: list[ClaimRecord],
    cfg: ConfigBundle,
    tz: str,
    flat: Sequence[ClaimRecord] = (),
    *,
    primary: bool = True,
) -> list[ClaimRecord]:
    live = [c for c in env.scope if c not in env.degenerate_channels]
    scored: list[_Reading] = []
    n_points = 0
    expected = 0
    for claim in members:
        ev = _pointer(claim)
        channel = ev.channels[0]
        n_points += max(0, ev.n_points - _flat_hours(flat, channel, ev.start, ev.end))
        expected += ev.expected_points
        if channel not in live or not isinstance(claim.value, dict):
            continue
        for ts, reading in claim.value.items():
            if not isinstance(reading, float | int):
                raise TypeError("window readings must be numeric")
            value = float(reading)
            scored.append(
                _Reading(
                    robust_z(value, env.med[channel], env.mad[channel]), channel, ts, value, claim
                )
            )
    if not scored or expected == 0:
        return []  # no data: a GapClaim covers it, never a state
    first = members[0]
    first_ev = _pointer(first)
    vt = first.temporal.valid_time
    if not isinstance(vt, Interval):
        raise TypeError("window claims have an interval")
    peak = max(scored, key=lambda r: (r.z, r.channel, r.ts))
    t_d = peak.z
    abnormal = t_d > env.T_star
    coverage = n_points / expected
    p_value = (1 + sum(1 for q in env.quiet_days if q.t_d >= t_d)) / (env.n + 1)
    history = 1.0 if env.pooled == "none" else cfg.envelope.thin_history_factor
    confidence = Confidence(
        value=(1.0 - p_value) * coverage * history,
        calibrated=False,
        components={
            "conformal_1_minus_p": 1.0 - p_value,
            "coverage": coverage,
            "history_factor": history,
        },
        stage="pre",
        note="uncalibrated: (1 - conformal p-value) x coverage x history factor",
    )
    day_text = local_date(vt.start, tz).strftime("%d %b %Y")
    subject = Subject(entity_id=entity, link_status="resolved")
    window_ids = sorted(c.claim_id for c in members)
    state = "abnormal" if abnormal else "normal"
    where = "outside" if abnormal else "inside"
    comparator = ">" if abnormal else "<="
    statement = (
        f"{entity} operating state on {day_text} was {where} its learned alarm band "
        f"(robust max-z T_D = {_fmt(t_d)} {comparator} T* = {_fmt(env.T_star)})"
    )
    if abnormal:
        statement += (
            f"; largest excursion: {peak.channel} {_fmt(peak.value)} at {local_hhmm(peak.ts, tz)}"
        )
    if primary:
        attribute = "operating_state"
        state_value: dict[str, float | str] = {"state": state, "T_D": t_d, "T_star": env.T_star}
    else:
        channel = env.scope[0]
        attribute = CHANNEL_ATTRIBUTE.get(channel, channel)
        signed = [(r.value - env.med[channel]) / (MAD_TO_SIGMA * env.mad[channel]) for r in scored]
        state_value = {
            "state": state,
            "T_D": t_d,
            "T_star": env.T_star,
            "T_D_upper": max(signed),
            "T_D_lower": -min(signed),
        }
        statement = (
            f"{channel} of {entity} on {day_text} was {where} its learned alarm band "
            f"(robust max-z T_D = {_fmt(t_d)} {comparator} T* = {_fmt(env.T_star)})"
        )
    day_claim = build_claim(
        case_id=first.case_id,
        claim_type="inferred",
        statement=statement,
        subject=subject,
        attribute=attribute,
        value=state_value,
        value_type="structured",
        unit=None,
        unit_status="sensor_native",
        temporal=Temporal(
            valid_time=vt,
            observed_time=ObservedTime(at=vt.end, basis="sensor_timestamp"),
            timezone_original=tz,
        ),
        modality="sensor",
        evidence=SensorWindowPointer(
            source_id=first_ev.source_id,
            series_id=env.series_id,
            partition_sha256=env.partition_hashes[env.series_id],
            channels=sorted(_pointer(c).channels[0] for c in members),
            start=vt.start,
            end=vt.end,
            n_points=n_points,
            expected_points=expected,
            statistic=STATISTIC,
            granularity="day",
            window_sha256=canonical_sha256(sorted(_pointer(c).window_sha256 for c in members)),
            envelope_id=env.envelope_id,
        ),
        derived_from=[*window_ids, env.envelope_id],
        method=Method(extractor="envelope_check", extractor_version="1", rule_id=STATE_RULE),
        confidence=confidence,
    )
    result = [day_claim]
    if abnormal and primary:
        scale = MAD_TO_SIGMA * env.mad[peak.channel]
        band_low = env.med[peak.channel] - env.T_star * scale
        band_high = env.med[peak.channel] + env.T_star * scale
        hour = hour_interval(peak.ts, "computed_window")
        result.append(
            build_claim(
                case_id=first.case_id,
                claim_type="inferred",
                statement=(
                    f"{peak.channel} peaked at {_fmt(peak.value)} (sensor units, undocumented) "
                    f"at {local_hhmm(peak.ts, tz)}, outside the alarm band "
                    f"[{_fmt(band_low)}, {_fmt(band_high)}]"
                ),
                subject=subject,
                attribute=CHANNEL_ATTRIBUTE.get(peak.channel, peak.channel),
                value={
                    "channel": peak.channel,
                    "reading": peak.value,
                    "z": peak.z,
                    "band_low": band_low,
                    "band_high": band_high,
                },
                value_type="structured",
                unit=None,
                unit_status="sensor_native",
                temporal=Temporal(
                    valid_time=hour,
                    observed_time=ObservedTime(at=hour.end, basis="sensor_timestamp"),
                    timezone_original=tz,
                ),
                modality="sensor",
                evidence=SensorWindowPointer(
                    source_id=first_ev.source_id,
                    series_id=env.series_id,
                    partition_sha256=env.partition_hashes[env.series_id],
                    channels=[peak.channel],
                    start=hour.start,
                    end=hour.end,
                    n_points=1,
                    expected_points=1,
                    statistic="hourly_peak",
                    granularity="hour",
                    window_sha256=canonical_sha256(
                        {
                            "series": env.series_id,
                            "channel": peak.channel,
                            "ts": peak.ts,
                            "reading": peak.value,
                        }
                    ),
                    envelope_id=env.envelope_id,
                ),
                derived_from=[day_claim.claim_id, peak.window.claim_id, env.envelope_id],
                method=Method(
                    extractor="envelope_check", extractor_version="1", rule_id=EXCURSION_RULE
                ),
                confidence=confidence,
            )
        )
    return result
