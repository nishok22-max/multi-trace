"""Qualitative phrase -> quantifier rule (PRD 10.4) and typed views of the claims the gate reads."""

from __future__ import annotations

from dataclasses import dataclass

from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle, PhraseRule
from trace_core.models.evidence import SensorWindowPointer

_PHRASE_PREFIX = "phrase."
_STATE_PREFIX = "state."


def phrase_rule_for(claim: ClaimRecord, cfg: ConfigBundle) -> PhraseRule | None:
    """The ontology rule that produced a text claim (by `method.rule_id = phrase.<class>`)."""
    rule_id = claim.method.rule_id or ""
    if not rule_id.startswith(_PHRASE_PREFIX):
        return None
    phrase_class = rule_id[len(_PHRASE_PREFIX) :]
    return next((r for r in cfg.ontology.phrases if r.phrase_class == phrase_class), None)


@dataclass(frozen=True)
class SensorState:
    """The numbers of a day-level sensor state claim (all computed by derive_sensor_state)."""

    state: str
    t_d: float
    t_star: float
    pointer: SensorWindowPointer
    t_upper: float | None = None
    t_lower: float | None = None

    @property
    def violated(self) -> bool:
        return self.t_d > self.t_star

    def violated_on(self, side: str) -> bool:
        """Violation on one side of the band. A one-sided check uses the signed statistic and
        the same threshold T* (an upper excursion above T* is also a two-sided one, so the
        false-alarm bound still holds). Without the signed value it falls back to two-sided."""
        if side == "upper" and self.t_upper is not None:
            return self.t_upper > self.t_star
        if side == "lower" and self.t_lower is not None:
            return self.t_lower > self.t_star
        return self.violated

    @property
    def missing_points(self) -> int:
        return self.pointer.expected_points - self.pointer.n_points

    @property
    def full_coverage(self) -> bool:
        return self.pointer.expected_points > 0 and self.missing_points == 0


def sensor_state_of(claim: ClaimRecord) -> SensorState | None:
    ev = claim.evidence
    value = claim.value
    if (
        not isinstance(ev, SensorWindowPointer)
        or not isinstance(value, dict)
        or not (claim.method.rule_id or "").startswith(_STATE_PREFIX)
    ):
        return None
    t_d, t_star, state = value.get("T_D"), value.get("T_star"), value.get("state")
    if not isinstance(t_d, float | int) or not isinstance(t_star, float | int):
        return None
    upper, lower = value.get("T_D_upper"), value.get("T_D_lower")
    return SensorState(
        state=str(state),
        t_d=float(t_d),
        t_star=float(t_star),
        pointer=ev,
        t_upper=float(upper) if isinstance(upper, float | int) else None,
        t_lower=float(lower) if isinstance(lower, float | int) else None,
    )
