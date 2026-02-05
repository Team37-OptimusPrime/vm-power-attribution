#!/usr/bin/env python3
"""
Phase 1 실험 결과 시각화: YOLO vs Node.js 전력 비교 (Host 환경)
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from datetime import datetime

# 경로 설정
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data" / "raw"
OUTPUT_DIR = BASE_DIR / "docs" / "figures" / "phase1"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 한글 폰트 설정 (macOS)
plt.rcParams['font.family'] = ['Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

def load_data():
    """데이터 로드"""
    data = {}

    # Alienware 데이터
    alienware_dir = DATA_DIR / "alienware"
    for name in ['baseline', 'yolo_solo', 'nodejs_solo', 'concurrent']:
        filepath = alienware_dir / f"{name}.csv"
        if filepath.exists():
            df = pd.read_csv(filepath)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            data[name] = df
            print(f"Loaded {name}: {len(df)} rows")

    # RPICT 데이터
    rpict_file = DATA_DIR / "rpict" / "rpict_phase1_test1.csv"
    if rpict_file.exists():
        df = pd.read_csv(rpict_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        data['rpict'] = df
        print(f"Loaded RPICT: {len(df)} rows")

    return data

def calculate_stats(data):
    """각 phase별 통계 계산"""
    stats = {}

    for name, df in data.items():
        if name == 'rpict':
            stats[name] = {
                'wall_power_mean': df['power1_w'].mean(),
                'wall_power_std': df['power1_w'].std(),
                'wall_power_max': df['power1_w'].max(),
            }
        else:
            stats[name] = {
                'cpu_pct_mean': df['cpu_pct'].mean(),
                'rapl_mean': df['rapl_package_w'].mean(),
                'rapl_std': df['rapl_package_w'].std(),
                'gpu_power_mean': df['gpu_power_w'].mean(),
                'gpu_power_std': df['gpu_power_w'].std(),
                'gpu_util_mean': df['gpu_util_pct'].mean(),
                'total_internal': df['rapl_package_w'].mean() + df['gpu_power_w'].mean(),
            }

    return stats

def plot_power_comparison(data, stats):
    """전력 비교 바 차트"""
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))

    phases = ['baseline', 'yolo_solo', 'nodejs_solo', 'concurrent']
    labels = ['Idle', 'YOLO\n(AI)', 'Node.js\n(Non-AI)', 'Concurrent']
    colors = ['#95a5a6', '#e74c3c', '#3498db', '#9b59b6']

    # CPU Power (RAPL)
    ax = axes[0]
    values = [stats[p]['rapl_mean'] for p in phases]
    errors = [stats[p]['rapl_std'] for p in phases]
    bars = ax.bar(labels, values, yerr=errors, capsize=5, color=colors, edgecolor='black')
    ax.set_ylabel('Power (W)')
    ax.set_title('CPU Power (RAPL Package)')
    ax.set_ylim(0, 45)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2,
                f'{val:.1f}W', ha='center', va='bottom', fontsize=10)

    # GPU Power
    ax = axes[1]
    values = [stats[p]['gpu_power_mean'] for p in phases]
    errors = [stats[p]['gpu_power_std'] for p in phases]
    bars = ax.bar(labels, values, yerr=errors, capsize=5, color=colors, edgecolor='black')
    ax.set_ylabel('Power (W)')
    ax.set_title('GPU Power (nvidia-smi)')
    ax.set_ylim(0, 55)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2,
                f'{val:.1f}W', ha='center', va='bottom', fontsize=10)

    # Total Internal Power
    ax = axes[2]
    values = [stats[p]['total_internal'] for p in phases]
    bars = ax.bar(labels, values, color=colors, edgecolor='black')
    ax.set_ylabel('Power (W)')
    ax.set_title('Total Internal Power\n(CPU + GPU)')
    ax.set_ylim(0, 85)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2,
                f'{val:.1f}W', ha='center', va='bottom', fontsize=10)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'power_comparison.png', dpi=150, bbox_inches='tight')
    plt.savefig(OUTPUT_DIR / 'power_comparison.pdf', bbox_inches='tight')
    print(f"Saved: power_comparison.png/pdf")
    plt.close()

def plot_timeseries(data):
    """시계열 그래프"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    plots = [
        ('baseline', 'Baseline (Idle)', axes[0, 0]),
        ('yolo_solo', 'YOLO Solo (AI Workload)', axes[0, 1]),
        ('nodejs_solo', 'Node.js Solo (Non-AI Workload)', axes[1, 0]),
        ('concurrent', 'Concurrent (YOLO + Node.js)', axes[1, 1]),
    ]

    for name, title, ax in plots:
        if name not in data:
            continue
        df = data[name]

        # 시간을 0부터 시작하도록 변환
        t0 = df['timestamp'].iloc[0]
        elapsed = (df['timestamp'] - t0).dt.total_seconds()

        ax.plot(elapsed, df['rapl_package_w'], label='CPU (RAPL)', color='#e74c3c', linewidth=1.5)
        ax.plot(elapsed, df['gpu_power_w'], label='GPU', color='#3498db', linewidth=1.5)
        ax.fill_between(elapsed, 0, df['rapl_package_w'], alpha=0.3, color='#e74c3c')
        ax.fill_between(elapsed, 0, df['gpu_power_w'], alpha=0.3, color='#3498db')

        ax.set_xlabel('Time (seconds)')
        ax.set_ylabel('Power (W)')
        ax.set_title(title)
        ax.legend(loc='upper right')
        ax.set_ylim(0, 60)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'timeseries.png', dpi=150, bbox_inches='tight')
    plt.savefig(OUTPUT_DIR / 'timeseries.pdf', bbox_inches='tight')
    print(f"Saved: timeseries.png/pdf")
    plt.close()

