#!/usr/bin/env python3
"""
Energy Attribution Validation Chart
교수님 요구: A+B concurrent → A책임 / B책임 / Idle로 분리하고
Solo 결과와 비율 비교
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

BASE_DIR = Path("/Users/rainyforest/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution")
DATA_DIR = BASE_DIR / "data/raw/alienware/phase1.6_test2"
RPICT_FILE = BASE_DIR / "data/raw/rpict/rpict_phase1.5-test4.csv"
OUTPUT_DIR = BASE_DIR / "reports/phase1.6/validation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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

def load_all():
    rpict = pd.read_csv(RPICT_FILE)
    rpict['ts'] = pd.to_datetime(rpict['timestamp'])

    data = {}
    for name, info in PHASES.items():
        df = pd.read_csv(DATA_DIR / info['file'])
        df['ts'] = pd.to_datetime(df['timestamp'])
        df_trim = df.iloc[info['start']:info['end']]

        t0, t1 = df_trim['ts'].iloc[0], df_trim['ts'].iloc[-1]
        rm = rpict[(rpict['ts'] >= t0) & (rpict['ts'] <= t1)]
        wall = rm['power1_w'].mean() if len(rm) > 0 else np.nan

        cpu = df_trim['rapl_package_w'].mean()
        gpu = df_trim['gpu_power_w'].mean()
        others = wall - cpu - gpu if not np.isnan(wall) else np.nan

        data[name] = {'wall': wall, 'cpu': cpu, 'gpu': gpu, 'others': others}
    return data

def create_attribution_chart(data):
    """
    교수님 핵심 그래프:
    각 concurrent 조합에 대해 3개 bar를 나란히:
      1) Solo A 책임분 (A solo - Idle)
      2) Solo B 책임분 (B solo - Idle)
      3) A+B concurrent에서 분리한 값 (concurrent - Idle = A책임 + B책임)
         → 이걸 A비율, B비율로 나눈 것
    """
    idle = data['Idle']

    combos = [
        ('A2', 'B2', 'A2+B2'),
        ('A2', 'B1', 'A2+B1'),
        ('A1', 'B2', 'A1+B2'),
        ('A1', 'B1', 'A1+B1'),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    axes = axes.flatten()

    for idx, (A, B, AB) in enumerate(combos):
        ax = axes[idx]

        # Solo 책임분 (Solo - Idle) per component
        a_cpu  = data[A]['cpu']  - idle['cpu']
        a_gpu  = data[A]['gpu']  - idle['gpu']
        a_oth  = data[A]['others'] - idle['others']

        b_cpu  = data[B]['cpu']  - idle['cpu']
        b_gpu  = data[B]['gpu']  - idle['gpu']
        b_oth  = data[B]['others'] - idle['others']

        # Concurrent 실측값 분리: (concurrent - Idle) = total delta
        ab_cpu  = data[AB]['cpu']  - idle['cpu']
        ab_gpu  = data[AB]['gpu']  - idle['gpu']
        ab_oth  = data[AB]['others'] - idle['others']

        # --- 3개 그룹: Solo A, Solo B, Concurrent(A+B)-Idle ---
        # 각 그룹을 stacked bar (CPU + GPU + Others)로 표현

        labels = [f'{A}\n(Solo)', f'{B}\n(Solo)', f'{A}+{B}\n(Concurrent)', f'{A}+{B}\n(Expected)']

        cpus   = [a_cpu,  b_cpu,  ab_cpu,  a_cpu + b_cpu]
        gpus   = [a_gpu,  b_gpu,  ab_gpu,  a_gpu + b_gpu]
        oths   = [a_oth,  b_oth,  ab_oth,  a_oth + b_oth]
        totals = [c+g+o for c,g,o in zip(cpus, gpus, oths)]

        x = np.arange(len(labels))
        width = 0.55

        bars_cpu = ax.bar(x, cpus, width, label='CPU', color='#FF6B6B')
        bars_gpu = ax.bar(x, gpus, width, bottom=cpus, label='GPU', color='#4DABF7')
        bars_oth = ax.bar(x, oths, width, bottom=[c+g for c,g in zip(cpus, gpus)], label='Others', color='#69DB7C')

        # Total labels
        for i, total in enumerate(totals):
            ax.text(i, total + 2, f'{total:.1f}W', ha='center', va='bottom',
                    fontsize=11, fontweight='bold')

        # Component labels inside bars
        for i in range(len(labels)):
            # CPU label
            if cpus[i] > 3:
                ax.text(i, cpus[i]/2, f'{cpus[i]:.1f}', ha='center', va='center', fontsize=9, color='white', fontweight='bold')
            # GPU label
            if gpus[i] > 3:
                ax.text(i, cpus[i] + gpus[i]/2, f'{gpus[i]:.1f}', ha='center', va='center', fontsize=9, color='white', fontweight='bold')
            # Others label
            if oths[i] > 3:
                ax.text(i, cpus[i] + gpus[i] + oths[i]/2, f'{oths[i]:.1f}', ha='center', va='center', fontsize=9, color='black', fontweight='bold')

        ax.set_ylabel('Power (W)', fontsize=11)
        ax.set_title(f'{AB}: Attribution Validation', fontsize=13, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10)
        ax.legend(fontsize=9, loc='upper left')
        ax.set_ylim(0, max(totals) * 1.15)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

        # Error annotation
        expected_total = (a_cpu+b_cpu) + (a_gpu+b_gpu) + (a_oth+b_oth)
        measured_total = ab_cpu + ab_gpu + ab_oth
        error_pct = ((measured_total - expected_total) / expected_total * 100) if expected_total > 0 else 0
        ax.text(0.98, 0.95, f'Error: {error_pct:+.1f}%',
                transform=ax.transAxes, fontsize=11, ha='right', va='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'attribution_stacked.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: attribution_stacked.png")


def create_ratio_comparison_chart(data):
    """
    교수님 핵심: "비슷한 비율로 나누어 갖는 모습이 나와야"
    Solo에서의 A:B 비율 vs Concurrent에서의 A:B 비율 비교
    """
    idle = data['Idle']

    combos = [
        ('A1', 'B1', 'A1+B1'),
        ('A1', 'B2', 'A1+B2'),
        ('A2', 'B1', 'A2+B1'),
        ('A2', 'B2', 'A2+B2'),
    ]

    fig, axes = plt.subplots(1, 4, figsize=(20, 6))

    for idx, (A, B, AB) in enumerate(combos):
        ax = axes[idx]

        # Solo 책임분
        a_total = (data[A]['wall'] - idle['wall'])
        b_total = (data[B]['wall'] - idle['wall'])
        sum_solo = a_total + b_total

        # Concurrent delta
        ab_total = data[AB]['wall'] - idle['wall']

        # 비율 계산
        if sum_solo > 0:
            a_ratio_solo = a_total / sum_solo * 100
            b_ratio_solo = b_total / sum_solo * 100
        else:
            a_ratio_solo, b_ratio_solo = 50, 50

        # Concurrent에서 A,B를 Solo 비율대로 나누면:
        a_attributed = ab_total * (a_total / sum_solo) if sum_solo > 0 else 0
        b_attributed = ab_total * (b_total / sum_solo) if sum_solo > 0 else 0

        # Bar chart: Solo vs Attributed
        labels = [f'{A}\nSolo', f'{A}\nAttributed', f'{B}\nSolo', f'{B}\nAttributed']
        values = [a_total, a_attributed, b_total, b_attributed]
        colors = ['#FF6B6B', '#FFAAAA', '#4DABF7', '#A5D8FF']

        bars = ax.bar(labels, values, color=colors, edgecolor='black', linewidth=0.5)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f'{val:.1f}W', ha='center', va='bottom', fontsize=10)

        ax.set_ylabel('Power (W)', fontsize=11)
        ax.set_title(f'{AB}\n(A:B = {a_ratio_solo:.0f}:{b_ratio_solo:.0f})', fontsize=12, fontweight='bold')
        ax.set_ylim(0, max(values) * 1.25)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'ratio_comparison.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: ratio_comparison.png")


def create_summary_table(data):
    """Print full summary table"""
    idle = data['Idle']

    combos = [('A1','B1','A1+B1'), ('A1','B2','A1+B2'),
              ('A2','B1','A2+B1'), ('A2','B2','A2+B2')]

    print("\n" + "="*120)
    print("Attribution Validation Summary (Wall Power 기준)")
    print("="*120)
    print(f"{'Combo':<10} {'A Solo':<12} {'B Solo':<12} {'Sum(A+B)':<12} {'Concurrent':<12} "
          f"{'Error':<10} {'A ratio(Solo)':<14} {'A ratio(Conc)':<14}")
    print("-"*120)

    for A, B, AB in combos:
        a_delta = data[A]['wall'] - idle['wall']
        b_delta = data[B]['wall'] - idle['wall']
        sum_ab = a_delta + b_delta
        conc_delta = data[AB]['wall'] - idle['wall']
        error = conc_delta - sum_ab
        error_pct = error / sum_ab * 100 if sum_ab > 0 else 0

        a_ratio_solo = a_delta / sum_ab * 100 if sum_ab > 0 else 0
        a_ratio_conc = a_delta / conc_delta * 100 if conc_delta > 0 else 0

        print(f"{AB:<10} {a_delta:<12.1f} {b_delta:<12.1f} {sum_ab:<12.1f} {conc_delta:<12.1f} "
              f"{error:+10.1f} {a_ratio_solo:<14.1f} {a_ratio_conc:<14.1f}")

    print("="*120)


if __name__ == "__main__":
    data = load_all()
    create_attribution_chart(data)
    create_ratio_comparison_chart(data)
    create_summary_table(data)
