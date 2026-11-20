"""Load backend/config/*.yaml into a ConfigBundle (adapter: reads files, core stays pure)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from trace_core.models.config import ConfigBundle

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _load(directory: Path, name: str) -> Any:
    with (directory / name).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_config_bundle(directory: Path = CONFIG_DIR) -> ConfigBundle:
    case = _load(directory, "case.yaml")
    case["shifts"] = _load(directory, "shifts.yaml")["shifts"]
    ontology = {
        "attributes": _load(directory, "ontology.yaml")["attributes"],
        "phrases": _load(directory, "phrases.yaml")["phrases"],
    }
    return ConfigBundle.model_validate(
        {
            "case": case,
            "ontology": ontology,
            "aliases": _load(directory, "aliases.yaml")["aliases"],
            "tolerances": _load(directory, "tolerances.yaml")["tolerances"],
            "gauges": _load(directory, "gauges.yaml")["gauges"],
            "envelope": _load(directory, "envelope.yaml"),
            "gate": _load(directory, "gate.yaml"),
            "llm": _load(directory, "llm.yaml"),
        }
    )