def plot_energy_attribution(stats):
    """에너지 귀속 비교 (핵심 그래프)"""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # 왼쪽: 리소스 할당 (가정: 동일)
    ax = axes[0]
    labels = ['YOLO (AI)', 'Node.js (Non-AI)']
    sizes = [50, 50]  # 동일 리소스 가정
    colors = ['#e74c3c', '#3498db']
    ax.pie(sizes, labels=labels, colors=colors, autopct='%1.0f%%',
           startangle=90, textprops={'fontsize': 12})
    ax.set_title('Resource Allocation\n(Assumed Equal)', fontsize=14)

    # 오른쪽: 실제 에너지 소비
    ax = axes[1]
    yolo_power = stats['yolo_solo']['total_internal']
    nodejs_power = stats['nodejs_solo']['total_internal']
    total = yolo_power + nodejs_power
    sizes = [yolo_power/total*100, nodejs_power/total*100]

    wedges, texts, autotexts = ax.pie(sizes, labels=labels, colors=colors,
                                       autopct='%1.0f%%', startangle=90,
                                       textprops={'fontsize': 12})
    ax.set_title('Actual Energy Consumption\n(Measured)', fontsize=14)

    # 범례에 실제 값 추가
    legend_labels = [f'YOLO: {yolo_power:.1f}W', f'Node.js: {nodejs_power:.1f}W']
    ax.legend(wedges, legend_labels, loc='lower center', bbox_to_anchor=(0.5, -0.1))

    plt.suptitle('Resource-based vs Energy-based Attribution', fontsize=16, y=1.02)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'energy_attribution.png', dpi=150, bbox_inches='tight')
    plt.savefig(OUTPUT_DIR / 'energy_attribution.pdf', bbox_inches='tight')
    print(f"Saved: energy_attribution.png/pdf")
    plt.close()

