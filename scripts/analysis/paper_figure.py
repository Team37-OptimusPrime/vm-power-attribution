#!/usr/bin/env python3
"""
Phase 1.5 논문용 종합 Figure 생성
- 4개 서브플롯으로 핵심 결과를 한 눈에 보여줌
- IEEE/ACM 논문 스타일 적용
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path
from datetime import datetime

# 논문 스타일 설정
plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 9,
    'axes.labelsize': 10,
    'axes.titlesize': 11,
    'xtick.labelsize': 8,
    'ytick.labelsize': 8,
    'legend.fontsize': 8,
    'figure.titlesize': 12,
    'axes.linewidth': 0.8,
    'grid.linewidth': 0.5,
    'lines.linewidth': 1.5,
    'axes.spines.top': False,
    'axes.spines.right': False,
})

# 색상 팔레트 (colorblind-friendly)
COLORS = {
    'yolo': '#E63946',      # 빨강 (AI workload)
    'nodejs': '#457B9D',    # 파랑 (Non-AI workload)
    'idle': '#A8DADC',      # 연한 파랑 (Idle)
    'cpu': '#2A9D8F',       # 청록 (CPU)
    'gpu': '#E9C46A',       # 노랑 (GPU)
    'other': '#8D99AE',     # 회색 (Other)
    'concurrent': '#9B5DE5', # 보라 (Concurrent)
}

def load_data():
    """데이터 로드"""
    base_path = Path(__file__).parent.parent.parent
    data_path = base_path / "data/raw/phase1.5/20260206_020631_test2"
    rpict_path = base_path / "data/raw/rpict/rpict_phase1.5-test2.csv"

    data = {
        'rpict': pd.read_csv(rpict_path, parse_dates=['timestamp']),
        'yolo_host': pd.read_csv(data_path / "yolo_solo_host.csv", parse_dates=['timestamp']),
        'nodejs_host': pd.read_csv(data_path / "nodejs_solo_host.csv", parse_dates=['timestamp']),
        'yolo_cgroup': pd.read_csv(data_path / "yolo_solo_cgroup.csv", parse_dates=['timestamp']),
        'nodejs_cgroup': pd.read_csv(data_path / "nodejs_solo_cgroup.csv", parse_dates=['timestamp']),
    }
    return data

def create_paper_figure(data, output_path):
    """논문용 종합 Figure 생성"""

    fig = plt.figure(figsize=(10, 9))

    # 그리드 레이아웃: 2x2 (상단 여백 확보)
    gs = fig.add_gridspec(2, 2, hspace=0.4, wspace=0.3,
                          left=0.08, right=0.95, top=0.85, bottom=0.08)

    # ===== (A) Wall Power Timeline =====
    ax1 = fig.add_subplot(gs[0, :])  # 상단 전체 사용

    rpict = data['rpict'].copy()
    rpict['elapsed'] = (rpict['timestamp'] - rpict['timestamp'].iloc[0]).dt.total_seconds()

    ax1.plot(rpict['elapsed'], rpict['power1_w'], color='#1D3557', linewidth=1.2, alpha=0.9)
    ax1.fill_between(rpict['elapsed'], rpict['power1_w'], alpha=0.3, color='#457B9D')

    # Phase 구분선 및 라벨
    phases = [
        (0, 60, 'Idle', COLORS['idle']),
        (60, 120, 'YOLO\n(AI)', COLORS['yolo']),
        (120, 180, 'Idle', COLORS['idle']),
        (180, 240, 'Node.js\n(Non-AI)', COLORS['nodejs']),
        (240, 300, 'Concurrent', COLORS['concurrent']),
    ]

    # RPICT 데이터 기준 시간 계산 (대략적)
    # Idle: ~0-60s, YOLO: ~60-120s, transition, Node.js: ~135-195s, Concurrent: ~220-280s
    phase_times = [
        (0, 60, 'Idle\n(Baseline)', COLORS['idle']),
        (63, 123, 'YOLO Solo\n(AI Workload)', COLORS['yolo']),
        (135, 195, 'Node.js Solo\n(Non-AI)', COLORS['nodejs']),
        (220, 280, 'Concurrent\n(YOLO + Node.js)', COLORS['concurrent']),
    ]

    for start, end, label, color in phase_times:
        ax1.axvspan(start, end, alpha=0.15, color=color)
        mid = (start + end) / 2
        ax1.text(mid, 145, label, ha='center', va='bottom', fontsize=8, fontweight='bold')

    ax1.set_xlabel('Time (seconds)')
    ax1.set_ylabel('Wall Power (W)')
    ax1.set_title('(a) Real-time Wall Power Measurement via CT Sensor', fontweight='bold', loc='left')
    ax1.set_ylim(0, 160)
    ax1.set_xlim(0, rpict['elapsed'].max())
    ax1.grid(True, alpha=0.3, linestyle='--')

    # 평균값 표시
    ax1.axhline(y=37.8, color=COLORS['idle'], linestyle='--', linewidth=1, alpha=0.7)
    ax1.axhline(y=114.5, color=COLORS['yolo'], linestyle='--', linewidth=1, alpha=0.7)
    ax1.axhline(y=42.0, color=COLORS['nodejs'], linestyle='--', linewidth=1, alpha=0.7)

    ax1.text(rpict['elapsed'].max() + 2, 37.8, '37.8W', va='center', fontsize=7, color=COLORS['idle'])
    ax1.text(rpict['elapsed'].max() + 2, 114.5, '114.5W', va='center', fontsize=7, color=COLORS['yolo'])
    ax1.text(rpict['elapsed'].max() + 2, 42.0, '42.0W', va='center', fontsize=7, color=COLORS['nodejs'])

    # ===== (B) Power Breakdown by Component =====
    ax2 = fig.add_subplot(gs[1, 0])

    # 데이터 (측정값 기반)
    phases_data = ['Idle', 'YOLO\n(AI)', 'Node.js\n(Non-AI)']
    cpu_power = [5.5, 31.9, 7.5]
    gpu_power = [8.4, 37.4, 8.4]
    other_power = [23.9, 45.2, 26.1]  # Wall - CPU - GPU

    x = np.arange(len(phases_data))
    width = 0.6

    bars1 = ax2.bar(x, cpu_power, width, label='CPU (RAPL)', color=COLORS['cpu'])
    bars2 = ax2.bar(x, gpu_power, width, bottom=cpu_power, label='GPU', color=COLORS['gpu'])
    bars3 = ax2.bar(x, other_power, width, bottom=np.array(cpu_power)+np.array(gpu_power),
                    label='Other (MB, PSU, etc.)', color=COLORS['other'])

    # Wall power 표시
    wall_powers = [37.8, 114.5, 42.0]
    for i, wp in enumerate(wall_powers):
        ax2.text(i, wp + 3, f'{wp}W', ha='center', va='bottom', fontsize=9, fontweight='bold')

    ax2.set_ylabel('Power (W)')
    ax2.set_title('(b) Power Breakdown by Component', fontweight='bold', loc='left')
    ax2.set_xticks(x)
    ax2.set_xticklabels(phases_data)
    ax2.legend(loc='upper left', framealpha=0.9)
    ax2.set_ylim(0, 135)
    ax2.grid(True, alpha=0.3, linestyle='--', axis='y')

    # ===== (C) Key Finding: Same Resources, Different Power =====
    ax3 = fig.add_subplot(gs[1, 1])

    # 왼쪽: 리소스 할당 (동일)
    # 오른쪽: 전력 소비 (다름)

    categories = ['CPU Cores\nAllocated', 'Memory\nAllocated', 'Wall Power\nConsumed']
    yolo_values = [2, 4, 114.5]
    nodejs_values = [2, 4, 42.0]

    x = np.arange(len(categories))
    width = 0.35

    bars1 = ax3.bar(x - width/2, yolo_values, width, label='YOLO (AI)', color=COLORS['yolo'])
    bars2 = ax3.bar(x + width/2, nodejs_values, width, label='Node.js (Non-AI)', color=COLORS['nodejs'])

    # 값 표시
    for bars, values in [(bars1, yolo_values), (bars2, nodejs_values)]:
        for bar, val in zip(bars, values):
            height = bar.get_height()
            unit = 'W' if val > 10 else ('GB' if val == 4 else '')
            ax3.text(bar.get_x() + bar.get_width()/2, height + 2,
                    f'{val}{unit}', ha='center', va='bottom', fontsize=8, fontweight='bold')

    # 강조: 전력 차이
    ax3.annotate('', xy=(2.175, 114.5), xytext=(2.175, 42),
                arrowprops=dict(arrowstyle='<->', color='#E63946', lw=2))
    ax3.text(2.4, 78, '2.7×\ndifference', ha='left', va='center', fontsize=9,
            fontweight='bold', color='#E63946')

    # "Same" 표시
    ax3.annotate('Same', xy=(0, 2), xytext=(0, -15),
                fontsize=8, ha='center', color='green', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='green', lw=1))
    ax3.annotate('Same', xy=(1, 4), xytext=(1, -15),
                fontsize=8, ha='center', color='green', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='green', lw=1))

    ax3.set_ylabel('Value')
    ax3.set_title('(c) Same Resources ≠ Same Energy', fontweight='bold', loc='left')
    ax3.set_xticks(x)
    ax3.set_xticklabels(categories)
    ax3.legend(loc='upper left')
    ax3.set_ylim(-25, 140)
    ax3.grid(True, alpha=0.3, linestyle='--', axis='y')

    # 핵심 메시지 박스
    textstr = 'Key Finding:\nIdentical resource allocation\n→ 2.7× power difference\n→ 18.3× delta difference'
    props = dict(boxstyle='round,pad=0.5', facecolor='#FFF3CD', edgecolor='#E63946', alpha=0.9)
    ax3.text(0.98, 0.98, textstr, transform=ax3.transAxes, fontsize=8,
            verticalalignment='top', horizontalalignment='right', bbox=props)

    # ===== 전체 제목 =====
    fig.suptitle('Phase 1.5: cgroup-based Power Attribution Analysis\n'
                 'Validating "Resource-based Billing ≠ Energy-based Billing"',
                 fontsize=12, fontweight='bold', y=0.95)

    # 저장
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.savefig(output_path.replace('.png', '.pdf'), bbox_inches='tight', facecolor='white')
    print(f"Saved: {output_path}")
    print(f"Saved: {output_path.replace('.png', '.pdf')}")

    plt.close()

def main():
    print("Loading data...")
    data = load_data()

    output_dir = Path(__file__).parent.parent.parent / "reports/phase1.5/figures"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = str(output_dir / "paper_figure_comprehensive.png")

    print("Creating paper figure...")
    create_paper_figure(data, output_path)

    print("\nFigure generation complete!")
    print(f"\nOutput files:")
    print(f"  - {output_path}")
    print(f"  - {output_path.replace('.png', '.pdf')}")

if __name__ == '__main__':
    main()
