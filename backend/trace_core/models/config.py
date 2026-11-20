"""ConfigBundle: every tunable in one hashed object (IMPLEMENTATION_PLAN C.1, SYSTEM_DESIGN 9).

`config_hash = sha256(JCS(bundle))` lives in `trace_core.ids.config_hash`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from trace_core.models.base import CoreModel, EntityId

Quantifier = Literal["forall", "exists"]
TrainingPolicy = Literal["all_except_case_window", "before_only"]
LlmMode = Literal["off", "record", "replay"]
H0Decision = Literal["real_day", "another_real_day", "planted"]


class Shift(CoreModel):
    name: str
    start_hour: int = Field(ge=0, le=24)
    end_hour: int = Field(ge=0, le=24)


class WorkingCalendar(CoreModel):
    working_weekdays: list[int]  # 0 = Monday
    holidays: list[str] = Field(default_factory=list)  # plant-local dates YYYY-MM-DD
    escalation_working_days: int = Field(ge=1)


class CaseConfig(CoreModel):
    plant_tz: str
    shifts: list[Shift]
    calendar: WorkingCalendar
    h0_decision: H0Decision | None = None


class AttributeDef(CoreModel):
    name: str
    dimension: str
    canonical_unit: str | None = None  # None: no documented canonical unit (never guessed)
    telemetry_sensor_native: bool = False  # MS telemetry for this attribute is never converted


class PhraseRule(CoreModel):
    """Qualitative phrase -> class, quantifier, attribute group, scope channels (PRD 10.4)."""

    phrase: str
    phrase_class: str
    quantifier: Quantifier
    attribute_group: str
    scope_channels: list[str]
    side: Literal["both", "upper", "lower"] = "both"


class Ontology(CoreModel):
    attributes: list[AttributeDef]
    phrases: list[PhraseRule]


class AliasEntry(CoreModel):
    entity_id: EntityId
    canonical_name: str
    aliases: list[str]


class Tolerance(CoreModel):
    attribute: str
    abs_tol: float = Field(ge=0)
    rel_tol: float = Field(ge=0)
    resolution: float = Field(ge=0)


class Gauge(CoreModel):
    gauge_id: str
    attribute: str
    unit: str
    min_value: float
    max_value: float


class EnvelopeConfig(CoreModel):
    alpha: float = Field(gt=0, lt=1)
    margin_days: int = Field(ge=0)
    training_policy: TrainingPolicy
    flatline_epsilon_factor: float = Field(gt=0)  # eps = factor * s_c
    flatline_min_hours: int = Field(ge=1)
    min_quiet_days_own_t_star: int = Field(ge=1)  # n < this pools T* across the model
    min_quiet_days_own_scale: int = Field(ge=1)  # n < this pools med/s_c too
    drift_ratio: float = Field(gt=0)
    thin_history_factor: float = Field(gt=0, le=1)


class GateConfig(CoreModel):
    tau_link: float = Field(ge=0, le=1)
    delta_link: float = Field(ge=0, le=1)
    tau_review: float = Field(ge=0, le=1)
    lambda_corroboration: float = Field(ge=0)
    min_coverage: float = Field(ge=0, le=1)
    cadence_hours: int = Field(ge=1)
    image_extractor_prior: float = Field(ge=0, le=1)
    text_extractor_prior: float = Field(ge=0, le=1)


class LlmConfig(CoreModel):
    llm_mode: LlmMode = "off"
    vlm_mode: LlmMode = "off"
    text_model: str | None = None  # model IDs come from env/config, never hard-coded
    vision_model: str | None = None
    max_calls: int = Field(default=0, ge=0)
    max_tokens: int = Field(default=0, ge=0)


class ConfigBundle(CoreModel):
    case: CaseConfig
    ontology: Ontology
    aliases: list[AliasEntry]
    tolerances: list[Tolerance]
    gauges: list[Gauge]
    envelope: EnvelopeConfig
    gate: GateConfig
    llm: LlmConfig

    @model_validator(mode="after")
    def _consistent(self) -> ConfigBundle:
        names = [a.name for a in self.ontology.attributes]
        if len(names) != len(set(names)):
            raise ValueError("duplicate attribute in ontology")
        known = set(names)
        for tol in self.tolerances:
            if tol.attribute not in known:
                raise ValueError(f"tolerance for unknown attribute {tol.attribute}")
        return self
