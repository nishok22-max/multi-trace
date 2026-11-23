"""Envelope learning: split-conformal robust max-z (PRD 10.3, SYSTEM_DESIGN 7.2).

For machine m:
  1. quiet days Q: no error/maintenance/failure within +-margin days, telemetry 24/24 h on every
     channel, and outside the case window +-margin days (policy `all_except_case_window`);
  2. per channel: med_c and MAD_c over the hourly values of Q (MAD = 0 -> channel excluded);
     s_c = 1.4826 * MAD_c;
  3. day statistic T_d = max over channels and hours of |x - med_c| / s_c;
  4. T* = the k-th smallest T_d over Q, k = ceil((1 - alpha)(n + 1)).

Thin history (PRD 10.3 step 4): with n < `min_quiet_days_own_t_star`, T* is the conformal quantile
of the quiet-day statistics pooled over the same-model machines (the statistic is unitless); with
n < `min_quiet_days_own_scale` the per-channel median/MAD also come from the pooled model-level
readings. Peers come from `model_peers`; with none usable, `ThinHistoryError` (fail closed).

Log coverage (PRD 10.3 step 1): every event log must declare its `coverage_period` (else
`LogCoverageError`, problem `/problems/log-coverage`), and a day outside a log's coverage is never
quiet (a missing log must not read as "no events").

TODO(M3): the `before_only` policy.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

import numpy as np

from trace_core.errors import LogCoverageError, ThinHistoryError
from trace_core.ids import envelope_id
from trace_core.models.case import Case
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle, EnvelopeConfig, Ontology
from trace_core.models.records import CoveragePeriod, Envelope, QuietDay, Source
from trace_core.models.time import Interval
from trace_core.normalise.time import (
    MAX_TS,
    MIN_TS,
    days_between,
    hours_in,
    local_date,
    local_day_bounds,
)
from trace_core.ports import TelemetryReader
from trace_core.read.sensor import TS, telemetry_series_id
from trace_core.read.table import EVENT_ATTRIBUTE_NAMES

MAD_TO_SIGMA = 1.4826
"""Normal-consistency factor of the median absolute deviation (PRD 10.3)."""
QUIET_REASONS = ["no_event_within_margin", "telemetry_24_of_24", "outside_case_window"]
STATISTIC = "robust_max_z"
Pooling = Literal["none", "t_star_model", "model_level"]


def robust_z(value: float, med: float, mad: float) -> float:
    """|x - med| / (1.4826 * MAD). Callers exclude degenerate channels (MAD = 0)."""
    return abs(value - med) / (MAD_TO_SIGMA * mad)


def conformal_rank(n: int, alpha: float) -> int:
    """k = ceil((1 - alpha)(n + 1)), exact in decimal (no float rounding at the boundary)."""
    return math.ceil((Decimal(1) - Decimal(str(alpha))) * (n + 1))


def event_days(events: Sequence[ClaimRecord], entity: str, tz: str) -> set[date]:
    out: set[date] = set()
    for claim in events:
        vt = claim.temporal.valid_time
        if (
            claim.subject.entity_id == entity
            and claim.attribute in EVENT_ATTRIBUTE_NAMES
            and isinstance(vt, Interval)
        ):
            out.add(local_date(vt.start, tz))
    return out


def _day_readings(
    data: dict[str, list[Any]], channels: list[str], tz: str
) -> dict[date, dict[str, dict[str, float]]]:
    """date -> channel -> {utc hour: reading}. Conflicting duplicates are dropped, never merged."""
    seen: dict[date, dict[str, dict[str, set[float]]]] = {}
    for index, ts in enumerate(data[TS]):
        day = local_date(str(ts), tz)
        for channel in channels:
            value = data[channel][index]
            if value is not None:
                per = seen.setdefault(day, {}).setdefault(channel, {})
                per.setdefault(str(ts), set()).add(float(value))
    return {
        day: {
            ch: {ts: next(iter(vals)) for ts, vals in per.items() if len(vals) == 1}
            for ch, per in chans.items()
        }
        for day, chans in seen.items()
    }


@dataclass(frozen=True)
class _Machine:
    entity: str
    series: str
    channels: list[str]
    by_day: dict[date, dict[str, dict[str, float]]]
    quiet: list[date]


def _prepare(
    telemetry: TelemetryReader,
    events: Sequence[ClaimRecord],
    case_days: Sequence[date],
    cfg: ConfigBundle,
    entity: str,
    coverage: Sequence[CoveragePeriod] = (),
) -> _Machine:
    tz = cfg.case.plant_tz
    margin = timedelta(days=cfg.envelope.margin_days)
    series = telemetry_series_id(entity)
    data = telemetry.read(series, MIN_TS, MAX_TS).to_pydict()
    channels = sorted(c for c in data if c != TS)
    by_day = _day_readings(data, channels, tz)
    events_on = event_days(events, entity, tz)
    quiet: list[date] = []
    for day in sorted(by_day):
        start, end = local_day_bounds(day, tz)
        expected = len(hours_in(start, end))
        full = all(len(by_day[day].get(ch, {})) == expected for ch in channels)
        near_event = any(abs(day - e) <= margin for e in events_on)
        near_case = any(abs(day - c) <= margin for c in case_days)
        logged = all(p.start <= start and end <= p.end for p in coverage)
        if full and logged and not near_event and not near_case:
            quiet.append(day)
    return _Machine(entity, series, channels, by_day, quiet)


def _centre_scale(
    machines: Sequence[_Machine], channels: Sequence[str]
) -> tuple[dict[str, float], dict[str, float]]:
    med: dict[str, float] = {}
    mad: dict[str, float] = {}
    for ch in channels:
        values = np.array(
            [v for m in machines for d in m.quiet for v in m.by_day[d][ch].values()], dtype=float
        )
        med[ch] = float(np.median(values))
        mad[ch] = float(np.median(np.abs(values - med[ch])))
    return med, mad


def _day_stats(
    machine: _Machine, med: dict[str, float], mad: dict[str, float], live: Sequence[str]
) -> dict[date, float]:
    return {
        d: max(robust_z(v, med[ch], mad[ch]) for ch in live for v in machine.by_day[d][ch].values())
        for d in machine.quiet
    }


def _log_coverage(sources: Sequence[Source]) -> list[CoveragePeriod]:
    """Declared coverage of every event log; an undeclared log refuses the build."""
    out: list[CoveragePeriod] = []
    for src in sources:
        if src.modality != "table" or src.held_reason is not None:
            continue
        if src.coverage_period is None:
            raise LogCoverageError(f"event log {src.source_id} declares no coverage period")
        out.append(src.coverage_period)
    return out


def _live(channels: Sequence[str], mad: Mapping[str, float]) -> list[str]:
    return [ch for ch in channels if mad[ch] != 0.0]


def learn_envelopes(
    telemetry: TelemetryReader,
    events: Sequence[ClaimRecord],
    sources: Sequence[Source],
    case: Case,
    ontology: Ontology,
    cfg: ConfigBundle,
    model_peers: Mapping[str, Sequence[str]] | None = None,
) -> list[Envelope]:
    """Per machine. `model_peers` maps a machine to the other machines of its model."""
    params = cfg.envelope
    if params.training_policy != "all_except_case_window":
        raise NotImplementedError("M3")  # before_only
    tz = cfg.case.plant_tz
    case_days = days_between(case.window_start, case.window_end, tz)
    coverage = _log_coverage(sources)
    out: list[Envelope] = []
    for entity in sorted(case.entities):
        own = _prepare(telemetry, events, case_days, cfg, entity, coverage)
        n = len(own.quiet)
        channels = own.channels
        pooled: Pooling = "none"
        members: list[str] = []
        if n >= params.min_quiet_days_own_t_star and n >= params.min_quiet_days_own_scale:
            med, mad = _centre_scale([own], channels)
            t_d = _day_stats(own, med, mad, _live(channels, mad))
            pool_stats = list(t_d.values())
        else:
            peers: list[_Machine] = []
            for peer_id in sorted((model_peers or {}).get(entity, ())):
                if peer_id == entity:
                    continue
                try:
                    peer = _prepare(telemetry, events, case_days, cfg, peer_id, coverage)
                except FileNotFoundError:
                    continue  # a peer without telemetry cannot contribute
                if peer.channels == channels and peer.quiet:
                    peers.append(peer)
            if not peers:
                raise ThinHistoryError("thin history and no usable same-model machines")
            members = [p.entity for p in peers]
            if n < params.min_quiet_days_own_scale:
                pooled = "model_level"
                med, mad = _centre_scale([own, *peers], channels)
                live = _live(channels, mad)
                stats = {m.entity: _day_stats(m, med, mad, live) for m in (own, *peers)}
            else:
                pooled = "t_star_model"
                med, mad = _centre_scale([own], channels)
                stats = {own.entity: _day_stats(own, med, mad, _live(channels, mad))}
                for peer in peers:  # the statistic is unitless: each peer uses its own scale
                    pmed, pmad = _centre_scale([peer], channels)
                    stats[peer.entity] = _day_stats(peer, pmed, pmad, _live(channels, pmad))
            t_d = stats[own.entity]
            pool_stats = [v for k in sorted(stats) for v in stats[k].values()]
        ranked = sorted(pool_stats)
        k = conformal_rank(len(ranked), params.alpha)
        if not ranked or k > len(ranked):
            raise ThinHistoryError("too few quiet days for the configured alpha")
        partition = {own.series: telemetry.partition_sha(own.series)}
        out.append(
            _envelope(
                own, channels, med, mad, t_d, ranked[k - 1], pooled, members, params, partition
            )
        )
        if pooled == "none":
            out.extend(_scope_envelopes(own, med, mad, ontology, params, partition))
    return out


def _envelope(
    own: _Machine,
    scope: Sequence[str],
    med: dict[str, float],
    mad: dict[str, float],
    t_d: Mapping[date, float],
    t_star: float,
    pooled: Pooling,
    members: Sequence[str],
    params: EnvelopeConfig,
    partition: dict[str, str],
) -> Envelope:
    return Envelope(
        envelope_id=envelope_id(
            own.entity,
            own.series,
            scope,
            STATISTIC,
            "day",
            [d.isoformat() for d in own.quiet],
            params,
            members,
            partition,
        ),
        machine=own.entity,
        series_id=own.series,
        scope=list(scope),
        quiet_days=[
            QuietDay(date=d.isoformat(), reasons=list(QUIET_REASONS), t_d=t_d[d]) for d in own.quiet
        ],
        n=len(own.quiet),
        med={ch: med[ch] for ch in scope},
        mad={ch: mad[ch] for ch in scope},
        T_star=t_star,
        pooled=pooled,
        pool_members=list(members),
        degenerate_channels=[ch for ch in scope if mad[ch] == 0.0],
        params=params,
        partition_hashes=partition,
    )


def _scope_envelopes(
    own: _Machine,
    med: dict[str, float],
    mad: dict[str, float],
    ontology: Ontology,
    params: EnvelopeConfig,
    partition: dict[str, str],
) -> list[Envelope]:
    """One envelope per single-channel phrase scope (a statement about vibration alone is
    judged against vibration alone, never against the all-channel family: PRD 10.4 scope).
    The conformal construction is the same, over the scope's channels only."""
    scopes = sorted(
        {
            rule.scope_channels[0]
            for rule in ontology.phrases
            if len(rule.scope_channels) == 1 and rule.scope_channels[0] in own.channels
        }
    )
    out: list[Envelope] = []
    for channel in scopes:
        if mad[channel] == 0.0:
            continue  # degenerate scale: no band to judge against
        t_d = _day_stats(own, med, mad, [channel])
        ranked = sorted(t_d.values())
        k = conformal_rank(len(ranked), params.alpha)
        if not ranked or k > len(ranked):
            continue  # too few quiet days for this alpha: no envelope, so no verdict
        out.append(
            _envelope(own, [channel], med, mad, t_d, ranked[k - 1], "none", [], params, partition)
        )
    return out
