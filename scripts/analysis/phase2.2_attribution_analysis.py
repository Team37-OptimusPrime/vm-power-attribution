#!/usr/bin/env python3
"""
Phase 2.2: 5-Component Attribution Concurrent Verification Analysis

Phase 2.0/2.1에서 도출한 컴포넌트 파라미터로 동시실행 에너지 분배 검증:
  Wall = CPU + GPU_sensor + GPU_hidden + Memory + Storage + Others_residual

GPU 분리: GPU0=YOLO(sensor+hidden), GPU1=Node.js(idle sensor+hidden)
CPU freq: fixed (3.6GHz) vs free (turbo enabled) 비교

Usage:
    python3 phase2.2_attribution_analysis.py
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = Path("/Users/rainyforest/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution")
FIXED_DIR = BASE_DIR / "data/raw/alienware/phase2.2_fixed"
FREE_DIR  = BASE_DIR / "data/raw/alienware/phase2.2_free"
RPICT_FILE = BASE_DIR / "data/raw/rpict/phase2.2.csv"
OUTPUT_DIR = BASE_DIR / "reports/phase2.2"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# Component Parameters (from Phase 2.0 / 2.1)
# ──────────────────────────────────────────────
GPU_HIDDEN_PER_CARD_W = 7.6    # Phase 2.0: GPU hidden power per card
MEM_PER_DIMM_W = 0.25          # Phase 2.0: 0.25W per DIMM
NUM_DIMMS = 2                   # 2x16GB
TOTAL_MEM_MB = 32 * 1024       # 32GB
STORAGE_COEFF = 0.0025          # Phase 2.1 revised: W/(MB/s), GPU delta 제거, avg(write 0.00233 + read 0.00268)

# ──────────────────────────────────────────────
# Trim settings (skip warmup/cooldown)
# ──────────────────────────────────────────────
TRIM_START = 10   # skip first 10 samples (~10s warmup)
TRIM_END = -5     # skip last 5 samples

PHASES_HOST = {
    'Idle':  'baseline',
    'A1':    'A1_yolo_nano',
    'A2':    'A2_yolo_medium',
    'B1':    'B1_nodejs_light',
    'B2':    'B2_nodejs_heavy',
    'A1+B1': 'A1B1_concurrent',
    'A1+B2': 'A1B2_concurrent',
    'A2+B1': 'A2B1_concurrent',
    'A2+B2': 'A2B2_concurrent',
}

SOLO_PHASES = ['A1', 'A2', 'B1', 'B2']
CONCURRENT_PHASES = ['A1+B1', 'A1+B2', 'A2+B1', 'A2+B2']

# Workload → cgroup mapping
WORKLOAD_CGROUP = {
    'A1': 'yolo.slice', 'A2': 'yolo.slice',
    'B1': 'nodejs.slice', 'B2': 'nodejs.slice',
}


def load_round(data_dir):
    """Load all host + cgroup CSVs for one round."""
    host = {}
    cgroup = {}

    for phase_name, prefix in PHASES_HOST.items():
        hf = data_dir / f"{prefix}_host.csv"
        cf = data_dir / f"{prefix}_cgroup.csv"

        if hf.exists():
            df = pd.read_csv(hf)
            host[phase_name] = df.iloc[TRIM_START:TRIM_END].copy()

        if cf.exists():
            df = pd.read_csv(cf)
            # trim: cgroup has 2 rows per timestamp (yolo + nodejs)
            timestamps = df['timestamp'].unique()
            trimmed_ts = timestamps[TRIM_START:TRIM_END] if len(timestamps) > abs(TRIM_END) + TRIM_START else timestamps
            cgroup[phase_name] = df[df['timestamp'].isin(trimmed_ts)].copy()

    return host, cgroup


def load_rpict():
    """Load RPICT wall power data."""
    if not RPICT_FILE.exists():
        print(f"[WARN] RPICT file not found: {RPICT_FILE}")
        return None
    return pd.read_csv(RPICT_FILE, parse_dates=['timestamp'])


def compute_idle(host_idle):
    """Compute idle baseline values."""
    return {
        'rapl_package_w': host_idle['rapl_package_w'].mean(),
        'rapl_core_w': host_idle['rapl_core_w'].mean(),
        'gpu0_power_w': host_idle['gpu0_power_w'].mean(),
        'gpu1_power_w': host_idle['gpu1_power_w'].mean(),
        'io_read_kbs': host_idle['io_read_kbs'].mean(),
        'io_write_kbs': host_idle['io_write_kbs'].mean(),
        'mem_used_pct': host_idle['mem_used_pct'].mean(),
    }


def compute_cgroup_stats(cg_df, cgroup_name):
    """Compute average cgroup stats for a specific slice."""
    sub = cg_df[cg_df['cgroup'] == cgroup_name]
    if sub.empty:
        return {'cpu_pct': 0, 'mem_mb': 0, 'io_read_kbs': 0, 'io_write_kbs': 0}
    return {
        'cpu_pct': sub['cpu_percent'].mean(),
        'mem_mb': sub['memory_mb'].mean(),
        'io_read_kbs': sub['io_read_kbs'].mean(),
        'io_write_kbs': sub['io_write_kbs'].mean(),
    }


def attribution_solo(host_df, cgroup_df, phase_name, idle):
    """5-component attribution for a solo workload."""
    h = host_df

    # CPU: RAPL package - idle
    cpu_total = h['rapl_package_w'].mean()
    cpu_active = cpu_total - idle['rapl_package_w']

    # GPU sensor (per card)
    gpu0_sensor = h['gpu0_power_w'].mean()
    gpu1_sensor = h['gpu1_power_w'].mean()

    # GPU hidden (constant per card)
    gpu0_hidden = GPU_HIDDEN_PER_CARD_W
    gpu1_hidden = GPU_HIDDEN_PER_CARD_W

    # A workloads use GPU0; B workloads use neither (GPU0 idle)
    if phase_name.startswith('A'):
        gpu_sensor = gpu0_sensor
        gpu_hidden = gpu0_hidden
        gpu_other_sensor = gpu1_sensor  # idle GPU1
    else:
        gpu_sensor = gpu0_sensor  # idle GPU0 (B doesn't use GPU)
        gpu_hidden = gpu0_hidden
        gpu_other_sensor = gpu1_sensor

    # Memory: proportional to cgroup memory usage
    cg = compute_cgroup_stats(cgroup_df, WORKLOAD_CGROUP[phase_name])
    mem_fraction = cg['mem_mb'] / TOTAL_MEM_MB if TOTAL_MEM_MB > 0 else 0
    mem_power = MEM_PER_DIMM_W * NUM_DIMMS * mem_fraction

    # Storage: io throughput (read + write) in MB/s
    io_throughput_mbs = (cg['io_read_kbs'] + cg['io_write_kbs']) / 1024.0
    storage_power = STORAGE_COEFF * io_throughput_mbs

    return {
        'phase': phase_name,
        'cpu_rapl_total': cpu_total,
        'cpu_active': cpu_active,
        'gpu0_sensor': gpu0_sensor,
        'gpu1_sensor': gpu1_sensor,
        'gpu0_hidden': gpu0_hidden,
        'gpu1_hidden': gpu1_hidden,
        'mem_power': mem_power,
        'mem_mb': cg['mem_mb'],
        'storage_power': storage_power,
        'io_mbs': io_throughput_mbs,
        'cg_cpu_pct': cg['cpu_pct'],
    }


def attribution_concurrent(host_df, cgroup_df, phase_name, idle):
    """
    5-component attribution for concurrent A+B.

    CPU_A = (RAPL - idle) × (A_cpu% / (A_cpu% + B_cpu%))
    GPU_A = GPU0_sensor (YOLO 독점 GPU0)
    GPU_hidden_A = 7.6W
    Mem_A = 0.25W/DIMM × (A_mem / total) × 2
    Storage_A = 0.0027 × A_io_throughput
    (B는 동일 구조, GPU1 사용)
    """
    h = host_df
    cpu_total = h['rapl_package_w'].mean()
    cpu_active = cpu_total - idle['rapl_package_w']

    gpu0_sensor = h['gpu0_power_w'].mean()
    gpu1_sensor = h['gpu1_power_w'].mean()

    # cgroup stats
    A_name, B_name = phase_name.split('+')
    yolo_cg = compute_cgroup_stats(cgroup_df, 'yolo.slice')
    node_cg = compute_cgroup_stats(cgroup_df, 'nodejs.slice')

    # CPU proportional split
    total_cpu_pct = yolo_cg['cpu_pct'] + node_cg['cpu_pct']
    if total_cpu_pct > 0:
        A_cpu_frac = yolo_cg['cpu_pct'] / total_cpu_pct
        B_cpu_frac = node_cg['cpu_pct'] / total_cpu_pct
    else:
        A_cpu_frac = 0.5
        B_cpu_frac = 0.5

    cpu_A = cpu_active * A_cpu_frac
    cpu_B = cpu_active * B_cpu_frac

    # GPU: GPU0 → A(YOLO), GPU1 → B(Node.js idle)
    gpu_sensor_A = gpu0_sensor
    gpu_sensor_B = gpu1_sensor
    gpu_hidden_A = GPU_HIDDEN_PER_CARD_W
    gpu_hidden_B = GPU_HIDDEN_PER_CARD_W

    # Memory
    A_mem_frac = yolo_cg['mem_mb'] / TOTAL_MEM_MB if TOTAL_MEM_MB > 0 else 0
    B_mem_frac = node_cg['mem_mb'] / TOTAL_MEM_MB if TOTAL_MEM_MB > 0 else 0
    mem_A = MEM_PER_DIMM_W * NUM_DIMMS * A_mem_frac
    mem_B = MEM_PER_DIMM_W * NUM_DIMMS * B_mem_frac

    # Storage
    A_io_mbs = (yolo_cg['io_read_kbs'] + yolo_cg['io_write_kbs']) / 1024.0
    B_io_mbs = (node_cg['io_read_kbs'] + node_cg['io_write_kbs']) / 1024.0
    storage_A = STORAGE_COEFF * A_io_mbs
    storage_B = STORAGE_COEFF * B_io_mbs

    # Total attributed per workload
    total_A = cpu_A + gpu_sensor_A + gpu_hidden_A + mem_A + storage_A
    total_B = cpu_B + gpu_sensor_B + gpu_hidden_B + mem_B + storage_B

    # System total from sensors
    sensor_total = cpu_total + gpu0_sensor + gpu1_sensor
    # Attribution total (includes hidden)
    attributed_total = total_A + total_B + idle['rapl_package_w']

    return {
        'phase': phase_name,
        'A': A_name, 'B': B_name,
        # Raw
        'cpu_rapl_total': cpu_total,
        'cpu_active': cpu_active,
        'gpu0_sensor': gpu0_sensor,
        'gpu1_sensor': gpu1_sensor,
        # A attribution
        'cpu_A': cpu_A, 'gpu_sensor_A': gpu_sensor_A,
        'gpu_hidden_A': gpu_hidden_A, 'mem_A': mem_A,
        'storage_A': storage_A, 'total_A': total_A,
        'A_cpu_pct': yolo_cg['cpu_pct'], 'A_mem_mb': yolo_cg['mem_mb'],
        'A_io_mbs': A_io_mbs,
        # B attribution
        'cpu_B': cpu_B, 'gpu_sensor_B': gpu_sensor_B,
        'gpu_hidden_B': gpu_hidden_B, 'mem_B': mem_B,
        'storage_B': storage_B, 'total_B': total_B,
        'B_cpu_pct': node_cg['cpu_pct'], 'B_mem_mb': node_cg['mem_mb'],
        'B_io_mbs': B_io_mbs,
        # Fractions
        'A_cpu_frac': A_cpu_frac, 'B_cpu_frac': B_cpu_frac,
    }


def match_rpict_to_phases(rpict_df, host_data, data_dir):
    """Match RPICT wall power to each phase by timestamp overlap."""
    wall_power = {}
    for phase_name, prefix in PHASES_HOST.items():
        if phase_name not in host_data:
            continue
        h = host_data[phase_name]
        if h.empty:
            continue

        t_start = pd.to_datetime(h['timestamp'].iloc[0])
        t_end = pd.to_datetime(h['timestamp'].iloc[-1])

        mask = (rpict_df['timestamp'] >= t_start) & (rpict_df['timestamp'] <= t_end)
        matched = rpict_df.loc[mask, 'power1_w']
        wall_power[phase_name] = matched.mean() if len(matched) > 0 else np.nan

    return wall_power


def solo_vs_concurrent_validation(solo_results, concurrent_results, idle, wall_power):
    """
    Core validation: concurrent attribution should match solo results.

    For A+B concurrent:
      attributed_A (from concurrent) ≈ solo_A_incremental
      attributed_B (from concurrent) ≈ solo_B_incremental
      Others_residual should be constant across all phases
    """
    rows = []

    for cr in concurrent_results:
        A_name = cr['A']
        B_name = cr['B']
        combo = cr['phase']

        # Solo incremental values (solo - idle)
        solo_A = next(s for s in solo_results if s['phase'] == A_name)
        solo_B = next(s for s in solo_results if s['phase'] == B_name)

        # Solo A incremental (above idle)
        solo_A_cpu = solo_A['cpu_active']
        solo_A_gpu_sensor = solo_A['gpu0_sensor']  # GPU0 when YOLO active
        solo_A_total_incr = solo_A_cpu + (solo_A_gpu_sensor - idle['gpu0_power_w'])

        # Solo B incremental
        solo_B_cpu = solo_B['cpu_active']
        solo_B_gpu_sensor = solo_B['gpu0_sensor']  # GPU0 idle when B runs
        solo_B_total_incr = solo_B_cpu  # B doesn't use GPU

        # Concurrent attributed
        conc_A_cpu = cr['cpu_A']
        conc_B_cpu = cr['cpu_B']

        # GPU0 incremental in concurrent (A is using GPU0)
        conc_A_gpu_incr = cr['gpu0_sensor'] - idle['gpu0_power_w']

        # Wall power
        wall = wall_power.get(combo, np.nan)
        wall_idle = wall_power.get('Idle', np.nan)

        # Others_residual = Wall - (CPU + GPU0_sensor + GPU1_sensor + 2×GPU_hidden + Mem + Storage)
        sensor_sum = (cr['cpu_rapl_total'] + cr['gpu0_sensor'] + cr['gpu1_sensor'])
        hidden_sum = 2 * GPU_HIDDEN_PER_CARD_W
        mem_sum = cr['mem_A'] + cr['mem_B']
        storage_sum = cr['storage_A'] + cr['storage_B']
        attributed_sensor = sensor_sum + hidden_sum + mem_sum + storage_sum
        others = wall - attributed_sensor if not np.isnan(wall) else np.nan

        # Error: concurrent CPU attribution vs solo CPU
        cpu_error_A = conc_A_cpu - solo_A_cpu
        cpu_error_B = conc_B_cpu - solo_B_cpu

        # Error: GPU0 sensor in concurrent vs solo
        gpu_error_A = cr['gpu0_sensor'] - solo_A['gpu0_sensor']

        # Total error: (concurrent attributed total) vs (solo A incr + solo B incr + idle)
        expected_total = solo_A['cpu_rapl_total'] + solo_B['cpu_rapl_total'] - idle['rapl_package_w'] \
                         + solo_A['gpu0_sensor'] + solo_B['gpu1_sensor']
        measured_total = cr['cpu_rapl_total'] + cr['gpu0_sensor'] + cr['gpu1_sensor']
        total_error = measured_total - expected_total
        total_error_pct = (total_error / expected_total * 100) if expected_total > 0 else 0

        rows.append({
            'combo': combo,
            'A': A_name, 'B': B_name,
            # Solo reference
            'solo_A_cpu': solo_A_cpu,
            'solo_A_gpu0': solo_A['gpu0_sensor'],
            'solo_B_cpu': solo_B_cpu,
            'solo_B_gpu1': solo_B['gpu1_sensor'],
            # Concurrent attributed
            'conc_A_cpu': conc_A_cpu,
            'conc_A_gpu0': cr['gpu0_sensor'],
            'conc_B_cpu': conc_B_cpu,
            'conc_B_gpu1': cr['gpu1_sensor'],
            # CPU split fracs
            'A_cpu_frac': cr['A_cpu_frac'],
            'B_cpu_frac': cr['B_cpu_frac'],
            # Errors
            'cpu_err_A': cpu_error_A,
            'cpu_err_B': cpu_error_B,
            'gpu_err_A': gpu_error_A,
            'total_error_w': total_error,
            'total_error_pct': total_error_pct,
            # 5-component
            'mem_A': cr['mem_A'], 'mem_B': cr['mem_B'],
            'storage_A': cr['storage_A'], 'storage_B': cr['storage_B'],
            'gpu_hidden_A': cr['gpu_hidden_A'], 'gpu_hidden_B': cr['gpu_hidden_B'],
            # Wall & residual
            'wall_w': wall,
            'wall_idle': wall_idle,
            'attributed_sensor': attributed_sensor,
            'others_residual': others,
        })

    return rows


# ══════════════════════════════════════════════
# Visualization functions
# ══════════════════════════════════════════════

def plot_5component_breakdown(solo_results, concurrent_results, idle, wall_power, round_name, out_dir):
    """Stacked bar chart: 5-component breakdown for all 9 phases."""
    phases_order = ['Idle', 'A1', 'A2', 'B1', 'B2', 'A1+B1', 'A1+B2', 'A2+B1', 'A2+B2']
    labels = phases_order

    cpu_vals, gpu0s_vals, gpu1s_vals, ghidden_vals, mem_vals, stor_vals, others_vals = \
        [], [], [], [], [], [], []

    for pname in phases_order:
        wall = wall_power.get(pname, np.nan)

        if pname == 'Idle':
            cpu_vals.append(idle['rapl_package_w'])
            gpu0s_vals.append(idle['gpu0_power_w'])
            gpu1s_vals.append(idle['gpu1_power_w'])
            ghidden_vals.append(2 * GPU_HIDDEN_PER_CARD_W)
            mem_vals.append(MEM_PER_DIMM_W * NUM_DIMMS)
            stor_vals.append(0)
            sensor_sum = idle['rapl_package_w'] + idle['gpu0_power_w'] + idle['gpu1_power_w'] \
                         + 2 * GPU_HIDDEN_PER_CARD_W + MEM_PER_DIMM_W * NUM_DIMMS
            others_vals.append(wall - sensor_sum if not np.isnan(wall) else 0)
            continue

        if pname in SOLO_PHASES:
            sr = next(s for s in solo_results if s['phase'] == pname)
            cpu_vals.append(sr['cpu_rapl_total'])
            gpu0s_vals.append(sr['gpu0_sensor'])
            gpu1s_vals.append(sr['gpu1_sensor'])
            ghidden_vals.append(2 * GPU_HIDDEN_PER_CARD_W)
            mem_vals.append(sr['mem_power'])
            stor_vals.append(sr['storage_power'])
            sensor_sum = sr['cpu_rapl_total'] + sr['gpu0_sensor'] + sr['gpu1_sensor'] \
                         + 2 * GPU_HIDDEN_PER_CARD_W + sr['mem_power'] + sr['storage_power']
            others_vals.append(wall - sensor_sum if not np.isnan(wall) else 0)
        else:
            cr = next(c for c in concurrent_results if c['phase'] == pname)
            cpu_vals.append(cr['cpu_rapl_total'])
            gpu0s_vals.append(cr['gpu0_sensor'])
            gpu1s_vals.append(cr['gpu1_sensor'])
            ghidden_vals.append(2 * GPU_HIDDEN_PER_CARD_W)
            mem_vals.append(cr['mem_A'] + cr['mem_B'])
            stor_vals.append(cr['storage_A'] + cr['storage_B'])
            sensor_sum = cr['cpu_rapl_total'] + cr['gpu0_sensor'] + cr['gpu1_sensor'] \
                         + 2 * GPU_HIDDEN_PER_CARD_W + cr['mem_A'] + cr['mem_B'] \
                         + cr['storage_A'] + cr['storage_B']
            others_vals.append(wall - sensor_sum if not np.isnan(wall) else 0)

    # Convert to numpy
    cpu_v = np.array(cpu_vals)
    gpu0_v = np.array(gpu0s_vals)
    gpu1_v = np.array(gpu1s_vals)
    ghid_v = np.array(ghidden_vals)
    mem_v = np.array(mem_vals)
    stor_v = np.array(stor_vals)
    oth_v = np.array(others_vals)

    fig, ax = plt.subplots(figsize=(16, 7))
    x = np.arange(len(labels))
    w = 0.6

    bottom = np.zeros(len(labels))
    components = [
        (cpu_v,  'CPU (RAPL)',       '#E74C3C'),
        (gpu0_v, 'GPU0 sensor',      '#3498DB'),
        (gpu1_v, 'GPU1 sensor',      '#85C1E9'),
        (ghid_v, 'GPU hidden (2×7.6W)', '#AED6F1'),
        (mem_v,  'Memory',           '#2ECC71'),
        (stor_v, 'Storage',          '#F39C12'),
        (oth_v,  'Others (residual)','#95A5A6'),
    ]

    for vals, label, color in components:
        ax.bar(x, vals, w, bottom=bottom, label=label, color=color, edgecolor='white', linewidth=0.3)
        bottom += vals

    # Wall power markers
    wall_vals = [wall_power.get(p, np.nan) for p in phases_order]
    ax.scatter(x, wall_vals, color='black', marker='_', s=300, linewidths=2.5, zorder=5, label='Wall (RPICT)')

    # Labels
    for i, wv in enumerate(wall_vals):
        if not np.isnan(wv):
            ax.text(i, wv + 1.5, f'{wv:.0f}W', ha='center', va='bottom', fontsize=8, fontweight='bold')

    ax.set_ylabel('Power (W)', fontsize=12)
    ax.set_title(f'5-Component Power Attribution — {round_name}', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha='right')
    ax.legend(loc='upper left', fontsize=9)
    ax.set_ylim(0, max(bottom.max(), np.nanmax(wall_vals)) * 1.15)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='y', alpha=0.2)

    plt.tight_layout()
    fpath = out_dir / f'5component_breakdown_{round_name.lower().replace(" ","_")}.png'
    plt.savefig(fpath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {fpath.name}")


def plot_validation_chart(validation_rows, round_name, out_dir):
    """Solo vs Concurrent attribution comparison (4 combos)."""
    combos = [r['combo'] for r in validation_rows]

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    axes = axes.flatten()

    for idx, row in enumerate(validation_rows):
        ax = axes[idx]
        categories = ['CPU_A', 'GPU0', 'CPU_B', 'GPU1']
        solo_vals = [row['solo_A_cpu'], row['solo_A_gpu0'], row['solo_B_cpu'], row['solo_B_gpu1']]
        conc_vals = [row['conc_A_cpu'], row['conc_A_gpu0'], row['conc_B_cpu'], row['conc_B_gpu1']]

        x = np.arange(len(categories))
        w = 0.3

        bars1 = ax.bar(x - w/2, solo_vals, w, label='Solo (reference)', color='#3498DB', alpha=0.8)
        bars2 = ax.bar(x + w/2, conc_vals, w, label='Concurrent (attributed)', color='#E74C3C', alpha=0.8)

        ax.set_ylabel('Power (W)')
        ax.set_title(f'{row["combo"]}  |  Error: {row["total_error_pct"]:+.1f}%',
                     fontsize=12, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(categories)
        ax.legend(fontsize=9)
        ax.grid(axis='y', alpha=0.2)

        # Value labels
        for bars in [bars1, bars2]:
            for bar in bars:
                h = bar.get_height()
                if h > 0.5:
                    ax.text(bar.get_x() + bar.get_width()/2, h,
                           f'{h:.1f}', ha='center', va='bottom', fontsize=8)

    plt.suptitle(f'Solo vs Concurrent Validation — {round_name}', fontsize=14, fontweight='bold', y=1.01)
    plt.tight_layout()
    fpath = out_dir / f'validation_{round_name.lower().replace(" ","_")}.png'
    plt.savefig(fpath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {fpath.name}")


def plot_others_residual(validation_rows_fixed, validation_rows_free, idle_wall_fixed, idle_wall_free, out_dir):
    """Others_residual should be constant across phases."""
    fig, ax = plt.subplots(figsize=(12, 5))

    labels_f = ['Idle'] + [r['combo'] for r in validation_rows_fixed]
    vals_f = [idle_wall_fixed] + [r['others_residual'] for r in validation_rows_fixed]

    labels_r = ['Idle'] + [r['combo'] for r in validation_rows_free]
    vals_r = [idle_wall_free] + [r['others_residual'] for r in validation_rows_free]

    x = np.arange(len(labels_f))
    w = 0.3

    ax.bar(x - w/2, vals_f, w, label='Fixed freq', color='#3498DB', alpha=0.8)
    ax.bar(x + w/2, vals_r, w, label='Free freq', color='#E74C3C', alpha=0.8)

    # Std dev annotations
    valid_f = [v for v in vals_f if not np.isnan(v)]
    valid_r = [v for v in vals_r if not np.isnan(v)]
    if valid_f:
        ax.axhline(np.mean(valid_f), color='#3498DB', linestyle='--', alpha=0.5)
        ax.text(len(x)-0.5, np.mean(valid_f)+0.5,
                f'Fixed: μ={np.mean(valid_f):.1f}W, σ={np.std(valid_f):.1f}W',
                fontsize=9, color='#3498DB')
    if valid_r:
        ax.axhline(np.mean(valid_r), color='#E74C3C', linestyle='--', alpha=0.5)
        ax.text(len(x)-0.5, np.mean(valid_r)-1.5,
                f'Free: μ={np.mean(valid_r):.1f}W, σ={np.std(valid_r):.1f}W',
                fontsize=9, color='#E74C3C')

    ax.set_ylabel('Others Residual (W)', fontsize=12)
    ax.set_title('Others_residual Consistency Check (should be constant)', fontsize=13, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels_f)
    ax.legend()
    ax.grid(axis='y', alpha=0.2)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    fpath = out_dir / 'others_residual_consistency.png'
    plt.savefig(fpath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {fpath.name}")


def plot_cpu_freq_comparison(host_fixed, host_free, out_dir):
    """Compare CPU frequency distribution: fixed vs free."""
    freq_cols = [c for c in host_fixed.get('A2+B2', pd.DataFrame()).columns if c.endswith('_mhz')]
    if not freq_cols:
        print("  [SKIP] No per-core freq columns found")
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    for ax, (host, title) in zip(axes, [(host_fixed, 'Fixed (3.6GHz)'), (host_free, 'Free (Turbo)')]):
        all_freqs = []
        for phase_name in ['Idle', 'A1', 'B2', 'A2+B2']:
            if phase_name in host:
                df = host[phase_name]
                avg = df[freq_cols].mean(axis=1).values
                all_freqs.append((phase_name, avg))

        for pname, freqs in all_freqs:
            ax.hist(freqs, bins=30, alpha=0.5, label=pname, density=True)

        ax.set_xlabel('CPU Frequency (MHz)')
        ax.set_ylabel('Density')
        ax.set_title(title, fontweight='bold')
        ax.legend()
        ax.grid(alpha=0.2)

    plt.suptitle('CPU Frequency Distribution', fontsize=13, fontweight='bold')
    plt.tight_layout()
    fpath = out_dir / 'cpu_freq_distribution.png'
    plt.savefig(fpath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {fpath.name}")


# ══════════════════════════════════════════════
# Text report
# ══════════════════════════════════════════════

def print_report(round_name, idle, solo_results, concurrent_results, validation_rows, wall_power):
    """Print comprehensive text report."""
    sep = "=" * 90
    print(f"\n{sep}")
    print(f"  Phase 2.2 — {round_name} Results")
    print(f"{sep}")

    # Idle
    print(f"\n[Idle Baseline]")
    print(f"  RAPL package: {idle['rapl_package_w']:.2f} W")
    print(f"  GPU0 sensor:  {idle['gpu0_power_w']:.2f} W")
    print(f"  GPU1 sensor:  {idle['gpu1_power_w']:.2f} W")
    wall_idle = wall_power.get('Idle', np.nan)
    print(f"  Wall (RPICT): {wall_idle:.1f} W" if not np.isnan(wall_idle) else "  Wall: N/A")

    # Solo results
    print(f"\n[Solo Workloads]")
    print(f"  {'Phase':<6} {'RAPL':>8} {'GPU0':>8} {'GPU1':>8} {'Mem':>8} {'Stor':>8} {'Wall':>8} {'cg_CPU%':>8}")
    print(f"  {'-'*62}")
    for sr in solo_results:
        w = wall_power.get(sr['phase'], np.nan)
        print(f"  {sr['phase']:<6} {sr['cpu_rapl_total']:>8.1f} {sr['gpu0_sensor']:>8.1f} "
              f"{sr['gpu1_sensor']:>8.1f} {sr['mem_power']:>8.3f} {sr['storage_power']:>8.4f} "
              f"{w:>8.1f} {sr['cg_cpu_pct']:>8.1f}")

    # Concurrent attribution
    print(f"\n[Concurrent — Per-Workload Attribution]")
    print(f"  {'Combo':<8} {'|':>2} {'CPU_A':>7} {'GPU0_A':>7} {'ghid_A':>7} {'mem_A':>7} "
          f"{'|':>2} {'CPU_B':>7} {'GPU1_B':>7} {'ghid_B':>7} {'mem_B':>7}")
    print(f"  {'-'*78}")
    for cr in concurrent_results:
        print(f"  {cr['phase']:<8} {'|':>2} {cr['cpu_A']:>7.1f} {cr['gpu_sensor_A']:>7.1f} "
              f"{cr['gpu_hidden_A']:>7.1f} {cr['mem_A']:>7.3f} "
              f"{'|':>2} {cr['cpu_B']:>7.1f} {cr['gpu_sensor_B']:>7.1f} "
              f"{cr['gpu_hidden_B']:>7.1f} {cr['mem_B']:>7.3f}")

    # Validation
    print(f"\n[Validation: Solo vs Concurrent]")
    print(f"  {'Combo':<8} {'Exp_CPU+GPU':>12} {'Meas_CPU+GPU':>13} {'Error(W)':>10} {'Error(%)':>10} "
          f"{'Others':>10}")
    print(f"  {'-'*68}")
    for vr in validation_rows:
        expected = vr['solo_A_cpu'] + vr['solo_A_gpu0'] + vr['solo_B_cpu'] + vr['solo_B_gpu1'] \
                   - idle['rapl_package_w']
        measured = vr['conc_A_cpu'] + vr['conc_A_gpu0'] + vr['conc_B_cpu'] + vr['conc_B_gpu1'] \
                   + idle['rapl_package_w']
        print(f"  {vr['combo']:<8} {expected:>12.1f} {measured:>13.1f} "
              f"{vr['total_error_w']:>+10.1f} {vr['total_error_pct']:>+10.1f} "
              f"{vr['others_residual']:>10.1f}" if not np.isnan(vr['others_residual'])
              else f"  {vr['combo']:<8} ... Others: N/A")

    # Others residual
    others_list = [vr['others_residual'] for vr in validation_rows if not np.isnan(vr['others_residual'])]
    if others_list:
        print(f"\n  Others_residual: mean={np.mean(others_list):.1f}W, std={np.std(others_list):.1f}W")
        if np.std(others_list) < 2:
            print(f"  ✓ Others std < 2W → 5-component model is consistent")
        else:
            print(f"  ✗ Others std ≥ 2W → model has unaccounted variation")

    print(f"{sep}\n")


def export_csv(validation_rows_fixed, validation_rows_free, solo_fixed, solo_free, out_dir):
    """Export all results to CSV."""
    # Validation table
    all_rows = []
    for row in validation_rows_fixed:
        row_copy = dict(row)
        row_copy['round'] = 'fixed'
        all_rows.append(row_copy)
    for row in validation_rows_free:
        row_copy = dict(row)
        row_copy['round'] = 'free'
        all_rows.append(row_copy)

    df = pd.DataFrame(all_rows)
    fpath = out_dir / 'validation_results.csv'
    df.to_csv(fpath, index=False, float_format='%.3f')
    print(f"  Saved: {fpath.name}")

    # Solo summary
    solo_rows = []
    for sr in solo_fixed:
        sr_copy = dict(sr)
        sr_copy['round'] = 'fixed'
        solo_rows.append(sr_copy)
    for sr in solo_free:
        sr_copy = dict(sr)
        sr_copy['round'] = 'free'
        solo_rows.append(sr_copy)

    df2 = pd.DataFrame(solo_rows)
    fpath2 = out_dir / 'solo_attribution.csv'
    df2.to_csv(fpath2, index=False, float_format='%.3f')
    print(f"  Saved: {fpath2.name}")


# ══════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════

def analyze_round(data_dir, rpict_df, round_name):
    """Full analysis for one round."""
    print(f"\n{'#'*60}")
    print(f"  Loading {round_name}...")
    print(f"{'#'*60}")

    host, cgroup = load_round(data_dir)

    if 'Idle' not in host:
        print(f"[ERROR] No baseline data for {round_name}")
        return None, None, None, None, None

    idle = compute_idle(host['Idle'])

    # Solo attribution
    solo_results = []
    for phase in SOLO_PHASES:
        if phase in host and phase in cgroup:
            sr = attribution_solo(host[phase], cgroup[phase], phase, idle)
            solo_results.append(sr)

    # Concurrent attribution
    concurrent_results = []
    for phase in CONCURRENT_PHASES:
        if phase in host and phase in cgroup:
            cr = attribution_concurrent(host[phase], cgroup[phase], phase, idle)
            concurrent_results.append(cr)

    # Match RPICT
    wall_power = {}
    if rpict_df is not None:
        wall_power = match_rpict_to_phases(rpict_df, host, data_dir)

    # Validation
    validation = solo_vs_concurrent_validation(solo_results, concurrent_results, idle, wall_power)

    # Report
    print_report(round_name, idle, solo_results, concurrent_results, validation, wall_power)

    return idle, solo_results, concurrent_results, validation, wall_power, host


def main():
    print("=" * 60)
    print("  Phase 2.2: 5-Component Attribution Analysis")
    print("=" * 60)

    rpict_df = load_rpict()

    # Analyze both rounds
    idle_f, solo_f, conc_f, val_f, wall_f, host_f = analyze_round(FIXED_DIR, rpict_df, "Round 1: Fixed Freq")
    idle_r, solo_r, conc_r, val_r, wall_r, host_r = analyze_round(FREE_DIR, rpict_df, "Round 2: Free Freq")

    # ── Cross-round comparison ──
    print("\n" + "=" * 60)
    print("  Fixed vs Free Frequency Comparison")
    print("=" * 60)

    if val_f and val_r:
        print(f"\n  {'Combo':<8} {'Fixed Err%':>12} {'Free Err%':>12} {'Fixed Others':>14} {'Free Others':>14}")
        print(f"  {'-'*64}")
        for vf, vr in zip(val_f, val_r):
            print(f"  {vf['combo']:<8} {vf['total_error_pct']:>+12.1f} {vr['total_error_pct']:>+12.1f} "
                  f"{vf['others_residual']:>14.1f}" if not np.isnan(vf['others_residual']) else "",
                  f"{vr['others_residual']:>14.1f}" if not np.isnan(vr.get('others_residual', np.nan)) else "")

    # ── Generate charts ──
    print("\nGenerating charts...")
    fig_dir = OUTPUT_DIR / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    if solo_f and conc_f and wall_f:
        plot_5component_breakdown(solo_f, conc_f, idle_f, wall_f, "Round 1 Fixed Freq", fig_dir)
        plot_validation_chart(val_f, "Round 1 Fixed Freq", fig_dir)

    if solo_r and conc_r and wall_r:
        plot_5component_breakdown(solo_r, conc_r, idle_r, wall_r, "Round 2 Free Freq", fig_dir)
        plot_validation_chart(val_r, "Round 2 Free Freq", fig_dir)

    # Others residual comparison
    if val_f and val_r:
        idle_wall_f_others = wall_f.get('Idle', np.nan) - (idle_f['rapl_package_w'] + idle_f['gpu0_power_w']
                             + idle_f['gpu1_power_w'] + 2*GPU_HIDDEN_PER_CARD_W + MEM_PER_DIMM_W*NUM_DIMMS) \
                             if wall_f.get('Idle') else np.nan
        idle_wall_r_others = wall_r.get('Idle', np.nan) - (idle_r['rapl_package_w'] + idle_r['gpu0_power_w']
                             + idle_r['gpu1_power_w'] + 2*GPU_HIDDEN_PER_CARD_W + MEM_PER_DIMM_W*NUM_DIMMS) \
                             if wall_r.get('Idle') else np.nan
        plot_others_residual(val_f, val_r, idle_wall_f_others, idle_wall_r_others, fig_dir)

    # CPU freq comparison
    if host_f and host_r:
        plot_cpu_freq_comparison(host_f, host_r, fig_dir)

    # ── Export CSV ──
    print("\nExporting CSV...")
    export_csv(val_f or [], val_r or [], solo_f or [], solo_r or [], OUTPUT_DIR)

    print(f"\n{'=' * 60}")
    print(f"  Analysis complete!")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
