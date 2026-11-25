"""Dev evaluation run (D-06..D-08). Builds seeded fault cases with the REAL engine, compares each
outcome with the planted truth, and writes an `EvalReport` (plus a sidecar with the bootstrap
intervals the frozen report model has no field for).

Never reads holdout data: the split is the caller's (`trace_eval.protocol.split_machines`) and this
runner only accepts dev machine numbers. Every number in the report is computed here from engine
outputs; the baselines' answer texts are the baselines' real outputs.

    python -m trace_eval.runner --out data/eval_report.json [--n 3] [--seed 7]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from trace_adapters.config_loader import load_config_bundle
from trace_core.build import build_case
from trace_core.compare.gate import gate
from trace_core.ids import build_claim, config_hash
from trace_core.models.case import CaseVersion
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import AliasEntry, ConfigBundle
from trace_core.models.eval import (
    BaselineOutput,
    CalibrationBin,
    EvalReport,
    Prf,
    Wilson,
)
from trace_core.models.evidence import SensorWindowPointer, TextSpanPointer
from trace_core.models.time import Interval, ObservedTime, Temporal
from trace_core.normalise.entities import resolve_entities
from trace_core.normalise.time import fmt_utc, parse_utc
from trace_core.read.sensor import RAW_STATISTIC, window_digest
from trace_core.read.text import read_plaintext
from trace_core.stage_types import GateContext
from trace_eval.baselines import BaselineInput
from trace_eval.baselines import fusion as fusion_baseline
from trace_eval.baselines import tfidf as tfidf_baseline
from trace_eval.baselines.nogate import Statement, false_conflicts
from trace_eval.metrics import (
    BinStat,
    bootstrap_ci,
    brier,
    calibration_bins,
    ece,
    precision_recall_f1,
    wilson_ci,
)
from trace_eval.protocol import leave_block_out
from trace_eval.report import save
from trace_eval.worlds import EXPECTED, KINDS, EvalCase, build_case_world, machine_id
from trace_worker.env import engine_sha, lockfile_hash, snapshot_hashes

DEV_MACHINES = tuple(range(101, 111))
"""Dev machine numbers; the holdout machines are never listed here (see protocol.split_machines)."""
EXTERNAL_FAULT_SHARE = 0.0
DISCLOSURE = (
    "All faults in this report were planted by the builders' injector (0% external); the "
    "hand-labelled set (U-2) has not been collected, so entity and extraction accuracy here are "
    "measured on injector truth only. Confidence is uncalibrated: no calibration fit exists yet."
)
ALIAS_VARIANTS = (
    "Machine {n}",
    "M{n}",
    "M-{n}",
    "machine #{n}",
    "SN-{n:04d}",
    "Machin {n}",
    "Press {n}",
)


@dataclass
class CaseResult:
    case: EvalCase
    version: CaseVersion
    outcome: str
    confidence: float | None
    state_abnormal: bool | None
    extraction: dict[str, bool]
    provenance: tuple[int, int]
    averaged: int


def eval_config(machines: Sequence[int]) -> ConfigBundle:
    base = load_config_bundle()
    aliases = [
        AliasEntry(
            entity_id=machine_id(n),
            canonical_name=f"Machine {n}",
            aliases=[f"M{n}", f"M-{n}", f"machine #{n}", f"SN-{n:04d}"],
        )
        for n in machines
    ]
    return base.model_copy(update={"aliases": aliases})


def _outcome(version: CaseVersion) -> str:
    comparisons = version.records.comparisons
    return comparisons[0].outcome if comparisons else "none"


def _state_claim(version: CaseVersion) -> ClaimRecord | None:
    return next(
        (
            c
            for c in version.records.claims
            if c.attribute == "operating_state" and (c.method.rule_id or "").startswith("state.")
        ),
        None,
    )


def _provenance(case: EvalCase, version: CaseVersion) -> tuple[int, int]:
    """(pointers that re-resolve to the same value, pointers checked): text quotes against the
    note, raw sensor windows against the Parquet partition."""
    ok = total = 0
    for claim in version.records.claims:
        ev = claim.evidence
        if isinstance(ev, TextSpanPointer):
            total += 1
            ok += int(case.note[ev.char_start : ev.char_end] == ev.quote)
        elif isinstance(ev, SensorWindowPointer) and ev.statistic == RAW_STATISTIC:
            total += 1
            channel = ev.channels[0]
            data = case.ports.telemetry.read(ev.series_id, ev.start, ev.end).to_pydict()
            seen: dict[str, set[float]] = {}
            for ts, v in zip(data["ts"], data[channel], strict=True):
                if v is not None:
                    seen.setdefault(str(ts), set()).add(float(v))
            readings = {h: next(iter(v)) for h, v in sorted(seen.items()) if len(v) == 1}
            digest = window_digest(ev.series_id, channel, ev.start, ev.end, readings)
            ok += int(digest == ev.window_sha256)
    return ok, total


def run_case(case: EvalCase, config: ConfigBundle) -> CaseResult:
    version = build_case(
        case.manifest,
        config,
        [],
        case.ports,
        hashes=snapshot_hashes(config, "eval"),
    )
    state = _state_claim(version)
    text = [c for c in version.records.claims if c.modality == "text"]
    day = case.day.isoformat()
    text_ok = (
        len(text) == 1
        and text[0].subject.entity_id == case.machine
        and text[0].value == "normal"
        and isinstance(text[0].temporal.valid_time, Interval)
        and text[0].temporal.valid_time.start[:10] <= day <= text[0].temporal.valid_time.end[:10]
    )
    abnormal = None if state is None else (state.value["state"] == "abnormal")  # type: ignore[index]
    sensor_ok = abnormal == case.abnormal if abnormal is not None else False
    ok, total = _provenance(case, version)
    return CaseResult(
        case=case,
        version=version,
        outcome=_outcome(version),
        confidence=None if state is None else state.confidence.value,
        state_abnormal=abnormal,
        extraction={"text": text_ok, "sensor": sensor_ok},
        provenance=(ok, total),
        averaged=sum(1 for c in version.records.conflicts if c.averaged is not False),
    )


def _baseline_input(case: EvalCase) -> BaselineInput:
    sentences = [s.strip() for s in case.note.replace("\n", ". ").split(". ") if s.strip()]
    return BaselineInput(
        machine=f"machine {case.machine.split(':')[1]}",
        day=case.day.isoformat(),
        note_sentences=sentences,
        note_written_at="2015-06-23T09:10:00Z",
        readings=case.readings,
        history=case.history,
    )


def _prf_by_kind(results: Sequence[CaseResult]) -> tuple[Prf, dict[str, Prf]]:
    """Per fault kind: the expected outcome class. tp = the kind's cases that got that outcome;
    fn = the others; fp = cases of OTHER kinds with a different expectation that got it anyway."""
    per: dict[str, Prf] = {}
    for kind in KINDS:
        want = EXPECTED[kind]
        mine = [r for r in results if r.case.kind == kind]
        others = [r for r in results if EXPECTED[r.case.kind] != want]
        tp = sum(1 for r in mine if r.outcome == want)
        fn = len(mine) - tp
        fp = sum(1 for r in others if r.outcome == want)
        p, rc, f1 = precision_recall_f1(tp, fp, fn)
        per[kind] = Prf(precision=p, recall=rc, f1=f1, n=len(mine))
    planted = [r for r in results if EXPECTED[r.case.kind] == "disagree"]
    tp = sum(1 for r in planted if r.outcome == "disagree")
    fp = sum(1 for r in results if EXPECTED[r.case.kind] != "disagree" and r.outcome == "disagree")
    p, rc, f1 = precision_recall_f1(tp, fp, len(planted) - tp)
    return Prf(precision=p, recall=rc, f1=f1, n=len(planted)), per


def _entity_accuracy(
    config: ConfigBundle, machines: Sequence[int], root: Path
) -> tuple[float, float, float, int]:
    """acc@1, acc@3, share routed to review and n, over every alias variant of every machine.
    Right at @1: the machine is the link or the top candidate; @3: among the top 3."""
    import io

    from trace_adapters.blob_fs import FsBlobStore
    from trace_core.models.records import Source

    blobs = FsBlobStore(root / "alias-blobs")
    hits1 = hits3 = routed = total = 0
    for n in machines:
        for template in ALIAS_VARIANTS:
            mention = template.format(n=n)
            text = (
                "Report date: 02 Jul 2015 09:10\nReporting period: 01 Jul 2015\n"
                f"{mention} ran normally through both shifts.\n"
            )
            ref = blobs.put(io.BytesIO(text.encode()), max_bytes=100_000)
            src = Source.model_validate(
                {"source_id": "alias-note", "case_id": "eval-alias", "modality": "text",
                 "sha256": ref.sha256, "origin": "eval:alias",
                 "ingested_at": "2015-08-06T04:00:00Z",
                 "synthetic": True, "mime": "text/plain", "size": ref.size}
            )  # fmt: skip
            claims = read_plaintext(src, text.encode(), config).claims
            resolved, _ = resolve_entities(claims, config, opened_at="2015-08-06T04:00:00Z")
            (claim,) = resolved
            subject = claim.subject
            truth = machine_id(n)
            ranked = (
                [subject.entity_id]
                if subject.entity_id
                else [c.entity_id for c in subject.candidates]
            )
            total += 1
            hits1 += int(bool(ranked) and ranked[0] == truth)
            hits3 += int(truth in ranked[:3])
            routed += int(subject.link_status != "resolved")
    return hits1 / total, hits3 / total, routed / total, total


def _wilson(k: int, n: int) -> Wilson:
    lo, hi = wilson_ci(k, n)
    return Wilson(point=k / n if n else 0.0, lower=lo, upper=hi, n=n)


def _gate_ctx(r: CaseResult, config: ConfigBundle) -> GateContext:
    claims = r.version.records.claims
    sources = r.version.views.state.sources
    return GateContext(
        config=config,
        config_hash=config_hash(config),
        envelopes=r.version.records.envelopes,
        events=[
            c
            for c in claims
            if c.attribute in {"error_event", "failure_event", "maintenance_action"}
        ],
        log_coverage=[s.coverage_period for s in sources if s.coverage_period is not None],
    )


def _shifted(claim: ClaimRecord, days: int) -> ClaimRecord:
    """The same note, but about another day: a pair the gate must call non-comparable."""
    vt = claim.temporal.valid_time
    assert isinstance(vt, Interval)  # noqa: S101
    new = Interval(
        start=fmt_utc(parse_utc(vt.start) + timedelta(days=days)),
        end=fmt_utc(parse_utc(vt.end) + timedelta(days=days)),
        granularity=vt.granularity,
        resolved_from=vt.resolved_from,
    )
    fields = claim.model_dump(mode="python")
    fields["temporal"] = Temporal(
        valid_time=new,
        observed_time=ObservedTime(at=claim.temporal.observed_time.at, basis="document_date"),
        timezone_original=claim.temporal.timezone_original,
    )
    return build_claim(**fields)


def _false_conflicts(results: Sequence[CaseResult], config: ConfigBundle) -> dict[str, Any]:
    """Non-comparable pairs through the REAL gate and through the no-gate baseline."""
    gated = tested = 0
    statements: list[tuple[Statement, Statement]] = []
    for i, r in enumerate(results):
        text = next((c for c in r.version.records.claims if c.modality == "text"), None)
        state = _state_claim(r.version)
        if text is None or state is None:
            continue
        label = "abnormal" if r.state_abnormal else "normal"
        day = r.case.day.isoformat()
        other = results[(i + 1) % len(results)]
        other_state = _state_claim(other.version)
        if other_state is not None and other.case.machine != r.case.machine:
            record = gate(text, other_state, _gate_ctx(other, config))
            tested += 1
            gated += int(record.outcome == "disagree")
            other_label = "abnormal" if other.state_abnormal else "normal"
            statements.append(
                (
                    Statement(r.case.machine, day, None, "normal"),
                    Statement(other.case.machine, other.case.day.isoformat(), None, other_label),
                )
            )
        record = gate(_shifted(text, 3), state, _gate_ctx(r, config))
        tested += 1
        gated += int(record.outcome == "disagree")
        statements.append(
            (
                Statement(r.case.machine, "shifted", None, "normal"),
                Statement(r.case.machine, day, None, label),
            )
        )
    flagged, non_comparable = false_conflicts(statements)
    return {"gate": (gated, tested), "nogate": (flagged, non_comparable)}


def _tally(results: Sequence[CaseResult]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        out[r.case.kind][r.outcome] += 1
    return {k: dict(v) for k, v in out.items()}


def assemble_report(
    *,
    split: Literal["dev", "holdout"],
    results: Sequence[CaseResult],
    config: ConfigBundle,
    machines: Sequence[int],
    root: Path,
    seed: int,
    n_per_kind: int,
    out: Path,
    disclosure: str = DISCLOSURE,
    extras_extra: dict[str, Any] | None = None,
) -> EvalReport:
    """Score built cases and write the report. Shared by the dev run and the holdout run, so both
    are computed by exactly the same code."""
    overall, per_fault = _prf_by_kind(results)

    alarms = tested = 0
    for r in (r for r in results if r.case.kind == "quiet_control"):
        stats = {
            date.fromisoformat(q.date): q.t_d for q in r.version.records.envelopes[0].quiet_days
        }
        a, t, _ = leave_block_out(stats, config.envelope.alpha, 7)
        alarms, tested = alarms + a, tested + t

    fc = _false_conflicts(results, config)
    acc1, acc3, routed, n_alias = _entity_accuracy(config, machines, root)
    extraction = {
        m: sum(1 for r in results if r.extraction[m]) / len(results) for m in ("text", "sensor")
    }
    ok = sum(r.provenance[0] for r in results)
    total = sum(r.provenance[1] for r in results)
    gaps_as_normal = sum(
        1 for r in results if r.case.kind in {"removed_source", "flatline"} and r.outcome == "agree"
    )
    conf = [r.confidence for r in results if r.confidence is not None]
    right = [r.extraction["sensor"] for r in results if r.confidence is not None]
    bins: list[BinStat] = calibration_bins(conf, right)
    ece_ci = bootstrap_ci(
        lambda idx: ece([conf[i] for i in idx], [right[i] for i in idx]), len(conf), seed=seed
    )
    brier_ci = bootstrap_ci(
        lambda idx: brier([conf[i] for i in idx], [right[i] for i in idx]), len(conf), seed=seed
    )

    demo = next(r for r in results if r.case.kind == "contradicting_note")
    planted = [_baseline_input(r.case) for r in results if r.case.abnormal]
    surfaced = {
        name: sum(1 for b in planted if fn(b).surfaced_conflict)
        for name, fn in (("tfidf", tfidf_baseline.answer), ("fusion", fusion_baseline.answer))
    }
    baselines: list[BaselineOutput] = []
    demo_input = _baseline_input(demo.case)
    for answer in (tfidf_baseline.answer(demo_input), fusion_baseline.answer(demo_input)):
        baselines.append(
            BaselineOutput(
                name=answer.name,  # type: ignore[arg-type]
                answer_text=answer.answer_text,
                score=answer.score,
                surfaced_conflict=answer.surfaced_conflict,
                provenance_correct=answer.provenance_correct,
            )
        )
    flagged, non_comparable = fc["nogate"]
    baselines.append(
        BaselineOutput(
            name="nogate",
            answer_text=f"flags {flagged} of {non_comparable} non-comparable pairs as conflicts",
            score=flagged / non_comparable if non_comparable else None,
            surfaced_conflict=flagged > 0,
            provenance_correct=False,
        )
    )

    hashes = snapshot_hashes(config, "eval")
    report = EvalReport(
        run_id=f"{split}-s{seed}-n{n_per_kind}-{hashes.config_hash[:8]}",
        split=split,
        config_hash=hashes.config_hash,
        engine_sha=engine_sha(),
        lockfile_hash=lockfile_hash(),
        overall=overall,
        per_fault=per_fault,
        false_conflict_rate=_wilson(*fc["gate"]),
        quiet_day_false_alarm=_wilson(alarms, tested),
        entity_accuracy_at1=acc1,
        entity_accuracy_at3=acc3,
        extraction_accuracy=extraction,
        provenance_reresolve_rate=ok / total if total else 0.0,
        gaps_read_as_normal=gaps_as_normal,
        averaged_outputs=sum(r.averaged for r in results),
        ece_before=ece(conf, right),
        ece_after=None,  # no calibration fit exists yet (P1-05)
        brier_before=brier(conf, right),
        brier_after=None,
        bins=[
            CalibrationBin(
                lo=b.lo, hi=b.hi, n=b.n, accuracy=b.accuracy, mean_confidence=b.mean_confidence
            )
            for b in bins
        ],
        baselines=baselines,
    )
    extras = {
        "seed": seed,
        "cases": len(results),
        "cases_per_kind": {k: sum(1 for r in results if r.case.kind == k) for k in KINDS},
        "ece_ci": list(ece_ci),
        "brier_ci": list(brier_ci),
        "external_fault_share": EXTERNAL_FAULT_SHARE,
        "disclosure": disclosure,
        **(extras_extra or {}),
        "entity": {"routed_to_review_share": routed, "mentions": n_alias},
        "false_conflicts": {"gate": list(fc["gate"]), "nogate": [flagged, non_comparable]},
        "baseline_surfaced_planted_conflict": {**surfaced, "planted_cases": len(planted)},
        "outcomes": _tally(results),
    }
    save(report, extras, out)
    return report


def run_dev(
    out: Path,
    *,
    n_per_kind: int = 3,
    seed: int = 7,
    work_dir: Path | None = None,
    machines: Sequence[int] = DEV_MACHINES,
) -> EvalReport:
    """Build every seeded case with the real engine and write the report to `out`."""
    if not set(machines) <= set(DEV_MACHINES):
        raise ValueError("the dev runner only accepts dev machines")
    config = eval_config(machines)
    root = work_dir or Path(tempfile.mkdtemp(prefix="trace-eval-"))
    results: list[CaseResult] = []
    for k_index, kind in enumerate(KINDS):
        for i in range(n_per_kind):
            n = machines[(k_index * n_per_kind + i) % len(machines)]
            world = build_case_world(root / f"c{len(results)}", n, kind, seed * 1000 + len(results))
            results.append(run_case(world, config))
    return assemble_report(
        split="dev",
        results=results,
        config=config,
        machines=machines,
        root=root,
        seed=seed,
        n_per_kind=n_per_kind,
        out=out,
    )


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="TRACE dev evaluation (never the holdout)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--n", type=int, default=3, help="cases per fault kind")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(list(argv))
    report = run_dev(args.out, n_per_kind=args.n, seed=args.seed)
    print(json.dumps({"run_id": report.run_id, "split": report.split, "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
