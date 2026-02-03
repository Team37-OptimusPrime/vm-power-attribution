#!/usr/bin/env python3
"""
Stress Test 결과 시각화
T-01 실험 (CPU stress-ng) 데이터 분석 및 시각화

Usage:
    python3 visualize_stress_test.py
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import numpy as np
from pathlib import Path

# 한글 폰트 설정 (macOS)
plt.rcParams['font.family'] = ['Arial Unicode MS', 'AppleGothic', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# 프로젝트 경로
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "figures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_host_data():
    """Host 측정 데이터 로드"""
    df = pd.read_csv(DATA_DIR / "host_stress_test.csv")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['elapsed_sec'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds()
    return df


def load_rpict_data():
    """RPICT 측정 데이터 로드"""
    # RPICT 데이터는 특수 포맷
    rows = []
    with open(DATA_DIR / "rpict_gpu_test.csv", 'r') as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) >= 2:
                time_str = parts[0]
                data_parts = parts[1].split()
                if len(data_parts) >= 2:
                    try:
                        power = abs(float(data_parts[1]))  # Power1, 절대값
                        rows.append({
                            'time_str': time_str,
                            'power_w': power
                        })
                    except (ValueError, IndexError):
                        continue

    df = pd.DataFrame(rows)
    # 날짜 추가 (2026-02-02)
    df['timestamp'] = pd.to_datetime('2026-02-02 ' + df['time_str'])
    df['elapsed_sec'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds()
    return df


def classify_state(cpu_pct):
    """CPU 사용률로 상태 분류"""
    if cpu_pct < 10:
        return 'Idle'
    elif cpu_pct >= 90:
        return 'Stress'
    else:
        return 'Transition'


def plot_timeseries(host_df, rpict_df):
    """시계열 전력 그래프"""
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    # 1. CPU 사용률
    ax1 = axes[0]
    ax1.fill_between(host_df['elapsed_sec'], host_df['cpu_pct'],
                     alpha=0.3, color='blue')
    ax1.plot(host_df['elapsed_sec'], host_df['cpu_pct'],
             color='blue', linewidth=1)
    ax1.set_ylabel('CPU Usage (%)', fontsize=12)
    ax1.set_ylim(0, 105)
    ax1.axhline(y=100, color='red', linestyle='--', alpha=0.5, label='100%')
    ax1.grid(True, alpha=0.3)
    ax1.set_title('T-01: CPU Stress Test (stress-ng --cpu 0 --timeout 30s × 3)',
                  fontsize=14, fontweight='bold')

    # Stress 구간 표시
    stress_periods = [
        (4, 34, 'Run 1'),
        (80, 110, 'Run 2'),
        (116, 146, 'Run 3')
    ]
    for start, end, label in stress_periods:
        ax1.axvspan(start, end, alpha=0.1, color='red')
        ax1.text((start+end)/2, 105, label, ha='center', fontsize=9, color='red')

    # 2. RAPL 전력
    ax2 = axes[1]
    ax2.plot(host_df['elapsed_sec'], host_df['rapl_package_w'],
             color='green', linewidth=1.5, label='Package (CPU+Uncore)')
    ax2.plot(host_df['elapsed_sec'], host_df['rapl_core_w'],
             color='limegreen', linewidth=1, alpha=0.7, label='Core only')
    ax2.fill_between(host_df['elapsed_sec'], host_df['rapl_package_w'],
                     alpha=0.2, color='green')
    ax2.set_ylabel('RAPL Power (W)', fontsize=12)
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(0, 140)

    # 평균값 표시
    idle_mask = host_df['cpu_pct'] < 10
    stress_mask = host_df['cpu_pct'] >= 90
    idle_avg = host_df.loc[idle_mask, 'rapl_package_w'].mean()
    stress_avg = host_df.loc[stress_mask, 'rapl_package_w'].mean()
    ax2.axhline(y=idle_avg, color='green', linestyle=':', alpha=0.5)
    ax2.axhline(y=stress_avg, color='green', linestyle=':', alpha=0.5)
    ax2.text(165, idle_avg, f'Idle: {idle_avg:.1f}W', fontsize=9, va='center')
    ax2.text(165, stress_avg, f'Stress: {stress_avg:.1f}W', fontsize=9, va='center')

    # 3. RPICT 실측 전력
    ax3 = axes[2]
    ax3.plot(rpict_df['elapsed_sec'], rpict_df['power_w'],
             color='orange', linewidth=2, marker='o', markersize=3, label='RPICT (Wall)')
    ax3.fill_between(rpict_df['elapsed_sec'], rpict_df['power_w'],
                     alpha=0.2, color='orange')
    ax3.set_ylabel('Wall Power (W)', fontsize=12)
    ax3.set_xlabel('Elapsed Time (seconds)', fontsize=12)
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)
    ax3.set_ylim(0, 250)

    # RPICT 평균값
    rpict_idle = rpict_df[rpict_df['power_w'] < 50]['power_w'].mean()
    rpict_stress = rpict_df[rpict_df['power_w'] >= 200]['power_w'].mean()
    ax3.axhline(y=rpict_idle, color='orange', linestyle=':', alpha=0.5)
    ax3.axhline(y=rpict_stress, color='orange', linestyle=':', alpha=0.5)
    ax3.text(165, rpict_idle, f'Idle: {rpict_idle:.1f}W', fontsize=9, va='center')
    ax3.text(165, rpict_stress, f'Stress: {rpict_stress:.1f}W', fontsize=9, va='center')

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'T01_timeseries.png', dpi=150, bbox_inches='tight')
    plt.savefig(OUTPUT_DIR / 'T01_timeseries.pdf', bbox_inches='tight')
    print(f"Saved: {OUTPUT_DIR / 'T01_timeseries.png'}")
    plt.close()


def plot_power_comparison(host_df, rpict_df):
    """RAPL vs RPICT 전력 비교"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # 상태별 분류
    host_df['state'] = host_df['cpu_pct'].apply(classify_state)

    # 1. Box plot 비교
    ax1 = axes[0]

    # RAPL 데이터
    rapl_idle = host_df.loc[host_df['state'] == 'Idle', 'rapl_package_w']
    rapl_stress = host_df.loc[host_df['state'] == 'Stress', 'rapl_package_w']

    # RPICT 데이터
    rpict_idle = rpict_df[rpict_df['power_w'] < 50]['power_w']
    rpict_stress = rpict_df[rpict_df['power_w'] >= 200]['power_w']

    data = [rapl_idle, rapl_stress, rpict_idle, rpict_stress]
    positions = [1, 2, 4, 5]
    colors = ['lightgreen', 'green', 'moccasin', 'orange']
    labels = ['RAPL\nIdle', 'RAPL\nStress', 'RPICT\nIdle', 'RPICT\nStress']

    bp = ax1.boxplot(data, positions=positions, widths=0.6, patch_artist=True)
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)

    ax1.set_xticks(positions)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel('Power (W)', fontsize=12)
    ax1.set_title('Power Distribution by State', fontsize=12, fontweight='bold')
    ax1.grid(True, axis='y', alpha=0.3)

    # 평균값 텍스트
    for i, d in enumerate(data):
        ax1.text(positions[i], d.max() + 5, f'{d.mean():.1f}W',
                ha='center', fontsize=10, fontweight='bold')

    # 2. 갭 분석
    ax2 = axes[1]

    # 상태별 평균
    states = ['Idle', 'CPU Stress']
    rapl_means = [rapl_idle.mean(), rapl_stress.mean()]
    rpict_means = [rpict_idle.mean(), rpict_stress.mean()]
    gap = [rpict_means[0] - rapl_means[0], rpict_means[1] - rapl_means[1]]

    x = np.arange(len(states))
    width = 0.25

    bars1 = ax2.bar(x - width, rapl_means, width, label='RAPL (CPU Package)', color='green')
    bars2 = ax2.bar(x, rpict_means, width, label='RPICT (Wall Power)', color='orange')
    bars3 = ax2.bar(x + width, gap, width, label='Gap (Other Components)', color='gray')

    ax2.set_ylabel('Power (W)', fontsize=12)
    ax2.set_title('Power Breakdown: RAPL vs Wall Power', fontsize=12, fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(states)
    ax2.legend()
    ax2.grid(True, axis='y', alpha=0.3)

    # 값 표시
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            ax2.annotate(f'{height:.1f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points",
                        ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'T01_power_comparison.png', dpi=150, bbox_inches='tight')
    plt.savefig(OUTPUT_DIR / 'T01_power_comparison.pdf', bbox_inches='tight')
    print(f"Saved: {OUTPUT_DIR / 'T01_power_comparison.png'}")
    plt.close()


def plot_efficiency_analysis(host_df, rpict_df):
    """PSU 효율 및 상관관계 분석"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # 1. RAPL vs RPICT 상관관계 (시간 매칭)
    ax1 = axes[0]

    # RPICT 타임스탬프 기준으로 Host 데이터 매칭 (가장 가까운 시간)
    matched_data = []
    for _, rpict_row in rpict_df.iterrows():
        rpict_time = rpict_row['elapsed_sec']
        # 가장 가까운 host 데이터 찾기
        time_diff = abs(host_df['elapsed_sec'] - rpict_time)
        closest_idx = time_diff.idxmin()
        if time_diff[closest_idx] < 2.0:  # 2초 이내만 매칭
            matched_data.append({
                'rpict_power': rpict_row['power_w'],
                'rapl_power': host_df.loc[closest_idx, 'rapl_package_w'],
                'elapsed_sec': rpict_time
            })

    matched_df = pd.DataFrame(matched_data)

    scatter = ax1.scatter(matched_df['rapl_power'], matched_df['rpict_power'],
                         c=matched_df['elapsed_sec'], cmap='viridis',
                         alpha=0.7, s=50, edgecolors='black', linewidth=0.5)

    # 회귀선
    z = np.polyfit(matched_df['rapl_power'], matched_df['rpict_power'], 1)
    p = np.poly1d(z)
    x_line = np.linspace(matched_df['rapl_power'].min(), matched_df['rapl_power'].max(), 100)
    ax1.plot(x_line, p(x_line), 'r--', linewidth=2,
             label=f'Linear fit: RPICT = {z[0]:.2f}×RAPL + {z[1]:.1f}')

    ax1.set_xlabel('RAPL Package Power (W)', fontsize=12)
    ax1.set_ylabel('RPICT Wall Power (W)', fontsize=12)
    ax1.set_title('RAPL vs RPICT (Wall Power) Correlation', fontsize=12, fontweight='bold')
    ax1.legend(loc='lower right')
    ax1.grid(True, alpha=0.3)
    plt.colorbar(scatter, ax=ax1, label='Time (sec)')

    # 상관계수
    corr = np.corrcoef(matched_df['rapl_power'], matched_df['rpict_power'])[0, 1]
    ax1.text(0.05, 0.95, f'r = {corr:.3f}\nn = {len(matched_df)}',
             transform=ax1.transAxes, fontsize=12, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    # 2. Power Delta 분석 (Stress - Idle)
    ax2 = axes[1]

    # 상태별 데이터
    host_df['state'] = host_df['cpu_pct'].apply(classify_state)
    rapl_idle = host_df.loc[host_df['state'] == 'Idle', 'rapl_package_w'].mean()
    rapl_stress = host_df.loc[host_df['state'] == 'Stress', 'rapl_package_w'].mean()

    rpict_idle = rpict_df[rpict_df['power_w'] < 50]['power_w'].mean()
    rpict_stress = rpict_df[rpict_df['power_w'] >= 200]['power_w'].mean()

    rapl_delta = rapl_stress - rapl_idle
    rpict_delta = rpict_stress - rpict_idle
    efficiency = rapl_delta / rpict_delta * 100

    # Stacked bar로 표현
    categories = ['Wall Power\n(RPICT)', 'CPU Power\n(RAPL)']
    deltas = [rpict_delta, rapl_delta]
    others = [rpict_delta - rapl_delta, 0]

    ax2.bar(categories, [rapl_delta, rapl_delta], label='CPU (RAPL)', color='green')
    ax2.bar(categories, others, bottom=[rapl_delta, rapl_delta],
            label='Other (PSU loss, VRM, etc.)', color='gray')

    ax2.set_ylabel('Power Increase (W)', fontsize=12)
    ax2.set_title('Power Increase: Idle → Stress', fontsize=12, fontweight='bold')
    ax2.legend()
    ax2.grid(True, axis='y', alpha=0.3)

    # 값 표시
    ax2.text(0, rpict_delta/2, f'{rpict_delta:.1f}W\n(Wall)',
             ha='center', va='center', fontsize=11, fontweight='bold')
    ax2.text(1, rapl_delta/2, f'{rapl_delta:.1f}W\n(CPU)',
             ha='center', va='center', fontsize=11, fontweight='bold')

    # 효율 표시
    ax2.text(0.5, -0.15, f'Efficiency: {efficiency:.1f}%\n(RAPL Δ / RPICT Δ)',
             transform=ax2.transAxes, ha='center', fontsize=11,
             bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.5))

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'T01_efficiency_analysis.png', dpi=150, bbox_inches='tight')
    plt.savefig(OUTPUT_DIR / 'T01_efficiency_analysis.pdf', bbox_inches='tight')
    print(f"Saved: {OUTPUT_DIR / 'T01_efficiency_analysis.png'}")
    plt.close()


def generate_summary_table(host_df, rpict_df):
    """요약 통계 테이블 생성"""
    host_df['state'] = host_df['cpu_pct'].apply(classify_state)

    # 상태별 통계
    stats = []

    # Idle
    idle_host = host_df[host_df['state'] == 'Idle']
    idle_rpict = rpict_df[rpict_df['power_w'] < 50]
    stats.append({
        'State': 'Idle',
        'RAPL Package (W)': f"{idle_host['rapl_package_w'].mean():.2f} ± {idle_host['rapl_package_w'].std():.2f}",
        'RAPL Core (W)': f"{idle_host['rapl_core_w'].mean():.2f} ± {idle_host['rapl_core_w'].std():.2f}",
        'GPU (W)': f"{idle_host['gpu_power_w'].mean():.2f} ± {idle_host['gpu_power_w'].std():.2f}",
        'RPICT Wall (W)': f"{idle_rpict['power_w'].mean():.2f} ± {idle_rpict['power_w'].std():.2f}",
        'CPU Usage (%)': f"{idle_host['cpu_pct'].mean():.1f}",
        'Samples': f"{len(idle_host)} / {len(idle_rpict)}"
    })

    # Stress
    stress_host = host_df[host_df['state'] == 'Stress']
    stress_rpict = rpict_df[rpict_df['power_w'] >= 200]
    stats.append({
        'State': 'CPU 100%',
        'RAPL Package (W)': f"{stress_host['rapl_package_w'].mean():.2f} ± {stress_host['rapl_package_w'].std():.2f}",
        'RAPL Core (W)': f"{stress_host['rapl_core_w'].mean():.2f} ± {stress_host['rapl_core_w'].std():.2f}",
        'GPU (W)': f"{stress_host['gpu_power_w'].mean():.2f} ± {stress_host['gpu_power_w'].std():.2f}",
        'RPICT Wall (W)': f"{stress_rpict['power_w'].mean():.2f} ± {stress_rpict['power_w'].std():.2f}",
        'CPU Usage (%)': f"{stress_host['cpu_pct'].mean():.1f}",
        'Samples': f"{len(stress_host)} / {len(stress_rpict)}"
    })

    # Delta
    rapl_delta = stress_host['rapl_package_w'].mean() - idle_host['rapl_package_w'].mean()
    rpict_delta = stress_rpict['power_w'].mean() - idle_rpict['power_w'].mean()
    stats.append({
        'State': 'Δ (Stress - Idle)',
        'RAPL Package (W)': f"+{rapl_delta:.2f}",
        'RAPL Core (W)': f"+{stress_host['rapl_core_w'].mean() - idle_host['rapl_core_w'].mean():.2f}",
        'GPU (W)': f"+{stress_host['gpu_power_w'].mean() - idle_host['gpu_power_w'].mean():.2f}",
        'RPICT Wall (W)': f"+{rpict_delta:.2f}",
        'CPU Usage (%)': '-',
        'Samples': '-'
    })

    # 효율
    efficiency = rapl_delta / rpict_delta * 100
    stats.append({
        'State': 'Efficiency',
        'RAPL Package (W)': f"{efficiency:.1f}%",
        'RAPL Core (W)': '-',
        'GPU (W)': '-',
        'RPICT Wall (W)': '(baseline)',
        'CPU Usage (%)': '-',
        'Samples': '-'
    })

    df_stats = pd.DataFrame(stats)

    # Markdown 테이블 저장
    md_table = df_stats.to_markdown(index=False)
    with open(OUTPUT_DIR / 'T01_summary_table.md', 'w') as f:
        f.write("# T-01 Experiment Summary\n\n")
        f.write("**Experiment**: CPU Stress Test (stress-ng --cpu 0 --timeout 30s × 3)\n\n")
        f.write("**Date**: 2026-02-02\n\n")
        f.write("## Results\n\n")
        f.write(md_table)
        f.write("\n\n## Key Findings\n\n")
        f.write(f"1. **RAPL-RPICT Correlation**: RAPL 전력과 실측 전력(RPICT) 간 강한 선형 상관관계 (효율 분석 그래프 참조)\n")
        f.write(f"2. **Power Efficiency**: RAPL 증가분 / RPICT 증가분 = {efficiency:.1f}%\n")
        f.write(f"   - RAPL은 CPU 패키지 전력만 측정, RPICT는 전체 시스템 전력 측정\n")
        f.write(f"3. **Gap Analysis**: {rpict_delta - rapl_delta:.1f}W의 차이 = PSU 손실 + VRM + 팬 + 마더보드 등\n")
        f.write(f"4. **GPU**: 이 테스트에서는 Idle 상태 유지 (~{idle_host['gpu_power_w'].mean():.1f}W)\n")

    print(f"Saved: {OUTPUT_DIR / 'T01_summary_table.md'}")

    return df_stats


def main():
    print("=" * 60)
    print("T-01 Stress Test Visualization")
    print("=" * 60)

    # 데이터 로드
    print("\n[1/5] Loading data...")
    host_df = load_host_data()
    rpict_df = load_rpict_data()
    print(f"  Host: {len(host_df)} records")
    print(f"  RPICT: {len(rpict_df)} records")

    # 시계열 그래프
    print("\n[2/5] Generating timeseries plot...")
    plot_timeseries(host_df, rpict_df)

    # 전력 비교
    print("\n[3/5] Generating power comparison plot...")
    plot_power_comparison(host_df, rpict_df)

    # 효율 분석
    print("\n[4/5] Generating efficiency analysis...")
    plot_efficiency_analysis(host_df, rpict_df)

    # 요약 테이블
    print("\n[5/5] Generating summary table...")
    stats = generate_summary_table(host_df, rpict_df)
    print("\n" + stats.to_string(index=False))

    print("\n" + "=" * 60)
    print(f"All outputs saved to: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == '__main__':
    main()
