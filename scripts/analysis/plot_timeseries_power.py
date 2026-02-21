#!/usr/bin/env python3
"""
plot_timeseries_power.py
전체 실험 타임라인 또는 단일 phase의 CPU/GPU/Wall power 시계열 그래프 생성.

Usage:
  python3 plot_timeseries_power.py                    # 전체 타임라인 (run3 기본)
  python3 plot_timeseries_power.py --phase RNGPT      # 단일 phase
  python3 plot_timeseries_power.py --run run3         # 특정 run
  python3 plot_timeseries_power.py --output my.png    # 출력 파일명 지정
"""

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

# ── 경로 설정 ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data", "raw")
RPICT_DIR = os.path.join(DATA_DIR, "rpict")
OUT_DIR   = os.path.join(BASE_DIR, "reports", "phase3", "figures")

# ── Phase 정의 (PyTorch 포함 전체 / 제외 모두 지원) ──────────
# 표시용 레이블
PHASE_LABELS = {
    "baseline":         "Baseline",
    "A2_yolo_medium":   "YOLO\n(solo)",
    "PT_pytorch_gemm":  "PyTorch\n(solo)",
    "RN_resnet18":      "ResNet\n(solo)",
    "GPT_gpt2":         "GPT-2\n(solo)",
    "B2_nodejs_heavy":  "Node.js\n(solo)",
    "A2B2_concurrent":  "YOLO+\nNode",
    "PTB2_concurrent":  "PT+\nNode",
    "RNB2_concurrent":  "RN+\nNode",
    "GPTB2_concurrent": "GPT+\nNode",
    "A2PT_concurrent":  "YOLO+\nPT",
    "A2RN_concurrent":  "YOLO+\nRN",
    "A2GPT_concurrent": "YOLO+\nGPT",
    "PTRN_concurrent":  "PT+\nRN",
    "PTGPT_concurrent": "PT+\nGPT",
    "RNGPT_concurrent": "RN+\nGPT",
}

# phase 배경색 (타입별)
PHASE_COLORS = {
    "baseline":   "#e8e8e8",
    "solo_ai":    "#d4e8ff",
    "solo_cpu":   "#ffe8cc",
    "ai_b2":      "#d4f5d4",
    "ai_ai":      "#f5d4f5",
}

PHASE_TYPES = {
    "baseline":         "baseline",
    "A2_yolo_medium":   "solo_ai",
    "PT_pytorch_gemm":  "solo_ai",
    "RN_resnet18":      "solo_ai",
    "GPT_gpt2":         "solo_ai",
    "B2_nodejs_heavy":  "solo_cpu",
    "A2B2_concurrent":  "ai_b2",
    "PTB2_concurrent":  "ai_b2",
    "RNB2_concurrent":  "ai_b2",
    "GPTB2_concurrent": "ai_b2",
    "A2PT_concurrent":  "ai_ai",
    "A2RN_concurrent":  "ai_ai",
    "A2GPT_concurrent": "ai_ai",
    "PTRN_concurrent":  "ai_ai",
    "PTGPT_concurrent": "ai_ai",
    "RNGPT_concurrent": "ai_ai",
}


def load_host_csvs(run_dir: str, phases: list) -> pd.DataFrame:
    """지정된 phases의 host CSV를 시간 순으로 concatenate."""
    dfs = []
    for phase in phases:
        path = os.path.join(run_dir, f"{phase}_host.csv")
        if not os.path.exists(path):
            print(f"  [WARN] not found: {path}", file=sys.stderr)
            continue
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df["phase"] = phase
        dfs.append(df)
    if not dfs:
        raise FileNotFoundError(f"No host CSV files found in {run_dir}")
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    return combined


def load_rpict(rpict_path: str) -> pd.DataFrame:
    """RPICT CSV 로드 및 정리."""
    df = pd.read_csv(rpict_path, parse_dates=["timestamp"])
    df = df.rename(columns={"power1_w": "wall_power_w"})
    df = df[["timestamp", "wall_power_w"]].sort_values("timestamp").reset_index(drop=True)
    return df


def trim_phase(df: pd.DataFrame, trim_head_s: float = 10, trim_tail_s: float = 5) -> pd.DataFrame:
    """각 phase에서 앞뒤 몇 초 제거 (안정 구간 확보)."""
    result = []
    for phase, grp in df.groupby("phase", sort=False):
        grp = grp.sort_values("timestamp")
        t0 = grp["timestamp"].iloc[0]
        t1 = grp["timestamp"].iloc[-1]
        mask = (grp["timestamp"] >= t0 + pd.Timedelta(seconds=trim_head_s)) & \
               (grp["timestamp"] <= t1 - pd.Timedelta(seconds=trim_tail_s))
        result.append(grp[mask])
    return pd.concat(result, ignore_index=True)


def smooth(series: pd.Series, window: int = 5) -> pd.Series:
    """Rolling mean smoothing."""
    return series.rolling(window=window, center=True, min_periods=1).mean()


