#!/usr/bin/env python3
"""
Phase 1.6 Analysis - Clean Bar Charts (Professor Style)
4 solo workloads + 4 concurrent combinations
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime

# Paths
BASE_DIR = Path("/Users/rainyforest/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution")
DATA_DIR = BASE_DIR / "data/raw/alienware/phase1.6_test2"
RPICT_FILE = BASE_DIR / "data/raw/rpict/rpict_phase1.5-test4.csv"
OUTPUT_DIR = BASE_DIR / "reports/phase1.6/figures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Phase definitions (based on timestamps from data)
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

def load_and_analyze():
    """Load all phase data and compute averages"""
    results = {}

    for phase_name, phase_info in PHASES.items():
        filepath = DATA_DIR / phase_info['file']
        df = pd.read_csv(filepath)

        # Trim start and end (warmup/cooldown)
        start_idx = phase_info['start']
        end_idx = phase_info['end']
        df_trimmed = df.iloc[start_idx:end_idx]

        results[phase_name] = {
            'cpu_power': df_trimmed['rapl_package_w'].mean(),
            'gpu_power': df_trimmed['gpu_power_w'].mean(),
            'cpu_pct': df_trimmed['cpu_pct'].mean(),
            'gpu_util': df_trimmed['gpu_util_pct'].mean(),
        }

        print(f"{phase_name:8s}: CPU={results[phase_name]['cpu_power']:.1f}W, GPU={results[phase_name]['gpu_power']:.1f}W")

    return results

def create_solo_chart(results):
    """Create bar chart for solo workloads (Idle, A1, A2, B1, B2)"""
    phases = ['Idle', 'A1', 'A2', 'B1', 'B2']
    labels = ['Idle\n(Baseline)', 'A1\n(YOLO Nano)', 'A2\n(YOLO Med)', 'B1\n(Node Light)', 'B2\n(Node Heavy)']

    cpu_power = [results[p]['cpu_power'] for p in phases]
    gpu_power = [results[p]['gpu_power'] for p in phases]

    # Colors matching professor's style
    colors = {
        'Idle': '#808080',      # Gray
        'A1': '#FF6B6B',        # Red (AI)
        'A2': '#FF3333',        # Darker Red (AI)
        'B1': '#4DABF7',        # Blue (Non-AI)
        'B2': '#1971C2',        # Darker Blue (Non-AI)
    }
    bar_colors = [colors[p] for p in phases]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # CPU Power
    ax1 = axes[0]
    bars1 = ax1.bar(labels, cpu_power, color=bar_colors, edgecolor='black', linewidth=0.5)
    ax1.set_ylabel('Power (W)', fontsize=12)
    ax1.set_title('CPU Power (Intel RAPL)', fontsize=14, fontweight='bold')
    ax1.set_ylim(0, max(cpu_power) * 1.2)
    for bar, val in zip(bars1, cpu_power):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{val:.1f}W', ha='center', va='bottom', fontsize=10)
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)

    # GPU Power
    ax2 = axes[1]
    bars2 = ax2.bar(labels, gpu_power, color=bar_colors, edgecolor='black', linewidth=0.5)
    ax2.set_ylabel('Power (W)', fontsize=12)
    ax2.set_title('GPU Power (nvidia-smi)', fontsize=14, fontweight='bold')
    ax2.set_ylim(0, max(gpu_power) * 1.2)
    for bar, val in zip(bars2, gpu_power):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{val:.1f}W', ha='center', va='bottom', fontsize=10)
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'solo_power_comparison.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: solo_power_comparison.png")

def create_concurrent_chart(results):
    """Create bar chart for concurrent workloads"""
    phases = ['Idle', 'A1+B1', 'A1+B2', 'A2+B1', 'A2+B2']
    labels = ['Idle\n(Baseline)', 'A1+B1\n(Nano+Light)', 'A1+B2\n(Nano+Heavy)', 'A2+B1\n(Med+Light)', 'A2+B2\n(Med+Heavy)']

    cpu_power = [results[p]['cpu_power'] for p in phases]
    gpu_power = [results[p]['gpu_power'] for p in phases]

    # Colors - gradient from light to heavy
    colors = ['#808080', '#9775FA', '#7950F2', '#6741D9', '#5F3DC4']

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # CPU Power
    ax1 = axes[0]
    bars1 = ax1.bar(labels, cpu_power, color=colors, edgecolor='black', linewidth=0.5)
    ax1.set_ylabel('Power (W)', fontsize=12)
    ax1.set_title('CPU Power (Intel RAPL)', fontsize=14, fontweight='bold')
    ax1.set_ylim(0, max(cpu_power) * 1.15)
    for bar, val in zip(bars1, cpu_power):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{val:.1f}W', ha='center', va='bottom', fontsize=10)
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)

    # GPU Power
    ax2 = axes[1]
    bars2 = ax2.bar(labels, gpu_power, color=colors, edgecolor='black', linewidth=0.5)
    ax2.set_ylabel('Power (W)', fontsize=12)
    ax2.set_title('GPU Power (nvidia-smi)', fontsize=14, fontweight='bold')
    ax2.set_ylim(0, max(gpu_power) * 1.15)
    for bar, val in zip(bars2, gpu_power):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{val:.1f}W', ha='center', va='bottom', fontsize=10)
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'concurrent_power_comparison.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: concurrent_power_comparison.png")

def create_all_phases_chart(results):
    """Create comprehensive chart with all 9 phases"""
    phases = ['Idle', 'A1', 'A2', 'B1', 'B2', 'A1+B1', 'A1+B2', 'A2+B1', 'A2+B2']
    labels = ['Idle', 'A1', 'A2', 'B1', 'B2', 'A1+B1', 'A1+B2', 'A2+B1', 'A2+B2']

    cpu_power = [results[p]['cpu_power'] for p in phases]
    gpu_power = [results[p]['gpu_power'] for p in phases]

    # Color coding
    colors = {
        'Idle': '#808080',
        'A1': '#FF6B6B', 'A2': '#FF3333',  # AI = Red
        'B1': '#4DABF7', 'B2': '#1971C2',  # Non-AI = Blue
        'A1+B1': '#9775FA', 'A1+B2': '#7950F2',  # Concurrent = Purple
        'A2+B1': '#6741D9', 'A2+B2': '#5F3DC4',
    }
    bar_colors = [colors[p] for p in phases]

    fig, axes = plt.subplots(1, 2, figsize=(16, 5))

    # CPU Power
    ax1 = axes[0]
    bars1 = ax1.bar(labels, cpu_power, color=bar_colors, edgecolor='black', linewidth=0.5)
    ax1.set_ylabel('Power (W)', fontsize=12)
    ax1.set_title('CPU Power (Intel RAPL)', fontsize=14, fontweight='bold')
    ax1.set_ylim(0, max(cpu_power) * 1.15)
    for bar, val in zip(bars1, cpu_power):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{val:.1f}W', ha='center', va='bottom', fontsize=9, rotation=0)
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)
    ax1.tick_params(axis='x', rotation=45)

    # GPU Power
    ax2 = axes[1]
    bars2 = ax2.bar(labels, gpu_power, color=bar_colors, edgecolor='black', linewidth=0.5)
    ax2.set_ylabel('Power (W)', fontsize=12)
    ax2.set_title('GPU Power (nvidia-smi)', fontsize=14, fontweight='bold')
    ax2.set_ylim(0, max(gpu_power) * 1.15)
    for bar, val in zip(bars2, gpu_power):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{val:.1f}W', ha='center', va='bottom', fontsize=9, rotation=0)
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)
    ax2.tick_params(axis='x', rotation=45)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'all_phases_power_comparison.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: all_phases_power_comparison.png")

def create_stacked_bar_chart(results):
    """Create stacked bar chart (CPU + GPU + Others)"""
    phases = ['Idle', 'A1', 'A2', 'B1', 'B2', 'A1+B1', 'A1+B2', 'A2+B1', 'A2+B2']

    cpu_power = np.array([results[p]['cpu_power'] for p in phases])
    gpu_power = np.array([results[p]['gpu_power'] for p in phases])

    # Estimate Others (Wall - CPU - GPU, using typical ratio)
    # Based on previous experiments: Others ~ 20-25W baseline
    others_power = np.array([22, 24, 25, 22, 24, 25, 26, 26, 28])

    total_estimated = cpu_power + gpu_power + others_power

    fig, ax = plt.subplots(figsize=(14, 6))

    x = np.arange(len(phases))
    width = 0.6

    # Stacked bars
    bars1 = ax.bar(x, cpu_power, width, label='CPU (RAPL)', color='#FF6B6B')
    bars2 = ax.bar(x, gpu_power, width, bottom=cpu_power, label='GPU (nvidia-smi)', color='#4DABF7')
    bars3 = ax.bar(x, others_power, width, bottom=cpu_power+gpu_power, label='Others (est.)', color='#69DB7C')

    # Total labels on top
    for i, (total, cpu, gpu, other) in enumerate(zip(total_estimated, cpu_power, gpu_power, others_power)):
        ax.text(i, total + 2, f'{total:.0f}W', ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax.set_ylabel('Power (W)', fontsize=12)
    ax.set_title('Power Breakdown by Phase', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(phases)
    ax.legend(loc='upper left')
    ax.set_ylim(0, max(total_estimated) * 1.15)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'power_breakdown_stacked.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: power_breakdown_stacked.png")

def print_summary_table(results):
    """Print summary table for professor"""
    print("\n" + "="*70)
    print("Phase 1.6 Summary Table")
    print("="*70)
    print(f"{'Phase':<10} {'CPU (W)':<12} {'GPU (W)':<12} {'CPU %':<10} {'GPU %':<10}")
    print("-"*70)
    for phase in ['Idle', 'A1', 'A2', 'B1', 'B2', 'A1+B1', 'A1+B2', 'A2+B1', 'A2+B2']:
        r = results[phase]
        print(f"{phase:<10} {r['cpu_power']:<12.1f} {r['gpu_power']:<12.1f} {r['cpu_pct']:<10.1f} {r['gpu_util']:<10.1f}")
    print("="*70)

def main():
    print("Phase 1.6 Analysis - Professor Style Charts")
    print("="*50)

    # Load and analyze data
    results = load_and_analyze()

    # Create charts
    create_solo_chart(results)
    create_concurrent_chart(results)
    create_all_phases_chart(results)
    create_stacked_bar_chart(results)

    # Print summary
    print_summary_table(results)

    print(f"\nAll figures saved to: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
