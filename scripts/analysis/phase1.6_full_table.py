#!/usr/bin/env python3
"""Phase 1.6 - 통합 수치 테이블 (Wall, CPU, GPU, Others, Delta)"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

BASE_DIR = Path("/Users/rainyforest/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution")
DATA_DIR = BASE_DIR / "data/raw/alienware/phase1.6_test2"
RPICT_FILE = BASE_DIR / "data/raw/rpict/rpict_phase1.5-test4.csv"

PHASES = {
    'Idle':  {'file': 'baseline_host.csv',           'start': 5, 'end': -3},
    'A1':    {'file': 'A1_yolo_nano_host.csv',       'start': 5, 'end': -5},
    'A2':    {'file': 'A2_yolo_medium_host.csv',     'start': 5, 'end': -5},
    'B1':    {'file': 'B1_nodejs_light_host.csv',    'start': 5, 'end': -3},
    'B2':    {'file': 'B2_nodejs_heavy_host.csv',    'start': 5, 'end': -3},
    'A1+B1': {'file': 'A1B1_concurrent_host.csv',   'start': 5, 'end': -5},
    'A1+B2': {'file': 'A1B2_concurrent_host.csv',   'start': 5, 'end': -5},
    'A2+B1': {'file': 'A2B1_concurrent_host.csv',   'start': 5, 'end': -5},
    'A2+B2': {'file': 'A2B2_concurrent_host.csv',   'start': 5, 'end': -5},
}

# Load RPICT data
rpict = pd.read_csv(RPICT_FILE)
rpict['ts'] = pd.to_datetime(rpict['timestamp'])

# Load host data and match RPICT
results = []
for name, info in PHASES.items():
    df = pd.read_csv(DATA_DIR / info['file'])
    df['ts'] = pd.to_datetime(df['timestamp'])
    df_trim = df.iloc[info['start']:info['end']]

    t_start = df_trim['ts'].iloc[0]
    t_end = df_trim['ts'].iloc[-1]

    # Match RPICT to this time window
    rpict_match = rpict[(rpict['ts'] >= t_start) & (rpict['ts'] <= t_end)]
    wall = rpict_match['power1_w'].mean() if len(rpict_match) > 0 else np.nan

    cpu = df_trim['rapl_package_w'].mean()
    gpu = df_trim['gpu_power_w'].mean()
    others = wall - cpu - gpu if not np.isnan(wall) else np.nan

    results.append({
        'phase': name,
        'wall': wall,
        'cpu': cpu,
        'gpu': gpu,
        'others': others,
        'time_range': f"{t_start.strftime('%H:%M:%S')} ~ {t_end.strftime('%H:%M:%S')}",
        'rpict_samples': len(rpict_match),
    })

# Build table
idle = results[0]

print("="*110)
print(f"{'Phase':<10} {'Wall(W)':<10} {'CPU(W)':<10} {'GPU(W)':<10} {'Others(W)':<10} "
      f"{'dWall':<10} {'dCPU':<10} {'dGPU':<10} {'dOthers':<10}")
print("="*110)

for r in results:
    d_wall = r['wall'] - idle['wall'] if not np.isnan(r['wall']) else np.nan
    d_cpu = r['cpu'] - idle['cpu']
    d_gpu = r['gpu'] - idle['gpu']
    d_others = r['others'] - idle['others'] if not np.isnan(r['others']) else np.nan

    def fmt(v):
        return f"{v:.1f}" if not np.isnan(v) else "N/A"

    def fmtd(v):
        if np.isnan(v): return "N/A"
        return f"{v:+.1f}" if abs(v) > 0.05 else "0.0"

    print(f"{r['phase']:<10} {fmt(r['wall']):<10} {fmt(r['cpu']):<10} {fmt(r['gpu']):<10} {fmt(r['others']):<10} "
          f"{fmtd(d_wall):<10} {fmtd(d_cpu):<10} {fmtd(d_gpu):<10} {fmtd(d_others):<10}")

print("="*110)
print(f"\nRPICT coverage per phase:")
for r in results:
    print(f"  {r['phase']:<10}: {r['time_range']}  ({r['rpict_samples']} samples)")
