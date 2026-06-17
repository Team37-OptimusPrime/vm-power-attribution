#!/usr/bin/env python3
"""
Phase 1.5 Heavy Node.js 실험 결과 분석
교수님께 보내드릴 그래프 및 테이블 생성
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime

# 경로 설정
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data/raw/alienware/phase1.5_heavy_nodejs"
RPICT_FILE = BASE_DIR / "data/raw/rpict/rpict_phase1.5-test3-heavy-node.csv"
OUTPUT_DIR = BASE_DIR / "reports/phase1.5_heavy"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 논문 스타일 설정
plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 10,
    'axes.labelsize': 11,
    'axes.titlesize': 12,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'legend.fontsize': 9,
    'figure.titlesize': 14,
    'axes.linewidth': 0.8,
    'grid.linewidth': 0.5,
    'lines.linewidth': 1.5,
})

# 색상
COLORS = {
    'idle': '#A8DADC',
    'yolo': '#E63946',
    'nodejs': '#457B9D',
    'concurrent': '#9B5DE5',
    'cpu': '#2A9D8F',
    'gpu': '#E9C46A',
    'other': '#8D99AE',
}

def load_data():
    """모든 데이터 로드"""
    data = {}

    # Host 데이터
    for phase in ['baseline', 'yolo_solo', 'nodejs_solo', 'concurrent']:
        host_file = DATA_DIR / f"{phase}_host.csv"
        cgroup_file = DATA_DIR / f"{phase}_cgroup.csv"

        if host_file.exists():
            data[f'{phase}_host'] = pd.read_csv(host_file, parse_dates=['timestamp'])
        if cgroup_file.exists():
            data[f'{phase}_cgroup'] = pd.read_csv(cgroup_file, parse_dates=['timestamp'])

    # RPICT 데이터
    if RPICT_FILE.exists():
        data['rpict'] = pd.read_csv(RPICT_FILE, parse_dates=['timestamp'])

    return data

def calculate_phase_averages(data):
    """각 Phase의 평균값 계산"""
    results = {}

    for phase in ['baseline', 'yolo_solo', 'nodejs_solo', 'concurrent']:
        host_key = f'{phase}_host'
        cgroup_key = f'{phase}_cgroup'

        if host_key in data:
            host_df = data[host_key]
            # 안정화 후 데이터만 사용 (처음 5초 제외)
            host_df = host_df.iloc[5:]

            results[phase] = {
                'rapl_package_w': host_df['rapl_package_w'].mean(),
                'gpu_power_w': host_df['gpu_power_w'].mean(),
                'cpu_pct': host_df['cpu_pct'].mean(),
            }

        if cgroup_key in data:
            cgroup_df = data[cgroup_key]
            cgroup_df = cgroup_df.iloc[10:]  # 안정화 후

            yolo_data = cgroup_df[cgroup_df['cgroup'] == 'yolo.slice']
            nodejs_data = cgroup_df[cgroup_df['cgroup'] == 'nodejs.slice']

            results[phase]['yolo_cpu_pct'] = yolo_data['cpu_percent'].mean() if len(yolo_data) > 0 else 0
            results[phase]['nodejs_cpu_pct'] = nodejs_data['cpu_percent'].mean() if len(nodejs_data) > 0 else 0

    return results

def calculate_wall_power_phases(rpict_df):
    """RPICT 데이터에서 각 Phase의 Wall Power 계산"""
    rpict_df = rpict_df.copy()
    rpict_df['elapsed'] = (rpict_df['timestamp'] - rpict_df['timestamp'].iloc[0]).dt.total_seconds()

    # Phase 시간 구간 (대략적)
    phases = {
        'baseline': (0, 45),
        'yolo_solo': (50, 110),
        'nodejs_solo': (130, 180),
        'concurrent': (195, 260),
    }

    results = {}
    for phase, (start, end) in phases.items():
        phase_data = rpict_df[(rpict_df['elapsed'] >= start) & (rpict_df['elapsed'] <= end)]
        if len(phase_data) > 0:
            results[phase] = phase_data['power1_w'].mean()

    return results

def create_comparison_figure(data, output_path):
    """이전 vs 현재 비교 그래프"""

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))

    # 이전 데이터 (Phase 1.5 test2)
    old_data = {
        'Idle': {'wall': 37.8, 'cpu': 5.5, 'gpu': 8.4},
        'YOLO': {'wall': 114.5, 'cpu': 31.9, 'gpu': 37.4},
        'Node.js': {'wall': 42.0, 'cpu': 7.5, 'gpu': 8.4},
        'Concurrent': {'wall': 115.7, 'cpu': 31.8, 'gpu': 36.2},
    }

    # 현재 데이터 계산
    avgs = calculate_phase_averages(data)
    wall_powers = calculate_wall_power_phases(data['rpict'])

    new_data = {
        'Idle': {
            'wall': wall_powers.get('baseline', 38),
            'cpu': avgs['baseline']['rapl_package_w'],
            'gpu': avgs['baseline']['gpu_power_w']
        },
        'YOLO': {
            'wall': wall_powers.get('yolo_solo', 118),
            'cpu': avgs['yolo_solo']['rapl_package_w'],
            'gpu': avgs['yolo_solo']['gpu_power_w']
        },
        'Node.js': {
            'wall': wall_powers.get('nodejs_solo', 116),
            'cpu': avgs['nodejs_solo']['rapl_package_w'],
            'gpu': avgs['nodejs_solo']['gpu_power_w']
        },
        'Concurrent': {
            'wall': wall_powers.get('concurrent', 170),
            'cpu': avgs['concurrent']['rapl_package_w'],
            'gpu': avgs['concurrent']['gpu_power_w']
        },
    }

    phases = ['Idle', 'YOLO', 'Node.js', 'Concurrent']
    x = np.arange(len(phases))
    width = 0.35

    # (a) Wall Power 비교
    ax1 = axes[0]
    old_wall = [old_data[p]['wall'] for p in phases]
    new_wall = [new_data[p]['wall'] for p in phases]

    bars1 = ax1.bar(x - width/2, old_wall, width, label='Light Node.js', color='#90BE6D')
    bars2 = ax1.bar(x + width/2, new_wall, width, label='Heavy Node.js', color='#F94144')

    ax1.set_ylabel('Wall Power (W)')
    ax1.set_title('(a) Wall Power Comparison')
    ax1.set_xticks(x)
    ax1.set_xticklabels(phases)
    ax1.legend()
    ax1.grid(True, alpha=0.3, axis='y')

    # Node.js 차이 표시
    ax1.annotate(f'+{new_wall[2] - old_wall[2]:.1f}W\n(+{(new_wall[2]/old_wall[2]-1)*100:.0f}%)',
                xy=(2 + width/2, new_wall[2]), xytext=(2.5, new_wall[2] + 15),
                fontsize=9, color='#F94144', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#F94144'))

    # (b) CPU Power 비교
    ax2 = axes[1]
    old_cpu = [old_data[p]['cpu'] for p in phases]
    new_cpu = [new_data[p]['cpu'] for p in phases]

    bars1 = ax2.bar(x - width/2, old_cpu, width, label='Light Node.js', color='#90BE6D')
    bars2 = ax2.bar(x + width/2, new_cpu, width, label='Heavy Node.js', color='#F94144')

    ax2.set_ylabel('CPU Power - RAPL (W)')
    ax2.set_title('(b) CPU Power Comparison')
    ax2.set_xticks(x)
    ax2.set_xticklabels(phases)
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='y')

    # Node.js 차이 표시
    ax2.annotate(f'+{new_cpu[2] - old_cpu[2]:.1f}W\n(+{(new_cpu[2]/old_cpu[2]-1)*100:.0f}%)',
                xy=(2 + width/2, new_cpu[2]), xytext=(2.5, new_cpu[2] + 8),
                fontsize=9, color='#F94144', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#F94144'))

    # (c) Delta from Idle 비교
    ax3 = axes[2]
    old_delta = [old_data[p]['wall'] - old_data['Idle']['wall'] for p in phases]
    new_delta = [new_data[p]['wall'] - new_data['Idle']['wall'] for p in phases]

    bars1 = ax3.bar(x - width/2, old_delta, width, label='Light Node.js', color='#90BE6D')
    bars2 = ax3.bar(x + width/2, new_delta, width, label='Heavy Node.js', color='#F94144')

    ax3.set_ylabel('Delta from Idle (W)')
    ax3.set_title('(c) Power Increase from Idle')
    ax3.set_xticks(x)
    ax3.set_xticklabels(phases)
    ax3.legend()
    ax3.grid(True, alpha=0.3, axis='y')
    ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

    # Node.js 차이 표시
    ax3.annotate(f'+{new_delta[2] - old_delta[2]:.1f}W',
                xy=(2 + width/2, new_delta[2]), xytext=(2.5, new_delta[2] + 10),
                fontsize=9, color='#F94144', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#F94144'))

    fig.suptitle('Phase 1.5 Heavy Node.js: Light vs Heavy Workload Comparison',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()

    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.savefig(output_path.replace('.png', '.pdf'), bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()

def create_timeline_figure(data, output_path):
    """시간에 따른 전력 변화 그래프"""

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    rpict = data['rpict'].copy()
    rpict['elapsed'] = (rpict['timestamp'] - rpict['timestamp'].iloc[0]).dt.total_seconds()

    # (a) Wall Power Timeline
    ax1 = axes[0]
    ax1.plot(rpict['elapsed'], rpict['power1_w'], color='#1D3557', linewidth=1.5)
    ax1.fill_between(rpict['elapsed'], rpict['power1_w'], alpha=0.3, color='#457B9D')

    # Phase 영역 표시
    phases = [
        (0, 45, 'Idle', COLORS['idle']),
        (50, 110, 'YOLO Solo', COLORS['yolo']),
        (115, 130, 'Cooldown', '#EEEEEE'),
        (130, 180, 'Node.js\n(Heavy)', COLORS['nodejs']),
        (185, 195, 'Cooldown', '#EEEEEE'),
        (195, 260, 'Concurrent', COLORS['concurrent']),
    ]

    for start, end, label, color in phases:
        ax1.axvspan(start, end, alpha=0.2, color=color)
        if 'Cooldown' not in label:
            ax1.text((start + end) / 2, 195, label, ha='center', va='bottom',
                    fontsize=9, fontweight='bold')

    ax1.set_ylabel('Wall Power (W)')
    ax1.set_title('(a) Wall Power Timeline (CT Sensor)', fontweight='bold', loc='left')
    ax1.set_ylim(0, 210)
    ax1.grid(True, alpha=0.3, linestyle='--')

    # 평균값 표시
    ax1.axhline(y=38, color=COLORS['idle'], linestyle='--', linewidth=1)
    ax1.axhline(y=118, color=COLORS['yolo'], linestyle='--', linewidth=1)
    ax1.axhline(y=116, color=COLORS['nodejs'], linestyle='--', linewidth=1)
    ax1.axhline(y=170, color=COLORS['concurrent'], linestyle='--', linewidth=1)

    # (b) CPU Usage by cgroup
    ax2 = axes[1]

    # 모든 cgroup 데이터 합치기
    all_cgroup = []
    for phase, (start_offset, _) in [
        ('baseline', (0, 0)),
        ('yolo_solo', (50, 0)),
        ('nodejs_solo', (130, 0)),
        ('concurrent', (195, 0))
    ]:
        cgroup_key = f'{phase}_cgroup'
        if cgroup_key in data:
            df = data[cgroup_key].copy()
            df['elapsed'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds() + start_offset
            all_cgroup.append(df)

    if all_cgroup:
        cgroup_df = pd.concat(all_cgroup, ignore_index=True)

        yolo_data = cgroup_df[cgroup_df['cgroup'] == 'yolo.slice']
        nodejs_data = cgroup_df[cgroup_df['cgroup'] == 'nodejs.slice']

        ax2.plot(yolo_data['elapsed'], yolo_data['cpu_percent'],
                color=COLORS['yolo'], label='YOLO (yolo.slice)', linewidth=1.5)
        ax2.plot(nodejs_data['elapsed'], nodejs_data['cpu_percent'],
                color=COLORS['nodejs'], label='Node.js (nodejs.slice)', linewidth=1.5)

    ax2.set_xlabel('Time (seconds)')
    ax2.set_ylabel('CPU Usage (%)')
    ax2.set_title('(b) Per-Application CPU Usage (cgroup)', fontweight='bold', loc='left')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3, linestyle='--')
    ax2.set_ylim(0, 400)

    # 200% 라인 (2코어 기준)
    ax2.axhline(y=200, color='gray', linestyle=':', linewidth=1)
    ax2.text(5, 210, '200% = 2 cores', fontsize=8, color='gray')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.savefig(output_path.replace('.png', '.pdf'), bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()

def create_summary_table(data):
    """요약 테이블 생성"""

    avgs = calculate_phase_averages(data)
    wall_powers = calculate_wall_power_phases(data['rpict'])

    # 이전 데이터
    old_results = {
        'Phase': ['Idle', 'YOLO Solo', 'Node.js Solo (Light)', 'Concurrent'],
        'Wall (W)': [37.8, 114.5, 42.0, 115.7],
        'CPU (W)': [5.5, 31.9, 7.5, 31.8],
        'GPU (W)': [8.4, 37.4, 8.4, 36.2],
        'Delta (W)': [0, 76.7, 4.2, 77.9],
        'YOLO CPU%': [0, 95.6, 0, 91.0],
        'Node CPU%': [0, 0, 17.4, 13.7],
    }

    # 현재 데이터
    new_results = {
        'Phase': ['Idle', 'YOLO Solo', 'Node.js Solo (Heavy)', 'Concurrent'],
        'Wall (W)': [
            round(wall_powers.get('baseline', 38), 1),
            round(wall_powers.get('yolo_solo', 118), 1),
            round(wall_powers.get('nodejs_solo', 116), 1),
            round(wall_powers.get('concurrent', 170), 1),
        ],
        'CPU (W)': [
            round(avgs['baseline']['rapl_package_w'], 1),
            round(avgs['yolo_solo']['rapl_package_w'], 1),
            round(avgs['nodejs_solo']['rapl_package_w'], 1),
            round(avgs['concurrent']['rapl_package_w'], 1),
        ],
        'GPU (W)': [
            round(avgs['baseline']['gpu_power_w'], 1),
            round(avgs['yolo_solo']['gpu_power_w'], 1),
            round(avgs['nodejs_solo']['gpu_power_w'], 1),
            round(avgs['concurrent']['gpu_power_w'], 1),
        ],
        'YOLO CPU%': [
            0,
            round(avgs['yolo_solo']['yolo_cpu_pct'], 1),
            0,
            round(avgs['concurrent']['yolo_cpu_pct'], 1),
        ],
        'Node CPU%': [
            0,
            0,
            round(avgs['nodejs_solo']['nodejs_cpu_pct'], 1),
            round(avgs['concurrent']['nodejs_cpu_pct'], 1),
        ],
    }

    # Delta 계산
    idle_wall = new_results['Wall (W)'][0]
    new_results['Delta (W)'] = [round(w - idle_wall, 1) for w in new_results['Wall (W)']]

    old_df = pd.DataFrame(old_results)
    new_df = pd.DataFrame(new_results)

    return old_df, new_df

def main():
    print("=" * 60)
    print("Phase 1.5 Heavy Node.js 분석")
    print("=" * 60)

    # 데이터 로드
    print("\n[1] 데이터 로드...")
    data = load_data()
    print(f"  로드된 데이터: {list(data.keys())}")

    # 요약 테이블 생성
    print("\n[2] 요약 테이블 생성...")
    old_df, new_df = create_summary_table(data)

    print("\n=== 이전 결과 (Light Node.js) ===")
    print(old_df.to_string(index=False))

    print("\n=== 현재 결과 (Heavy Node.js) ===")
    print(new_df.to_string(index=False))

    # CSV 저장
    old_df.to_csv(OUTPUT_DIR / "phase1.5_light_summary.csv", index=False)
    new_df.to_csv(OUTPUT_DIR / "phase1.5_heavy_summary.csv", index=False)
    print(f"\n✓ 테이블 저장: {OUTPUT_DIR}")

    # 그래프 생성
    print("\n[3] 그래프 생성...")
    create_comparison_figure(data, str(OUTPUT_DIR / "comparison_light_vs_heavy.png"))
    create_timeline_figure(data, str(OUTPUT_DIR / "timeline_heavy.png"))

    # 핵심 수치 출력
    print("\n" + "=" * 60)
    print("핵심 결과 (교수님 보고용)")
    print("=" * 60)

    light_nodejs_wall = 42.0
    heavy_nodejs_wall = new_df['Wall (W)'][2]
    light_delta = 4.2
    heavy_delta = new_df['Delta (W)'][2]

    print(f"""
Node.js 워크로드 부하 강화 결과:

| 항목 | Light (이전) | Heavy (현재) | 변화 |
|------|-------------|-------------|------|
| Wall Power | {light_nodejs_wall}W | {heavy_nodejs_wall}W | +{heavy_nodejs_wall - light_nodejs_wall:.1f}W (+{(heavy_nodejs_wall/light_nodejs_wall - 1)*100:.0f}%) |
| Delta from Idle | +{light_delta}W | +{heavy_delta}W | +{heavy_delta - light_delta:.1f}W |
| Node CPU% | 17.4% | {new_df['Node CPU%'][2]}% | +{new_df['Node CPU%'][2] - 17.4:.0f}% |

핵심 인사이트:
1. 동일한 리소스 할당(2코어, 4GB)에서도 워크로드 특성에 따라 전력 소비 대폭 증가
2. YOLO(GPU) vs Node.js(CPU-only) 비교가 더 명확해짐
3. Concurrent에서 두 워크로드의 독립적 기여 확인 가능
""")

    print(f"\n✓ 모든 결과가 {OUTPUT_DIR}에 저장되었습니다.")

if __name__ == '__main__':
    main()
