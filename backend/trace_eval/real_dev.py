"""Dev rehearsal of the holdout pipeline on REAL telemetry of DEV machines only. It exercises the
same code as the holdout run (`build_real_case`, `run_case`, `assemble_report`) so that every
problem is found, and tuned, on dev data before the holdout is ever touched.

    python -m trace_eval.real_dev --out data/eval_report_real_dev.json [--machines 12] [--n 2]

The machines are drawn from the DEV side of the protocol split; a holdout machine is refused.
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from trace_core.models.eval import EvalReport
from trace_eval.holdout_run import DRAW_SEED, machine_split
from trace_eval.real_worlds import build_real_case, dataset_available, load_real
from trace_eval.runner import CaseResult, assemble_report, eval_config, run_case
from trace_eval.worlds import KINDS

REPO = Path(__file__).resolve().parents[2]
DEV_DISCLOSURE = (
    "Dev rehearsal on the real telemetry of dev machines, with faults planted by the builders' "
    "injector. Not the holdout."
)


def run_real_dev(
    out: Path,
    dataset: Path,
    *,
    machines: int = 12,
    n_per_kind: int = 2,
    seed: int = 7,
    work_dir: Path | None = None,
) -> EvalReport:
    if not dataset_available(dataset):
        raise FileNotFoundError("the PdM dataset is not in seed/dataset")
    dev, holdout = machine_split(dataset)
    pool = sorted(random.Random(seed).sample(dev, machines))  # noqa: S311 (reproducible draw)
    if set(pool) & set(holdout):
        raise ValueError("a holdout machine reached the dev rehearsal")
    data = load_real(dataset, pool)
    config = eval_config(pool)
    root = work_dir or Path(tempfile.mkdtemp(prefix="trace-real-dev-"))
    plan = [("quiet_control", n) for n in pool]
    for index, kind in enumerate(k for k in KINDS if k != "quiet_control"):
        picks = random.Random(seed * 100 + index).sample(pool, n_per_kind)  # noqa: S311
        plan.extend((kind, n) for n in sorted(picks))
    results: list[CaseResult] = []
    for i, (kind, n) in enumerate(plan):
        world = build_real_case(root / f"c{i}", data, n, kind, DRAW_SEED * 10_000 + 5_000 + i)
        results.append(run_case(world, config))
    return assemble_report(
        split="dev",
        results=results,
        config=config,
        machines=pool,
        root=root,
        seed=seed,
        n_per_kind=n_per_kind,
        out=out,
        disclosure=DEV_DISCLOSURE,
        extras_extra={"data": "real PdM telemetry of dev machines; planted faults only"},
    )


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--machines", type=int, default=12)
    parser.add_argument("--n", type=int, default=2)
    args = parser.parse_args(list(argv))
    report = run_real_dev(
        args.out, REPO / "seed" / "dataset", machines=args.machines, n_per_kind=args.n
    )
    print(report.run_id, report.split)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
