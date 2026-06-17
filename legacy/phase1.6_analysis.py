#!/usr/bin/env python3
"""
Phase 1.6 4-Workload Analysis
Academic-style figures and tables for professor report
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data/raw/alienware/phase1.6_test2"
RPICT_FILE = BASE_DIR / "data/raw/rpict/rpict_phase1.5-test4.csv"
OUTPUT_DIR = BASE_DIR / "reports/phase1.6"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Academic style
plt.rcParams.update({
    'font.family': 'serif',
    'font.serif': ['Times New Roman', 'DejaVu Serif'],
    'font.size': 10,
    'axes.labelsize': 11,
    'axes.titlesize': 12,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'legend.fontsize': 9,
    'figure.titlesize': 13,
    'axes.linewidth': 0.8,
    'grid.linewidth': 0.4,
    'lines.linewidth': 1.5,
    'axes.spines.top': False,
    'axes.spines.right': False,
    'figure.dpi': 150,
})

# Color palette (colorblind-friendly)
COLORS = {
    'cpu': '#E07A5F',      # Terracotta
    'gpu': '#3D405B',      # Dark blue-gray
    'other': '#81B29A',    # Sage green
    'A1': '#F4A261',       # Sandy orange
    'A2': '#E76F51',       # Burnt sienna
    'B1': '#2A9D8F',       # Teal
    'B2': '#264653',       # Dark teal
    'idle': '#E9C46A',     # Maize
}

def load_host_data(phase_name):
    """Load host CSV for a phase"""
    file_path = DATA_DIR / f"{phase_name}_host.csv"
    if file_path.exists():
        df = pd.read_csv(file_path, parse_dates=['timestamp'])
        # Skip first 5 rows (warmup)
        return df.iloc[5:]
    return None

def load_rpict():
    """Load RPICT wall power data"""
    if RPICT_FILE.exists():
        return pd.read_csv(RPICT_FILE, parse_dates=['timestamp'])
    return None

def calculate_averages():
    """Calculate average power for each phase"""
    phases = {
        'Idle': 'baseline',
        'A1 (YOLO Nano)': 'A1_yolo_nano',
        'A2 (YOLO Medium)': 'A2_yolo_medium',
        'B1 (Node.js Light)': 'B1_nodejs_light',
        'B2 (Node.js Heavy)': 'B2_nodejs_heavy',
    }

    results = {}
    for label, filename in phases.items():
        df = load_host_data(filename)
        if df is not None:
            results[label] = {
                'cpu_rapl': df['rapl_package_w'].mean(),
                'cpu_rapl_std': df['rapl_package_w'].std(),
                'gpu': df['gpu_power_w'].mean(),
                'gpu_std': df['gpu_power_w'].std(),
                'cpu_pct': df['cpu_pct'].mean(),
            }
    return results

def calculate_wall_power_phases(rpict_df):
    """Calculate wall power for each phase from RPICT"""
    rpict_df = rpict_df.copy()
    rpict_df['elapsed'] = (rpict_df['timestamp'] - rpict_df['timestamp'].iloc[0]).dt.total_seconds()

    # Phase time ranges (from observation)
    phases = {
        'Idle': (0, 50),
        'A1 (YOLO Nano)': (55, 115),
        'A2 (YOLO Medium)': (130, 190),
        'B1 (Node.js Light)': (210, 270),
        'B2 (Node.js Heavy)': (290, 350),
    }

    results = {}
    for label, (start, end) in phases.items():
        phase_data = rpict_df[(rpict_df['elapsed'] >= start) & (rpict_df['elapsed'] <= end)]
        if len(phase_data) > 0:
            results[label] = {
                'mean': phase_data['power1_w'].mean(),
                'std': phase_data['power1_w'].std(),
                'min': phase_data['power1_w'].min(),
                'max': phase_data['power1_w'].max(),
            }
    return results

def create_academic_breakdown_figure(host_avgs, wall_powers, output_path):
    """Create academic-style stacked bar chart"""

    fig, ax = plt.subplots(figsize=(10, 6))

    phases = ['Idle', 'A1 (YOLO Nano)', 'A2 (YOLO Medium)', 'B1 (Node.js Light)', 'B2 (Node.js Heavy)']
    x = np.arange(len(phases))
    width = 0.6

    # Data
    cpu_vals = [host_avgs[p]['cpu_rapl'] for p in phases]
    gpu_vals = [host_avgs[p]['gpu'] for p in phases]
    wall_vals = [wall_powers[p]['mean'] for p in phases]
    other_vals = [wall_vals[i] - cpu_vals[i] - gpu_vals[i] for i in range(len(phases))]

    # Stacked bars
    bars_cpu = ax.bar(x, cpu_vals, width, label='CPU (RAPL)', color=COLORS['cpu'], edgecolor='white', linewidth=0.5)
    bars_gpu = ax.bar(x, gpu_vals, width, bottom=cpu_vals, label='GPU', color=COLORS['gpu'], edgecolor='white', linewidth=0.5)
    bars_other = ax.bar(x, other_vals, width, bottom=np.array(cpu_vals)+np.array(gpu_vals),
                        label='Other (PSU, MB, etc.)', color=COLORS['other'], edgecolor='white', linewidth=0.5)

    # Total labels
    for i, total in enumerate(wall_vals):
        ax.text(i, total + 3, f'{total:.0f}W', ha='center', va='bottom', fontsize=10, fontweight='bold')

    # Error bars for wall power
    wall_stds = [wall_powers[p]['std'] for p in phases]
    ax.errorbar(x, wall_vals, yerr=wall_stds, fmt='none', ecolor='black', capsize=3, capthick=1, linewidth=1)

    ax.set_ylabel('Power (W)')
    ax.set_xlabel('Workload')
    ax.set_title('Power Breakdown by Component', fontweight='bold', pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(['Idle', 'A1\n(YOLO Nano)', 'A2\n(YOLO Med.)', 'B1\n(Node Light)', 'B2\n(Node Heavy)'])
    ax.legend(loc='upper left', framealpha=0.9)
    ax.set_ylim(0, 180)
    ax.grid(True, alpha=0.3, linestyle='--', axis='y')

    # Add annotation for key insight
    ax.annotate('', xy=(2, wall_vals[2]), xytext=(4, wall_vals[4]),
                arrowprops=dict(arrowstyle='<->', color='#E63946', lw=2))
    ax.text(3, (wall_vals[2] + wall_vals[4])/2 + 5,
            f'GPU: {gpu_vals[2]:.0f}W vs {gpu_vals[4]:.0f}W',
            ha='center', fontsize=9, color='#E63946', fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.savefig(str(output_path).replace('.png', '.pdf'), bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()

def create_comparison_figure(host_avgs, wall_powers, output_path):
    """Create AI vs Non-AI comparison figure"""

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # (a) Wall Power Comparison
    ax1 = axes[0]
    categories = ['Light\nWorkload', 'Heavy\nWorkload']
    ai_values = [wall_powers['A1 (YOLO Nano)']['mean'], wall_powers['A2 (YOLO Medium)']['mean']]
    nonai_values = [wall_powers['B1 (Node.js Light)']['mean'], wall_powers['B2 (Node.js Heavy)']['mean']]

    x = np.arange(len(categories))
    width = 0.35

    bars1 = ax1.bar(x - width/2, ai_values, width, label='AI (YOLO)', color=COLORS['A2'], edgecolor='white')
    bars2 = ax1.bar(x + width/2, nonai_values, width, label='Non-AI (Node.js)', color=COLORS['B2'], edgecolor='white')

    # Value labels
    for bars, values in [(bars1, ai_values), (bars2, nonai_values)]:
        for bar, val in zip(bars, values):
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2,
                    f'{val:.0f}W', ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax1.set_ylabel('Wall Power (W)')
    ax1.set_title('(a) Total Power Consumption', fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(categories)
    ax1.legend(loc='upper left')
    ax1.set_ylim(0, 180)
    ax1.grid(True, alpha=0.3, linestyle='--', axis='y')

    # Annotations
    ax1.annotate(f'+{ai_values[1] - nonai_values[1]:.0f}W\n({(ai_values[1]/nonai_values[1]-1)*100:.0f}%)',
                xy=(1 - width/2, ai_values[1]), xytext=(1.3, ai_values[1] + 10),
                fontsize=9, fontweight='bold', color=COLORS['A2'],
                arrowprops=dict(arrowstyle='->', color=COLORS['A2'], lw=1.5))

    # (b) Component Distribution
    ax2 = axes[1]

    phases = ['A2 (YOLO Medium)', 'B2 (Node.js Heavy)']
    labels = ['A2 (YOLO Med.)', 'B2 (Node Heavy)']

    cpu_vals = [host_avgs[p]['cpu_rapl'] for p in phases]
    gpu_vals = [host_avgs[p]['gpu'] for p in phases]
    wall_vals = [wall_powers[p]['mean'] for p in phases]
    other_vals = [wall_vals[i] - cpu_vals[i] - gpu_vals[i] for i in range(len(phases))]

    x = np.arange(len(phases))
    width = 0.5

    ax2.bar(x, cpu_vals, width, label='CPU', color=COLORS['cpu'], edgecolor='white')
    ax2.bar(x, gpu_vals, width, bottom=cpu_vals, label='GPU', color=COLORS['gpu'], edgecolor='white')
    ax2.bar(x, other_vals, width, bottom=np.array(cpu_vals)+np.array(gpu_vals),
            label='Other', color=COLORS['other'], edgecolor='white')

    # Add value annotations inside bars
    for i in range(len(phases)):
        # CPU
        ax2.text(i, cpu_vals[i]/2, f'{cpu_vals[i]:.0f}W', ha='center', va='center',
                fontsize=9, color='white', fontweight='bold')
        # GPU
        ax2.text(i, cpu_vals[i] + gpu_vals[i]/2, f'{gpu_vals[i]:.0f}W', ha='center', va='center',
                fontsize=9, color='white', fontweight='bold')
        # Other
        ax2.text(i, cpu_vals[i] + gpu_vals[i] + other_vals[i]/2, f'{other_vals[i]:.0f}W',
                ha='center', va='center', fontsize=9, color='black', fontweight='bold')

    ax2.set_ylabel('Power (W)')
    ax2.set_title('(b) Power Distribution (Heavy Workloads)', fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.legend(loc='upper right')
    ax2.set_ylim(0, 180)
    ax2.grid(True, alpha=0.3, linestyle='--', axis='y')

    # Key insight box
    textstr = 'Key Insight:\nSame total power (~145W vs ~117W)\nDifferent distribution:\n• AI: GPU-intensive (60W)\n• Non-AI: CPU-intensive (57W)'
    props = dict(boxstyle='round,pad=0.5', facecolor='#FFF9E6', edgecolor='#E9C46A', alpha=0.9)
    ax2.text(0.98, 0.02, textstr, transform=ax2.transAxes, fontsize=8,
            verticalalignment='bottom', horizontalalignment='right', bbox=props)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.savefig(str(output_path).replace('.png', '.pdf'), bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()

def create_timeline_figure(rpict_df, output_path):
    """Create wall power timeline"""

    fig, ax = plt.subplots(figsize=(12, 5))

    rpict_df = rpict_df.copy()
    rpict_df['elapsed'] = (rpict_df['timestamp'] - rpict_df['timestamp'].iloc[0]).dt.total_seconds()

    ax.plot(rpict_df['elapsed'], rpict_df['power1_w'], color='#1D3557', linewidth=1.2)
    ax.fill_between(rpict_df['elapsed'], rpict_df['power1_w'], alpha=0.2, color='#457B9D')

    # Phase regions
    phases = [
        (0, 50, 'Idle', COLORS['idle'], 0.15),
        (55, 115, 'A1: YOLO Nano', COLORS['A1'], 0.2),
        (130, 190, 'A2: YOLO Medium', COLORS['A2'], 0.2),
        (210, 270, 'B1: Node.js Light', COLORS['B1'], 0.2),
        (290, 350, 'B2: Node.js Heavy', COLORS['B2'], 0.2),
    ]

    for start, end, label, color, alpha in phases:
        ax.axvspan(start, end, alpha=alpha, color=color)
        mid = (start + end) / 2
        ax.text(mid, 185, label, ha='center', va='bottom', fontsize=9, fontweight='bold', rotation=0)

    ax.set_xlabel('Time (seconds)')
    ax.set_ylabel('Wall Power (W)')
    ax.set_title('Real-time Power Measurement (CT Sensor)', fontweight='bold')
    ax.set_ylim(0, 200)
    ax.set_xlim(0, rpict_df['elapsed'].max())
    ax.grid(True, alpha=0.3, linestyle='--')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.savefig(str(output_path).replace('.png', '.pdf'), bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()

def create_summary_table(host_avgs, wall_powers):
    """Create summary table"""

    data = []
    for phase in ['Idle', 'A1 (YOLO Nano)', 'A2 (YOLO Medium)', 'B1 (Node.js Light)', 'B2 (Node.js Heavy)']:
        cpu = host_avgs[phase]['cpu_rapl']
        gpu = host_avgs[phase]['gpu']
        wall = wall_powers[phase]['mean']
        other = wall - cpu - gpu
        delta = wall - wall_powers['Idle']['mean']

        data.append({
            'Phase': phase,
            'Wall (W)': round(wall, 1),
            'CPU (W)': round(cpu, 1),
            'GPU (W)': round(gpu, 1),
            'Other (W)': round(other, 1),
            'Delta (W)': round(delta, 1),
            'GPU %': round(gpu/wall*100, 1),
            'CPU %': round(cpu/wall*100, 1),
        })

    return pd.DataFrame(data)

def main():
    print("=" * 60)
    print("Phase 1.6 Analysis: 4 Workloads Comparison")
    print("=" * 60)

    # Load data
    print("\n[1] Loading data...")
    host_avgs = calculate_averages()
    rpict_df = load_rpict()
    wall_powers = calculate_wall_power_phases(rpict_df)

    # Create summary table
    print("\n[2] Summary Table...")
    summary_df = create_summary_table(host_avgs, wall_powers)
    print(summary_df.to_string(index=False))
    summary_df.to_csv(OUTPUT_DIR / "phase1.6_summary.csv", index=False)

    # Create figures
    print("\n[3] Creating figures...")
    create_academic_breakdown_figure(host_avgs, wall_powers, str(OUTPUT_DIR / "power_breakdown.png"))
    create_comparison_figure(host_avgs, wall_powers, str(OUTPUT_DIR / "ai_vs_nonai_comparison.png"))
    create_timeline_figure(rpict_df, str(OUTPUT_DIR / "timeline.png"))

    # Key insights
    print("\n" + "=" * 60)
    print("KEY INSIGHTS")
    print("=" * 60)

    a2_wall = wall_powers['A2 (YOLO Medium)']['mean']
    b2_wall = wall_powers['B2 (Node.js Heavy)']['mean']
    a2_gpu = host_avgs['A2 (YOLO Medium)']['gpu']
    b2_gpu = host_avgs['B2 (Node.js Heavy)']['gpu']
    a2_cpu = host_avgs['A2 (YOLO Medium)']['cpu_rapl']
    b2_cpu = host_avgs['B2 (Node.js Heavy)']['cpu_rapl']

    print(f"""
