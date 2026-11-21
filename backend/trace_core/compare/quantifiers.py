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

    @property
    def violated(self) -> bool:
        return self.t_d > self.t_star

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
    return SensorState(state=str(state), t_d=float(t_d), t_star=float(t_star), pointer=ev)