def plot_key_finding(stats):
    """핵심 발견 그래프 (논문용)"""
    fig, ax = plt.subplots(figsize=(10, 6))

    # 데이터 준비
    categories = ['CPU Power\n(RAPL)', 'GPU Power', 'Total Power']
    yolo_vals = [
        stats['yolo_solo']['rapl_mean'],
        stats['yolo_solo']['gpu_power_mean'],
        stats['yolo_solo']['total_internal']
    ]
    nodejs_vals = [
        stats['nodejs_solo']['rapl_mean'],
        stats['nodejs_solo']['gpu_power_mean'],
        stats['nodejs_solo']['total_internal']
    ]

    x = np.arange(len(categories))
    width = 0.35

    bars1 = ax.bar(x - width/2, yolo_vals, width, label='YOLO (AI)', color='#e74c3c', edgecolor='black')
    bars2 = ax.bar(x + width/2, nodejs_vals, width, label='Node.js (Non-AI)', color='#3498db', edgecolor='black')

    # 값 표시
    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{bar.get_height():.1f}W', ha='center', va='bottom', fontsize=11, fontweight='bold')
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{bar.get_height():.1f}W', ha='center', va='bottom', fontsize=11)

    # 배율 표시
    for i, (y, n) in enumerate(zip(yolo_vals, nodejs_vals)):
        ratio = y / n if n > 0 else 0
        ax.annotate(f'{ratio:.1f}x', xy=(i, max(y, n) + 8), ha='center',
                   fontsize=12, color='#2c3e50', fontweight='bold')

    ax.set_ylabel('Power (W)', fontsize=12)
    ax.set_title('Power Consumption: AI vs Non-AI Workload\n(Same Resource Allocation)', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=11)
    ax.legend(fontsize=11)
    ax.set_ylim(0, 85)
    ax.grid(True, axis='y', alpha=0.3)

    # 핵심 메시지
    ax.text(0.5, -0.15,
            'Key Finding: With equal resource allocation, AI workload consumes 4-5x more energy than Non-AI workload',
            transform=ax.transAxes, ha='center', fontsize=11, style='italic',
            bbox=dict(boxstyle='round', facecolor='#f9e79f', alpha=0.8))

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'key_finding.png', dpi=150, bbox_inches='tight')
    plt.savefig(OUTPUT_DIR / 'key_finding.pdf', bbox_inches='tight')
    print(f"Saved: key_finding.png/pdf")
    plt.close()

def generate_summary_table(stats):
    """요약 테이블 생성"""
    rows = []

    for name, label in [('baseline', 'Idle'), ('yolo_solo', 'YOLO (AI)'),
                         ('nodejs_solo', 'Node.js'), ('concurrent', 'Concurrent')]:
        if name in stats:
            s = stats[name]
            rows.append({
                'Phase': label,
                'CPU %': f"{s['cpu_pct_mean']:.1f}",
                'CPU Power (W)': f"{s['rapl_mean']:.1f} ± {s['rapl_std']:.1f}",
                'GPU Power (W)': f"{s['gpu_power_mean']:.1f} ± {s['gpu_power_std']:.1f}",
                'GPU Util %': f"{s['gpu_util_mean']:.1f}",
                'Total (W)': f"{s['total_internal']:.1f}",
            })

    df = pd.DataFrame(rows)

    # Markdown 저장
    md_path = OUTPUT_DIR / 'summary_table.md'
    with open(md_path, 'w') as f:
        f.write("# Phase 1 실험 결과 요약\n\n")
        f.write(f"실험 일시: 2026-02-05\n\n")
        f.write("## 전력 측정 결과\n\n")
        f.write(df.to_markdown(index=False))
        f.write("\n\n## 핵심 발견\n\n")

        yolo = stats['yolo_solo']['total_internal']
        nodejs = stats['nodejs_solo']['total_internal']
        ratio = yolo / nodejs

        f.write(f"- YOLO (AI) 총 전력: **{yolo:.1f}W**\n")
        f.write(f"- Node.js (Non-AI) 총 전력: **{nodejs:.1f}W**\n")
        f.write(f"- 전력 비율: **{ratio:.1f}x** (AI가 Non-AI 대비 {ratio:.1f}배 더 소비)\n")
        f.write(f"\n→ **동일 리소스 할당 시에도 에너지 소비는 크게 다름**\n")

    print(f"Saved: {md_path}")
    return df

def main():
    print("=" * 50)
    print("Phase 1 실험 결과 시각화")
    print("=" * 50)

    # 데이터 로드
    data = load_data()

    # 통계 계산
    stats = calculate_stats(data)

    print("\n--- Statistics ---")
    for name, s in stats.items():
        print(f"\n{name}:")
        for k, v in s.items():
            print(f"  {k}: {v:.2f}")

    # 그래프 생성
    print("\n--- Generating plots ---")
    plot_power_comparison(data, stats)
    plot_timeseries(data)
    plot_energy_attribution(stats)
    plot_key_finding(stats)

    # 요약 테이블
    print("\n--- Summary ---")
    df = generate_summary_table(stats)
    print(df.to_string(index=False))

    print(f"\n✅ All outputs saved to: {OUTPUT_DIR}")

if __name__ == '__main__':
    main()
