"""h0 reality check (D-01): does the REAL M-21 / 14 Mar 2015 fit the demo story?

Standalone report tool (not part of trace_core). Reads seed/dataset/*.csv, applies the
PRD 10.3 quiet-day rule and split-conformal robust max-z, and writes data/h0_report.json.
No network, no thresholds invented: alpha / margin_days come from backend/config/envelope.yaml.
Dataset timestamps are naive and interpreted as plant-local (assumption A7).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "seed" / "dataset"
CHANNELS = ["volt", "rotate", "pressure", "vibration"]
CASE_MACHINE = 21
CASE_DAY = pd.Timestamp("2015-03-14")


def _load() -> dict[str, pd.DataFrame]:
    tel = pd.read_csv(DATASET / "PdM_telemetry.csv", parse_dates=["datetime"])
    return {
        "tel": tel,
        "err": pd.read_csv(DATASET / "PdM_errors.csv", parse_dates=["datetime"]),
        "maint": pd.read_csv(DATASET / "PdM_maint.csv", parse_dates=["datetime"]),
        "fail": pd.read_csv(DATASET / "PdM_failures.csv", parse_dates=["datetime"]),
        "machines": pd.read_csv(DATASET / "PdM_machines.csv"),
    }


def _event_days(d: dict[str, pd.DataFrame], machine: int) -> set[pd.Timestamp]:
    days: set[pd.Timestamp] = set()
    for key in ("err", "maint", "fail"):
        df = d[key]
        days.update(df.loc[df["machineID"] == machine, "datetime"].dt.normalize())
    return days


def machine_analysis(
    d: dict[str, pd.DataFrame], machine: int, alpha: float, margin: int, case_day: pd.Timestamp
) -> dict[str, Any]:
    tel = d["tel"]
    t = tel[tel["machineID"] == machine].copy()
    t["day"] = t["datetime"].dt.normalize()
    counts = t.groupby("day")[CHANNELS].count()
    full_days = set(counts.index[(counts == 24).all(axis=1)])
    ev_days = _event_days(d, machine)
    delta = pd.Timedelta(days=margin)
    quiet = sorted(
        day
        for day in full_days
        if abs(day - case_day) > delta and all(abs(day - e) > delta for e in ev_days)
    )
    n = len(quiet)
    out: dict[str, Any] = {"machine": machine, "n_quiet_days": n}
    if n == 0:
        return out
    q_rows = t[t["day"].isin(quiet)]
    med = q_rows[CHANNELS].median()
    mad = (q_rows[CHANNELS] - med).abs().median()
    s = 1.4826 * mad
    ok = [c for c in CHANNELS if s[c] > 0]
    z = ((t[ok] - med[ok]).abs() / s[ok]).max(axis=1)
    t["z"] = z
    td = t.groupby("day")["z"].max()
    q_td = np.sort(td.loc[quiet].to_numpy())
    k = math.ceil((1 - alpha) * (n + 1))
    t_star = float(q_td[k - 1]) if k <= n else None
    out.update(
        {
            "k": k,
            "t_star": t_star,
            "med": {c: float(med[c]) for c in CHANNELS},
            "s": {c: float(s[c]) for c in CHANNELS},
            "degenerate_channels": [c for c in CHANNELS if s[c] == 0],
            "t_d_by_day": td,
        }
    )
    return out


def scan_alternatives(
    d: dict[str, pd.DataFrame], alpha: float, margin: int
) -> list[dict[str, Any]]:
    """Real machine-days with T_D > T* and error rows that day (re-verified as the case day)."""
    tel, err = d["tel"], d["err"]
    out: list[dict[str, Any]] = []
    far = pd.Timestamp("1900-01-01")
    for m in sorted(d["machines"]["machineID"]):
        a = machine_analysis(d, int(m), alpha, margin, far)
        if a.get("t_star") is None:
            continue
        td = a["t_d_by_day"]
        e = err[err["machineID"] == m]
        eday = e.assign(day=e["datetime"].dt.normalize()).groupby("day")["errorID"].apply(sorted)
        t = tel[tel["machineID"] == m]
        full = t.groupby(t["datetime"].dt.normalize())[CHANNELS].count().eq(24).all(axis=1)
        for day in eday.index:
            if day not in td.index or not bool(full.get(day, False)) or td.loc[day] <= a["t_star"]:
                continue
            b = machine_analysis(d, int(m), alpha, margin, day)  # day as the case window
            if b.get("t_star") is None or float(b["t_d_by_day"].loc[day]) <= b["t_star"]:
                continue
            rows = t[t["datetime"].dt.normalize() == day]
            z = (rows[CHANNELS] - pd.Series(b["med"])).abs() / pd.Series(b["s"])
            st = z.stack()
            pk = st.idxmax()
            out.append(
                {
                    "machine": int(m),
                    "day": str(day.date()),
                    "n_quiet": b["n_quiet_days"],
                    "t_star": b["t_star"],
                    "t_d": float(b["t_d_by_day"].loc[day]),
                    "errors": eday.loc[day],
                    "peak_channel": pk[1],
                    "peak_hour": str(rows.loc[pk[0], "datetime"]),
                    "peak_value": float(rows.loc[pk[0], pk[1]]),
                    "peak_z": float(st.max()),
                }
            )
    return out


def run() -> int:
    needed = [
        "PdM_telemetry.csv",
        "PdM_errors.csv",
        "PdM_maint.csv",
        "PdM_failures.csv",
        "PdM_machines.csv",
    ]
    missing = [f for f in needed if not (DATASET / f).exists()]
    if missing:
        print("STOP: missing dataset files:", ", ".join(missing))
        return 2
    cfg = yaml.safe_load((ROOT / "backend" / "config" / "envelope.yaml").read_text())
    alpha, margin = float(cfg["alpha"]), int(cfg["margin_days"])
    d = _load()

    m21 = machine_analysis(d, CASE_MACHINE, alpha, margin, CASE_DAY)
    td_series: pd.Series = m21.pop("t_d_by_day")
    t_d = float(td_series.loc[CASE_DAY])
    tel = d["tel"]
    day_rows = tel[
        (tel["machineID"] == CASE_MACHINE) & (tel["datetime"].dt.normalize() == CASE_DAY)
    ]
    med, s = m21["med"], m21["s"]
    zs = ((day_rows[CHANNELS] - pd.Series(med)).abs() / pd.Series(s)).replace([np.inf], np.nan)
    flat = zs.stack()
    peak_idx = flat.idxmax()
    peak_row = day_rows.loc[peak_idx[0]]

    def _window(df: pd.DataFrame) -> list[dict[str, Any]]:
        sub = df[
            (df["machineID"] == CASE_MACHINE)
            & (df["datetime"] >= CASE_DAY - pd.Timedelta(days=margin))
            & (df["datetime"] < CASE_DAY + pd.Timedelta(days=margin + 1))
        ]
        return [{**{k: str(v) for k, v in r.items()}} for r in sub.to_dict("records")]

    err_on_day = d["err"][
        (d["err"]["machineID"] == CASE_MACHINE) & (d["err"]["datetime"].dt.normalize() == CASE_DAY)
    ]

    # Quiet-day histogram over all machines, same rule.
    ns = []
    for m in sorted(d["machines"]["machineID"]):
        ns.append(
            machine_analysis(
                d,
                int(m),
                alpha,
                margin,
                CASE_DAY if m == CASE_MACHINE else pd.Timestamp("1900-01-01"),
            )["n_quiet_days"]
        )
    hist = {
        "min": int(min(ns)),
        "median": float(np.median(ns)),
        "max": int(max(ns)),
        "machines_n_lt_19": int(sum(1 for x in ns if x < 19)),
        "machines_n_lt_10": int(sum(1 for x in ns if x < 10)),
        "per_machine": ns,
    }

    report = {
        "case": {
            "machine": CASE_MACHINE,
            "day": str(CASE_DAY.date()),
            "tz_note": "naive dataset timestamps assumed plant-local (A7)",
        },
        "params": {"alpha": alpha, "margin_days": margin, "channels": CHANNELS},
        "n_quiet_days": m21["n_quiet_days"],
        "k": m21["k"],
        "t_star": m21["t_star"],
        "t_d_case_day": t_d,
        "t_d_exceeds_t_star": bool(m21["t_star"] is not None and t_d > m21["t_star"]),
        "case_day_hours": int(len(day_rows)),
        "peak": {
            "channel": peak_idx[1],
            "datetime": str(peak_row["datetime"]),
            "value": float(peak_row[peak_idx[1]]),
            "z": float(flat.max()),
        },
        "error_rows_on_case_day": [
            {"datetime": str(r.datetime), "errorID": r.errorID} for r in err_on_day.itertuples()
        ],
        "events_within_margin": {
            "errors": _window(d["err"]),
            "maint": _window(d["maint"]),
            "failures": _window(d["fail"]),
        },
        "med": med,
        "s": s,
        "degenerate_channels": m21["degenerate_channels"],
        "quiet_day_histogram_all_machines": hist,
    }
    alts = scan_alternatives(d, alpha, margin)
    report["alternatives_real"] = alts
    # Deterministic pick: same machine, vibration peak, an error3 row, max T_D / T*.
    pool = [
        a
        for a in alts
        if a["machine"] == CASE_MACHINE
        and a["peak_channel"] == "vibration"
        and "error3" in a["errors"]
    ]
    if pool:
        best = max(pool, key=lambda a: a["t_d"] / a["t_star"])
        report["decision"] = {
            "h0_decision": "another_real_day",
            "machine": best["machine"],
            "day": best["day"],
            "t_d": best["t_d"],
            "t_star": best["t_star"],
            "errors": best["errors"],
            "peak_hour": best["peak_hour"],
        }
    out = ROOT / "data" / "h0_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "n_quiet_days",
                    "k",
                    "t_star",
                    "t_d_case_day",
                    "t_d_exceeds_t_star",
                    "peak",
                    "error_rows_on_case_day",
                    "case_day_hours",
                )
            },
            indent=2,
        )
    )
    print("quiet-day histogram:", {k: v for k, v in hist.items() if k != "per_machine"})
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(run())
