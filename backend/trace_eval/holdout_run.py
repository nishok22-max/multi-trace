"""The holdout run (D-09, M6): REAL telemetry of the holdout machines, planted faults, the same
scoring code as the dev run. It is allowed to run once.

Guards, all enforced here and not only by the task:
- `TRACE_HOLDOUT_RUN=1` must be set (only `make eval-holdout` sets it);
- the machine split is the protocol's pure function of a fixed seed, so dev and holdout machines
  are disjoint by construction and nothing here can reach a dev machine;
- an existing holdout report is never overwritten: delete it by hand to run again, and the new
  report then says so.

Nothing in this module changes after the run: the report records the config, engine and lockfile
hashes, and a change to the engine afterwards makes the report show as superseded.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import tempfile
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from trace_core.models.eval import EvalReport
from trace_eval.holdout import HOLDOUT_ENV
from trace_eval.protocol import split_machines
from trace_eval.real_worlds import (
    RealData,
    build_real_case,
    dataset_available,
    load_real,
    machine_numbers,
)
from trace_eval.runner import CaseResult, assemble_report, eval_config, run_case
from trace_eval.worlds import KINDS

PROTOCOL_SEED = 20150805
"""Fixes the dev/holdout machine split. Chosen and committed before any holdout result existed."""
DRAW_SEED = 31
"""Fixes which holdout machines carry which planted fault."""
DEV_FRACTION = Decimal("0.6")
HOLDOUT_DISCLOSURE = (
    "Holdout run: the genuine PdM telemetry and event logs of the holdout machines (disjoint from "
    "the dev machines by construction), with faults planted by the builders' injector (0% "
    "external faults). The hand-labelled set (U-2) has not been collected, so entity and "
    "extraction accuracy are measured on injector truth only. Confidence is uncalibrated: no "
    "calibration fit exists. Thresholds and weights were tuned on dev machines only; this report "
    "is what the holdout produced and nothing was changed after seeing it."
)


def machine_split(dataset: Path) -> tuple[list[int], list[int]]:
    """(dev, holdout) machine numbers: a pure function of the dataset's machine list."""
    ids = [f"machine:{n}" for n in machine_numbers(dataset)]
    dev, holdout = split_machines(ids, PROTOCOL_SEED, DEV_FRACTION)
    return [int(m.split(":")[1]) for m in dev], [int(m.split(":")[1]) for m in holdout]


def plan(holdout: Sequence[int], n_per_kind: int) -> list[tuple[str, int]]:
    """(kind, machine) for every case: one quiet control per holdout machine (they supply the
    quiet-day false-alarm set), and `n_per_kind` distinct machines for each planted fault."""
    out: list[tuple[str, int]] = [("quiet_control", n) for n in sorted(holdout)]
    for index, kind in enumerate(k for k in KINDS if k != "quiet_control"):
        rng = random.Random(DRAW_SEED * 100 + index)  # noqa: S311 (reproducible draw)
        out.extend((kind, n) for n in sorted(rng.sample(sorted(holdout), n_per_kind)))
    return out


def manifest_for(holdout: Sequence[int], cases: Sequence[tuple[str, int]]) -> dict[str, Any]:
    ordered = sorted(holdout)
    return {
        "protocol_seed": PROTOCOL_SEED,
        "draw_seed": DRAW_SEED,
        "holdout_machines": ordered,
        "holdout_machines_sha256": hashlib.sha256(json.dumps(ordered).encode()).hexdigest(),
        "cases": [{"kind": k, "machine": n} for k, n in cases],
    }


def run_holdout(
    out: Path,
    dataset: Path,
    *,
    n_per_kind: int = 8,
    work_dir: Path | None = None,
    git_info: dict[str, Any] | None = None,
    seed_manifest: Path | None = None,
) -> EvalReport:
    if os.environ.get(HOLDOUT_ENV) != "1":
        raise PermissionError("the holdout runs only through `make eval-holdout`")
    if out.exists():
        raise PermissionError("a holdout report already exists: the holdout runs once")
    if not dataset_available(dataset):
        raise FileNotFoundError("the PdM dataset is not in seed/dataset")
    dev, holdout = machine_split(dataset)
    if set(dev) & set(holdout):  # also asserted inside split_machines
        raise ValueError("dev and holdout machines overlap")
    cases = plan(holdout, n_per_kind)
    root = work_dir or Path(tempfile.mkdtemp(prefix="trace-holdout-"))
    manifest = manifest_for(holdout, cases)
    if seed_manifest is not None:
        seed_manifest.parent.mkdir(parents=True, exist_ok=True)
        seed_manifest.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    data: RealData = load_real(dataset, holdout)
    config = eval_config(holdout)
    results: list[CaseResult] = []
    for i, (kind, n) in enumerate(cases):
        world = build_real_case(root / f"c{i}", data, n, kind, DRAW_SEED * 10_000 + i)
        results.append(run_case(world, config))
    return assemble_report(
        split="holdout",
        results=results,
        config=config,
        machines=holdout,
        root=root,
        seed=DRAW_SEED,
        n_per_kind=n_per_kind,
        out=out,
        disclosure=HOLDOUT_DISCLOSURE,
        extras_extra={
            "protocol": {
                "split_seed": PROTOCOL_SEED,
                "dev_machines": len(dev),
                "holdout_machines": len(holdout),
                "holdout_machines_sha256": manifest["holdout_machines_sha256"],
                "dev_fraction": str(DEV_FRACTION),
            },
            "data": "real PdM telemetry and event logs; planted faults only",
            "git": git_info or {},
            "models": sorted({data.models[n] for n in holdout}),
        },
    )
