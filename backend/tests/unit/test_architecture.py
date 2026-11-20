"""Runtime twins of the import-linter contracts, plus config sanity (D-03)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from trace_adapters.config_loader import load_config_bundle
from trace_core.ids import config_hash

BACKEND = Path(__file__).resolve().parents[2]


def test_api_never_imports_pdfium() -> None:
    """Importing the whole API in a clean interpreter must not load any decoder (Q2-02)."""
    code = (
        "import sys, importlib, pkgutil, trace_api\n"
        "for m in pkgutil.walk_packages(trace_api.__path__, 'trace_api.'):\n"
        "    importlib.import_module(m.name)\n"
        "banned = ['pypdfium2', 'pytesseract', 'PIL', 'trace_adapters.pdfium_reader',\n"
        "          'trace_adapters.tesseract_ocr']\n"
        "loaded = [b for b in banned if b in sys.modules]\n"
        "print('LOADED', loaded)\n"
        "sys.exit(1 if loaded else 0)\n"
    )
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_config_bundle_loads_with_documented_defaults() -> None:
    bundle = load_config_bundle()
    assert bundle.case.plant_tz == "Asia/Kolkata"
    assert (bundle.gate.tau_link, bundle.gate.delta_link) == (0.85, 0.15)
    assert bundle.gate.lambda_corroboration == 0.2
    assert bundle.envelope.alpha == 0.05 and bundle.envelope.margin_days == 3
    assert bundle.envelope.training_policy == "all_except_case_window"
    assert bundle.llm.llm_mode == "off" and bundle.llm.vlm_mode == "off"
    assert bundle.llm.text_model is None and bundle.llm.vision_model is None  # never hard-coded
    forall = {p.phrase for p in bundle.ontology.phrases if p.quantifier == "forall"}
    assert {"ran normally", "no issues", "all good"} == forall
    assert all(
        a.canonical_unit is None for a in bundle.ontology.attributes if a.name == "vibration"
    )  # a unit nobody documented is never guessed
    assert "Press 21" not in [alias for e in bundle.aliases for alias in e.aliases]


def test_config_hash_is_deterministic_and_sensitive() -> None:
    a, b = load_config_bundle(), load_config_bundle()
    assert config_hash(a) == config_hash(b) and len(config_hash(a)) == 64
    changed = a.model_copy(update={"gate": a.gate.model_copy(update={"tau_link": 0.9})})
    assert config_hash(changed) != config_hash(a)