def plot_full_timeline(host_df: pd.DataFrame, rpict_df: pd.DataFrame,
                       phases: list, out_path: str):
    """전체 실험 타임라인 그래프."""
    # 시작 시각 기준 경과 시간(분) 계산
    t0 = host_df["timestamp"].iloc[0]
    host_df = host_df.copy()
    host_df["t_min"] = (host_df["timestamp"] - t0).dt.total_seconds() / 60

    rpict_df = rpict_df.copy()
    rpict_df = rpict_df[(rpict_df["timestamp"] >= host_df["timestamp"].iloc[0]) &
                        (rpict_df["timestamp"] <= host_df["timestamp"].iloc[-1])]
    rpict_df["t_min"] = (rpict_df["timestamp"] - t0).dt.total_seconds() / 60

    fig, ax = plt.subplots(figsize=(14, 5))

    # ── 배경 shading (phase 구간) ──
    phase_bounds = []
    for phase in phases:
        grp = host_df[host_df["phase"] == phase]
        if grp.empty:
            continue
        t_start = grp["t_min"].iloc[0]
        t_end   = grp["t_min"].iloc[-1]
        color   = PHASE_COLORS.get(PHASE_TYPES.get(phase, "baseline"), "#f0f0f0")
        ax.axvspan(t_start, t_end, color=color, alpha=0.35, linewidth=0)
        phase_bounds.append((t_start, t_end, phase))

    # ── Power lines ──
    cpu_smooth = smooth(host_df["rapl_package_w"])
    gpu0_smooth = smooth(host_df["gpu0_power_w"])
    gpu1_smooth = smooth(host_df["gpu1_power_w"])

    ax.plot(host_df["t_min"], cpu_smooth,  color="#e67e22", lw=1.5, label="CPU (RAPL)")
    ax.plot(host_df["t_min"], gpu0_smooth, color="#2980b9", lw=1.5, label="GPU 0")
    ax.plot(host_df["t_min"], gpu1_smooth, color="#27ae60", lw=1.5, label="GPU 1")

    if not rpict_df.empty:
        ax.scatter(rpict_df["t_min"], rpict_df["wall_power_w"],
                   color="#8e44ad", s=6, alpha=0.7, label="Wall (RPICT)", zorder=5)

    ax.set_xlabel("Elapsed Time (min)", fontsize=11)
    ax.set_ylabel("Power (W)", fontsize=11)
    ax.set_title("Power Consumption Timeline — Phase 3 Experiment (Run 3)", fontsize=12)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_xlim(host_df["t_min"].iloc[0], host_df["t_min"].iloc[-1])

    # ── Phase 레이블 (ylim 확정 후 배치) ──
    y_top = ax.get_ylim()[1]
    for t_start, t_end, phase in phase_bounds:
        t_mid = (t_start + t_end) / 2
        label = PHASE_LABELS.get(phase, phase)
        ax.text(t_mid, y_top * 0.98, label,
                ha="center", va="top", fontsize=6.5,
                rotation=0, clip_on=True,
                bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.6))

    # ── 범례 패치 (phase type color) ──
    legend_patches = [
        mpatches.Patch(color=PHASE_COLORS["baseline"],  alpha=0.5, label="Baseline"),
        mpatches.Patch(color=PHASE_COLORS["solo_ai"],   alpha=0.5, label="Solo AI"),
        mpatches.Patch(color=PHASE_COLORS["solo_cpu"],  alpha=0.5, label="Solo CPU"),
        mpatches.Patch(color=PHASE_COLORS["ai_b2"],     alpha=0.5, label="AI + Node.js"),
        mpatches.Patch(color=PHASE_COLORS["ai_ai"],     alpha=0.5, label="AI + AI"),
    ]
    ax.legend(handles=ax.get_legend_handles_labels()[0] + legend_patches,
              labels=ax.get_legend_handles_labels()[1] + [p.get_label() for p in legend_patches],
              loc="upper left", fontsize=8, framealpha=0.85, ncol=2)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")
    plt.close()


