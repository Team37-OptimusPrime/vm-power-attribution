#!/usr/bin/env python3
"""
Energy Attribution Validation Analysis
교수님의 validation 방법: Concurrent 실행 결과를 바탕으로
A 책임에너지, B 책임에너지, 시스템 기본에너지로 분리하고
Solo 실행 결과와 비교하여 모델 검증
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

# Paths
BASE_DIR = Path("/Users/rainyforest/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution")
DATA_DIR = BASE_DIR / "data/raw/alienware/phase1.6_test2"
OUTPUT_DIR = BASE_DIR / "reports/phase1.6/validation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Phase definitions
PHASES = {
    'Idle': {'file': 'baseline_host.csv', 'start': 5, 'end': -3},
    'A1': {'file': 'A1_yolo_nano_host.csv', 'start': 5, 'end': -5},
    'A2': {'file': 'A2_yolo_medium_host.csv', 'start': 5, 'end': -5},
    'B1': {'file': 'B1_nodejs_light_host.csv', 'start': 5, 'end': -3},
    'B2': {'file': 'B2_nodejs_heavy_host.csv', 'start': 5, 'end': -3},
    'A1+B1': {'file': 'A1B1_concurrent_host.csv', 'start': 5, 'end': -5},
    'A1+B2': {'file': 'A1B2_concurrent_host.csv', 'start': 5, 'end': -5},
    'A2+B1': {'file': 'A2B1_concurrent_host.csv', 'start': 5, 'end': -5},
    'A2+B2': {'file': 'A2B2_concurrent_host.csv', 'start': 5, 'end': -5},
}

def load_data():
    """Load all phase data"""
    results = {}
    for phase_name, phase_info in PHASES.items():
        filepath = DATA_DIR / phase_info['file']
        df = pd.read_csv(filepath)
        df_trimmed = df.iloc[phase_info['start']:phase_info['end']]

        results[phase_name] = {
            'cpu': df_trimmed['rapl_package_w'].mean(),
            'gpu': df_trimmed['gpu_power_w'].mean(),
        }
    return results

def calculate_attribution(results):
    """
    교수님의 귀속 원칙 적용:
    - CPU: 사용량 기준 (단순 빼기)
    - GPU: 할당 비율 기준 (YOLO만 GPU 사용)
    - Others: 메모리 할당 비율 기준
    """

    idle_cpu = results['Idle']['cpu']
    idle_gpu = results['Idle']['gpu']

    # Solo 실행 시 워크로드 책임분 (Baseline을 뺀 값)
    solo_attribution = {}
    for workload in ['A1', 'A2', 'B1', 'B2']:
        solo_attribution[workload] = {
            'cpu': results[workload]['cpu'] - idle_cpu,
            'gpu': results[workload]['gpu'] - idle_gpu,
            'total': results[workload]['cpu'] + results[workload]['gpu'] - idle_cpu - idle_gpu
        }

    # Concurrent 실행 결과 분석
    concurrent_analysis = {}

    for combo in ['A1+B1', 'A1+B2', 'A2+B1', 'A2+B2']:
        A, B = combo.split('+')

        # 실측값 (Concurrent 실행)
        measured_cpu = results[combo]['cpu']
        measured_gpu = results[combo]['gpu']
        measured_total = measured_cpu + measured_gpu

        # 예측값 (Solo 책임분의 합 + Idle)
        # Expected = (A solo - Idle) + (B solo - Idle) + Idle
        #          = A solo + B solo - Idle
        expected_cpu = results[A]['cpu'] + results[B]['cpu'] - idle_cpu
        expected_gpu = results[A]['gpu'] + results[B]['gpu'] - idle_gpu
        expected_total = expected_cpu + expected_gpu

        # 오차
        error_cpu = measured_cpu - expected_cpu
        error_gpu = measured_gpu - expected_gpu
        error_total = measured_total - expected_total
        error_pct = (error_total / expected_total) * 100 if expected_total > 0 else 0

        concurrent_analysis[combo] = {
            'A': A, 'B': B,
            # 실측값
            'measured_cpu': measured_cpu,
            'measured_gpu': measured_gpu,
            'measured_total': measured_total,
            # 예측값
            'expected_cpu': expected_cpu,
            'expected_gpu': expected_gpu,
            'expected_total': expected_total,
            # Solo 책임분
            'A_solo_cpu': solo_attribution[A]['cpu'],
            'A_solo_gpu': solo_attribution[A]['gpu'],
            'B_solo_cpu': solo_attribution[B]['cpu'],
            'B_solo_gpu': solo_attribution[B]['gpu'],
            # 오차
            'error_cpu': error_cpu,
            'error_gpu': error_gpu,
            'error_total': error_total,
            'error_pct': error_pct,
        }

    return solo_attribution, concurrent_analysis

def create_validation_table(solo_attr, concurrent_analysis):
    """Create validation table"""

    print("\n" + "="*100)
    print("Energy Attribution Validation")
    print("="*100)

    for combo, data in concurrent_analysis.items():
        A, B = data['A'], data['B']

        print(f"\n[{combo}]")
        print("-" * 100)
        print(f"{'Component':<20} {'Solo A':<15} {'Solo B':<15} {'Expected':<15} {'Measured':<15} {'Error':>10}")
        print("-" * 100)

        # CPU
        cpu_expected = data['expected_cpu']
        cpu_measured = data['measured_cpu']
        cpu_error = data['error_cpu']
        print(f"{'CPU (W)':<20} {data['A_solo_cpu']:<15.1f} {data['B_solo_cpu']:<15.1f} "
              f"{cpu_expected:<15.1f} {cpu_measured:<15.1f} {cpu_error:>+10.1f}")

        # GPU
        gpu_expected = data['expected_gpu']
        gpu_measured = data['measured_gpu']
        gpu_error = data['error_gpu']
        print(f"{'GPU (W)':<20} {data['A_solo_gpu']:<15.1f} {data['B_solo_gpu']:<15.1f} "
              f"{gpu_expected:<15.1f} {gpu_measured:<15.1f} {gpu_error:>+10.1f}")

        # Total
        total_expected = data['expected_total']
        total_measured = data['measured_total']
        total_error = data['error_total']
        print(f"{'Total (W)':<20} {'-':<15} {'-':<15} "
              f"{total_expected:<15.1f} {total_measured:<15.1f} {total_error:>+10.1f}")

        print(f"\nError: {data['error_pct']:+.1f}%")

    print("\n" + "="*100)

def create_validation_chart(solo_attr, concurrent_analysis):
    """Create validation comparison chart"""

    combos = list(concurrent_analysis.keys())
    n_combos = len(combos)

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    axes = axes.flatten()

    for idx, combo in enumerate(combos):
        ax = axes[idx]
        data = concurrent_analysis[combo]
        A, B = data['A'], data['B']

        categories = ['CPU', 'GPU', 'Total']
        x = np.arange(len(categories))
        width = 0.25

        # Solo A 책임분
        solo_a = [data['A_solo_cpu'], data['A_solo_gpu'],
                  data['A_solo_cpu'] + data['A_solo_gpu']]

        # Solo B 책임분
        solo_b = [data['B_solo_cpu'], data['B_solo_gpu'],
                  data['B_solo_cpu'] + data['B_solo_gpu']]

        # Expected (A + B)
        expected = [data['expected_cpu'], data['expected_gpu'], data['expected_total']]

        # Measured (Concurrent)
        measured = [data['measured_cpu'], data['measured_gpu'], data['measured_total']]

        # Bars
        bars1 = ax.bar(x - width*1.5, solo_a, width, label=f'{A} Solo', color='#FF6B6B', alpha=0.8)
        bars2 = ax.bar(x - width*0.5, solo_b, width, label=f'{B} Solo', color='#4DABF7', alpha=0.8)
        bars3 = ax.bar(x + width*0.5, expected, width, label='Expected (A+B)', color='#FCC419', alpha=0.8)
        bars4 = ax.bar(x + width*1.5, measured, width, label='Measured (Concurrent)', color='#9775FA', alpha=0.8)

        ax.set_ylabel('Power (W)', fontsize=11)
        ax.set_title(f'{combo}: Validation', fontsize=13, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(categories)
        ax.legend(fontsize=9, loc='upper left')
        ax.grid(axis='y', alpha=0.3)

        # Error annotation
        error_text = f'Error: {data["error_pct"]:+.1f}%'
        ax.text(0.98, 0.95, error_text, transform=ax.transAxes,
                fontsize=10, ha='right', va='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        # Value labels on bars
        for bars in [bars1, bars2, bars3, bars4]:
            for bar in bars:
                height = bar.get_height()
                if height > 1:  # Only show labels for significant values
                    ax.text(bar.get_x() + bar.get_width()/2, height,
                           f'{height:.0f}', ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'validation_comparison.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nSaved: {OUTPUT_DIR / 'validation_comparison.png'}")

def create_error_analysis_chart(concurrent_analysis):
    """Create error analysis chart"""

    combos = list(concurrent_analysis.keys())
    cpu_errors = [concurrent_analysis[c]['error_cpu'] for c in combos]
    gpu_errors = [concurrent_analysis[c]['error_gpu'] for c in combos]
    total_errors = [concurrent_analysis[c]['error_total'] for c in combos]

    x = np.arange(len(combos))
    width = 0.25

    fig, ax = plt.subplots(figsize=(12, 6))

    bars1 = ax.bar(x - width, cpu_errors, width, label='CPU Error', color='#FF6B6B')
    bars2 = ax.bar(x, gpu_errors, width, label='GPU Error', color='#4DABF7')
    bars3 = ax.bar(x + width, total_errors, width, label='Total Error', color='#9775FA')

    ax.set_ylabel('Error (W)', fontsize=12)
    ax.set_title('Energy Attribution Error Analysis', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(combos)
    ax.legend()
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax.grid(axis='y', alpha=0.3)

    # Value labels
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2, height,
                   f'{height:+.1f}', ha='center',
                   va='bottom' if height >= 0 else 'top', fontsize=9)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'error_analysis.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {OUTPUT_DIR / 'error_analysis.png'}")

def export_csv_table(solo_attr, concurrent_analysis):
    """Export validation table to CSV"""

    # Validation table
    rows = []
    for combo, data in concurrent_analysis.items():
        rows.append({
            'Combination': combo,
            'Workload_A': data['A'],
            'Workload_B': data['B'],
            'A_Solo_CPU_W': data['A_solo_cpu'],
            'A_Solo_GPU_W': data['A_solo_gpu'],
            'B_Solo_CPU_W': data['B_solo_cpu'],
            'B_Solo_GPU_W': data['B_solo_gpu'],
            'Expected_CPU_W': data['expected_cpu'],
            'Expected_GPU_W': data['expected_gpu'],
            'Expected_Total_W': data['expected_total'],
            'Measured_CPU_W': data['measured_cpu'],
            'Measured_GPU_W': data['measured_gpu'],
            'Measured_Total_W': data['measured_total'],
            'Error_CPU_W': data['error_cpu'],
            'Error_GPU_W': data['error_gpu'],
            'Error_Total_W': data['error_total'],
            'Error_Pct': data['error_pct'],
        })

    df = pd.DataFrame(rows)
    output_file = OUTPUT_DIR / 'validation_table.csv'
    df.to_csv(output_file, index=False, float_format='%.2f')
    print(f"Saved: {output_file}")

    return df

def main():
    print("="*80)
    print("Energy Attribution Validation Analysis")
    print("="*80)

    # Load data
    print("\nLoading data...")
    results = load_data()

    # Calculate attribution
    print("Calculating energy attribution...")
    solo_attr, concurrent_analysis = calculate_attribution(results)

    # Create table
    create_validation_table(solo_attr, concurrent_analysis)

    # Create charts
    print("\nGenerating charts...")
    create_validation_chart(solo_attr, concurrent_analysis)
    create_error_analysis_chart(concurrent_analysis)

    # Export CSV
    print("\nExporting CSV...")
    df = export_csv_table(solo_attr, concurrent_analysis)

    print(f"\n{'='*80}")
    print("Analysis complete!")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