1. AI (YOLO Medium) vs Non-AI (Node.js Heavy) 비교:
   - Wall Power: {a2_wall:.0f}W vs {b2_wall:.0f}W (AI가 {a2_wall - b2_wall:.0f}W 더 높음)
   - GPU Power: {a2_gpu:.0f}W vs {b2_gpu:.0f}W (AI가 {a2_gpu - b2_gpu:.0f}W 더 높음)
   - CPU Power: {a2_cpu:.0f}W vs {b2_cpu:.0f}W (Non-AI가 {b2_cpu - a2_cpu:.0f}W 더 높음)

2. 같은 리소스 할당(2코어, 4GB)에서:
   - AI 워크로드: GPU에서 전력 소비 집중 ({a2_gpu/a2_wall*100:.0f}% of total)
   - Non-AI 워크로드: CPU에서 전력 소비 집중 ({b2_cpu/b2_wall*100:.0f}% of total)

3. 시사점:
   - 리소스 기반 과금은 전력 소비를 반영하지 못함
   - GPU 사용 여부가 전력 소비의 핵심 변수
   - 에너지 기반 과금 시 컴포넌트별 차등 적용 필요
""")

    print(f"\n✓ All outputs saved to: {OUTPUT_DIR}")

if __name__ == '__main__':
    main()