def plot_single_phase(host_df: pd.DataFrame, rpict_df: pd.DataFrame,
                      phase: str, out_path: str):
    """단일 phase 내 시계열 그래프."""
    grp = host_df[host_df["phase"] == phase].copy()
    if grp.empty:
        print(f"[ERROR] Phase '{phase}' not found in data.", file=sys.stderr)
        return

    t0 = grp["timestamp"].iloc[0]
    grp["t_sec"] = (grp["timestamp"] - t0).dt.total_seconds()

    # RPICT 구간 필터링
    rpict_sub = rpict_df[
        (rpict_df["timestamp"] >= grp["timestamp"].iloc[0]) &
        (rpict_df["timestamp"] <= grp["timestamp"].iloc[-1])
    ].copy()
    rpict_sub["t_sec"] = (rpict_sub["timestamp"] - t0).dt.total_seconds()

    fig, ax = plt.subplots(figsize=(10, 4.5))

    ax.plot(grp["t_sec"], smooth(grp["rapl_package_w"]),  color="#e67e22", lw=2, label="CPU (RAPL)")
    ax.plot(grp["t_sec"], smooth(grp["gpu0_power_w"]),    color="#2980b9", lw=2, label="GPU 0")
    ax.plot(grp["t_sec"], smooth(grp["gpu1_power_w"]),    color="#27ae60", lw=2, label="GPU 1")
    if not rpict_sub.empty:
        ax.scatter(rpict_sub["t_sec"], rpict_sub["wall_power_w"],
                   color="#8e44ad", s=20, alpha=0.8, label="Wall (RPICT)", zorder=5)

    ax.set_xlabel("Elapsed Time (s)", fontsize=11)
    ax.set_ylabel("Power (W)", fontsize=11)
    ax.set_title(f"Power Consumption — {PHASE_LABELS.get(phase, phase).replace(chr(10), ' ')}", fontsize=12)
    ax.legend(fontsize=9, framealpha=0.85)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Phase 3 power time-series graph")
    parser.add_argument("--run",    default="run3",
                        help="Data run ID (e.g. run3). Data dir: phase3_fixed_<run>")
    parser.add_argument("--phase",  default=None,
                        help="Single phase name (e.g. RNGPT). If omitted → full timeline.")
    parser.add_argument("--no-pt",  action="store_true",
                        help="Exclude PyTorch phases")
    parser.add_argument("--trim",   action="store_true", default=True,
                        help="Trim head/tail seconds per phase (default: True)")
    parser.add_argument("--no-trim", dest="trim", action="store_false")
    parser.add_argument("--output", default=None,
                        help="Output PNG filename (auto-generated if omitted)")
    args = parser.parse_args()

    run_id   = args.run
    run_dir  = os.path.join(DATA_DIR, "alienware", f"phase3_fixed_{run_id}")
    rpict_map = {
        "run1":  os.path.join(RPICT_DIR, "phase3-rerun.csv"),  # run1 AI+AI subset
        "run3":  os.path.join(RPICT_DIR, "phase3_run3.csv"),
        "run4":  os.path.join(RPICT_DIR, "phase3_run4.csv"),
        "run5":  os.path.join(RPICT_DIR, "phase3_run5.csv"),
        "run6":  os.path.join(RPICT_DIR, "phase3_run6.csv"),
    }
    rpict_path = rpict_map.get(run_id, os.path.join(RPICT_DIR, f"phase3_{run_id}.csv"))

    if not os.path.isdir(run_dir):
        print(f"[ERROR] Data directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    # PyTorch 포함 전체 phase 순서
    all_phases = [
        "baseline",
        "A2_yolo_medium", "PT_pytorch_gemm", "RN_resnet18", "GPT_gpt2", "B2_nodejs_heavy",
        "A2B2_concurrent", "PTB2_concurrent", "RNB2_concurrent", "GPTB2_concurrent",
        "A2PT_concurrent", "A2RN_concurrent", "A2GPT_concurrent",
        "PTRN_concurrent", "PTGPT_concurrent", "RNGPT_concurrent",
    ]
    pt_phases = {"PT_pytorch_gemm", "PTB2_concurrent", "A2PT_concurrent",
                 "PTRN_concurrent", "PTGPT_concurrent"}
    no_pt_phases = [p for p in all_phases if p not in pt_phases]

    phases = no_pt_phases if args.no_pt else all_phases

    # 단일 phase 지정 시 (prefix match)
    if args.phase:
        matched = [p for p in all_phases if p.upper().startswith(args.phase.upper())]
        if not matched:
            print(f"[ERROR] Phase '{args.phase}' not found. Available: {all_phases}", file=sys.stderr)
            sys.exit(1)
        phases = matched[:1]

    print(f"Loading host CSVs from: {run_dir}")
    host_df = load_host_csvs(run_dir, phases)

    if args.trim and len(phases) > 1:
        host_df = trim_phase(host_df, trim_head_s=10, trim_tail_s=5)

    rpict_df = pd.DataFrame(columns=["timestamp", "wall_power_w"])
    if os.path.exists(rpict_path):
        print(f"Loading RPICT from: {rpict_path}")
        rpict_df = load_rpict(rpict_path)
    else:
        print(f"[WARN] RPICT file not found: {rpict_path} — Wall power will be omitted.")

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.output:
        out_path = args.output if os.path.isabs(args.output) else os.path.join(OUT_DIR, args.output)
    elif args.phase:
        out_path = os.path.join(OUT_DIR, f"timeseries_{args.phase.lower()}_{run_id}.png")
    else:
        suffix = "_nopt" if args.no_pt else ""
        out_path = os.path.join(OUT_DIR, f"timeseries_full_{run_id}{suffix}.png")

    if len(phases) == 1:
        plot_single_phase(host_df, rpict_df, phases[0], out_path)
    else:
        plot_full_timeline(host_df, rpict_df, phases, out_path)


if __name__ == "__main__":
    main()
