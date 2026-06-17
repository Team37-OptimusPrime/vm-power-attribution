"""verify_model.py — Conservation verification for the power-attribution model.

Validates the paper's headline claim — that the model decomposes measured system
power into per-workload contributions within a small error — directly on the
real scp'd experiment data, using the SAME model the dashboard runs.

Metric ("귀속 오차" = conservation / decomposition error):
    conservation_mae_pct = mean(|e_sys - (Σ attributed + baseline)|) / mean(e_sys)
    where e_sys = RAPL(CPU) + GPU(total) + DRAM(idle).

Per the team decision, <=5% is defined as this conservation accuracy
(NOT a solo-vs-concurrent absolute comparison, which reflects real physical
CPU contention / GPU0≠GPU1 differences rather than model error).

Usage:
    python3 dashboard/verify_model.py                  # default fixed runs
    python3 dashboard/verify_model.py phase3_fixed     # specific run(s)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DASH = Path(__file__).resolve().parent
sys.path.insert(0, str(DASH))

from data_loader import load_baseline, load_phase, merge_host_cgroup  # noqa: E402
from model import attribute_power, compute_baseline_power, summarize_phase  # noqa: E402

BASE = DASH.parent / "data" / "raw" / "alienware"
THRESHOLD_PCT = 5.0
TRIM_HEAD_S, TRIM_TAIL_S = 15, 5

# Demo focus: AI + Non-AI (B2) combos, where the model holds cleanly.
AI_B2_COMBOS = ["A2B2_concurrent", "RNB2_concurrent", "GPTB2_concurrent"]
# AI + AI combos (reported for completeness).
AI_AI_COMBOS = ["A2RN_concurrent", "A2GPT_concurrent", "RNGPT_concurrent"]


def _trim(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "timestamp" not in df.columns:
        return df
    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], errors="coerce")
    d = d.dropna(subset=["timestamp"]).sort_values("timestamp")
    t0, t1 = d["timestamp"].min(), d["timestamp"].max()
    out = d[(d["timestamp"] >= t0 + pd.Timedelta(seconds=TRIM_HEAD_S))
            & (d["timestamp"] <= t1 - pd.Timedelta(seconds=TRIM_TAIL_S))]
    return out if not out.empty else d


def _phase_error(run: Path, phase: str, baseline_powers: dict) -> float | None:
    pdata = load_phase(run, phase)
    host = _trim(pdata.get("host"))
    merged = merge_host_cgroup(host, pdata.get("cgroup"))
    if merged is None or merged.empty:
        return None
    summary = summarize_phase(attribute_power(merged, baseline_powers))
    return summary.get("conservation_mae_pct", float("nan"))


def verify_run(run: Path) -> tuple[float, list[tuple[str, str, float]]]:
    bp = compute_baseline_power(load_baseline(run).get("host"), None)
    rows: list[tuple[str, str, float]] = []
    worst_demo = 0.0
    for label, combos in (("AI+B2", AI_B2_COMBOS), ("AI+AI", AI_AI_COMBOS)):
        for combo in combos:
            err = _phase_error(run, combo, bp)
            if err is None:
                continue
            rows.append((label, combo, err))
            if label == "AI+B2":
                worst_demo = max(worst_demo, err)
    return worst_demo, rows


def main() -> int:
    targets = sys.argv[1:] or ["phase3_fixed", "phase3_fixed_run2", "phase3_fixed_run3"]
    overall_pass = True
    for t in targets:
        run = BASE / t
        if not run.exists():
            print(f"(skip {t}: not found)")
            continue
        worst_demo, rows = verify_run(run)
        print(f"\n===== {t} =====")
        print(f"{'group':7s} {'combo':22s} {'conservation_err%':>18s}")
        for label, combo, err in rows:
            flag = "  <-- >5%" if err > THRESHOLD_PCT else ""
            print(f"{label:7s} {combo:22s} {err:18.2f}{flag}")
        status = "PASS" if worst_demo <= THRESHOLD_PCT else "FAIL"
        print(f"  AI+B2 worst (demo metric): {worst_demo:.2f}%  ->  {status} (threshold {THRESHOLD_PCT}%)")
        overall_pass = overall_pass and (worst_demo <= THRESHOLD_PCT)

    print(f"\n{'='*40}\nOVERALL (AI+B2 conservation): {'PASS ✓' if overall_pass else 'FAIL ✗'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
