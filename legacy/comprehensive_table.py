#!/usr/bin/env python3
"""
Phase 1.6 - 종합 속성값 테이블
Host + Cgroup + RPICT 데이터를 모두 통합하여
교수님이 요구하는 모든 속성값을 한 번에 출력
"""

import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data/raw/alienware/phase1.6_test2"
RPICT_FILE = BASE_DIR / "data/raw/rpict/rpict_phase1.5-test4.csv"
OUTPUT_DIR = BASE_DIR / "reports/phase1.6"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PHASES = {
    'Idle':  {'file': 'baseline',  'start': 5, 'end': -3},
    'A1':    {'file': 'A1_yolo_nano',       'start': 5, 'end': -5},
    'A2':    {'file': 'A2_yolo_medium',     'start': 5, 'end': -5},
    'B1':    {'file': 'B1_nodejs_light',    'start': 5, 'end': -3},
    'B2':    {'file': 'B2_nodejs_heavy',    'start': 5, 'end': -3},
    'A1+B1': {'file': 'A1B1_concurrent',   'start': 5, 'end': -5},
    'A1+B2': {'file': 'A1B2_concurrent',   'start': 5, 'end': -5},
    'A2+B1': {'file': 'A2B1_concurrent',   'start': 5, 'end': -5},
    'A2+B2': {'file': 'A2B2_concurrent',   'start': 5, 'end': -5},
}


def load_all():
    rpict = pd.read_csv(RPICT_FILE)
    rpict['ts'] = pd.to_datetime(rpict['timestamp'])

    data = {}
    for name, info in PHASES.items():
        # --- Host data ---
        host_file = DATA_DIR / f"{info['file']}_host.csv"
        hdf = pd.read_csv(host_file)
        hdf['ts'] = pd.to_datetime(hdf['timestamp'])
        h = hdf.iloc[info['start']:info['end']]

        # RPICT wall power
        t0, t1 = h['ts'].iloc[0], h['ts'].iloc[-1]
        rm = rpict[(rpict['ts'] >= t0) & (rpict['ts'] <= t1)]
        wall = rm['power1_w'].mean() if len(rm) > 0 else np.nan

        # Host metrics
        cpu_w = h['rapl_package_w'].mean()
        gpu_w = h['gpu_power_w'].mean()
        dram_w = h['rapl_dram_w'].mean()
        others = wall - cpu_w - gpu_w if not np.isnan(wall) else np.nan

        host_metrics = {
            'wall': wall,
            'cpu_w': cpu_w,
            'gpu_w': gpu_w,
            'dram_w': dram_w,
            'others': others,
            'cpu_pct': h['cpu_pct'].mean(),
            'gpu_util_pct': h['gpu_util_pct'].mean(),
            'iowait_pct': h['iowait_pct'].mean(),
            'io_read_kbs': h['io_read_kbs'].mean(),
            'io_write_kbs': h['io_write_kbs'].mean(),
            'mem_used_pct': h['mem_used_pct'].mean(),
            'samples': len(h),
        }

        # --- Cgroup data ---
        cgroup_file = DATA_DIR / f"{info['file']}_cgroup.csv"
        cdf = pd.read_csv(cgroup_file)
        cdf['ts'] = pd.to_datetime(cdf['timestamp'])

        # Cgroup has 2 rows per timestamp (yolo.slice + nodejs.slice)
        # Need to trim by matching timestamps to host trimmed range
        cdf_trim = cdf[(cdf['ts'] >= t0) & (cdf['ts'] <= t1)]

        yolo = cdf_trim[cdf_trim['cgroup'] == 'yolo.slice']
        nodejs = cdf_trim[cdf_trim['cgroup'] == 'nodejs.slice']

        cgroup_metrics = {
            'yolo_cpu_pct': yolo['cpu_percent'].mean() if len(yolo) > 0 else 0,
            'yolo_mem_mb': yolo['memory_mb'].mean() if len(yolo) > 0 else 0,
            'yolo_io_read': yolo['io_read_kbs'].mean() if len(yolo) > 0 else 0,
            'yolo_io_write': yolo['io_write_kbs'].mean() if len(yolo) > 0 else 0,
            'nodejs_cpu_pct': nodejs['cpu_percent'].mean() if len(nodejs) > 0 else 0,
            'nodejs_mem_mb': nodejs['memory_mb'].mean() if len(nodejs) > 0 else 0,
            'nodejs_io_read': nodejs['io_read_kbs'].mean() if len(nodejs) > 0 else 0,
            'nodejs_io_write': nodejs['io_write_kbs'].mean() if len(nodejs) > 0 else 0,
        }

        data[name] = {**host_metrics, **cgroup_metrics}

    return data


def print_table1_power(data):
    """Table 1: Power Breakdown (기존 + DRAM)"""
    idle = data['Idle']
    print("\n" + "=" * 130)
    print("Table 1: Power Breakdown (Wall = CPU + GPU + Others)")
    print("=" * 130)
    print(f"{'Phase':<10} {'Wall(W)':<10} {'CPU(W)':<10} {'GPU(W)':<10} {'DRAM(W)':<10} {'Others(W)':<10} "
          f"{'dWall':<10} {'dCPU':<10} {'dGPU':<10} {'dOthers':<10}")
    print("-" * 130)

    for name in PHASES:
        d = data[name]
        dw = d['wall'] - idle['wall'] if not np.isnan(d['wall']) else np.nan
        dc = d['cpu_w'] - idle['cpu_w']
        dg = d['gpu_w'] - idle['gpu_w']
        do = d['others'] - idle['others'] if not np.isnan(d['others']) else np.nan

        def f(v): return f"{v:.1f}" if not np.isnan(v) else "N/A"
        def fd(v):
            if np.isnan(v): return "N/A"
            return f"{v:+.1f}" if abs(v) > 0.05 else "0.0"

        print(f"{name:<10} {f(d['wall']):<10} {f(d['cpu_w']):<10} {f(d['gpu_w']):<10} "
              f"{f(d['dram_w']):<10} {f(d['others']):<10} "
              f"{fd(dw):<10} {fd(dc):<10} {fd(dg):<10} {fd(do):<10}")

    print("=" * 130)


def print_table2_utilization(data):
    """Table 2: System-level Utilization"""
    print("\n" + "=" * 100)
    print("Table 2: System-level Utilization (Host)")
    print("=" * 100)
    print(f"{'Phase':<10} {'CPU%':<10} {'GPU%':<10} {'IOWait%':<10} "
          f"{'IO_R(KB/s)':<12} {'IO_W(KB/s)':<12} {'Mem%':<10}")
    print("-" * 100)

    for name in PHASES:
        d = data[name]
        print(f"{name:<10} {d['cpu_pct']:<10.1f} {d['gpu_util_pct']:<10.1f} {d['iowait_pct']:<10.2f} "
              f"{d['io_read_kbs']:<12.1f} {d['io_write_kbs']:<12.1f} {d['mem_used_pct']:<10.1f}")

    print("=" * 100)


def print_table3_cgroup(data):
    """Table 3: Per-Workload Metrics (Cgroup) - 교수님 핵심 요구"""
    print("\n" + "=" * 130)
    print("Table 3: Per-Workload Metrics (cgroup v2)")
    print("  cpu_percent: cgroup 내 CPU 사용률 (200% = 2 cores fully used)")
    print("  memory_mb: cgroup 메모리 사용량")
    print("=" * 130)
    print(f"{'Phase':<10} {'A(yolo)':<8} {'A_CPU%':<10} {'A_Mem(MB)':<10} {'A_IOR':<10} {'A_IOW':<10} "
          f"{'B(node)':<8} {'B_CPU%':<10} {'B_Mem(MB)':<10} {'B_IOR':<10} {'B_IOW':<10}")
    print("-" * 130)

    for name in PHASES:
        d = data[name]
        print(f"{name:<10} {'yolo':<8} {d['yolo_cpu_pct']:<10.1f} {d['yolo_mem_mb']:<10.1f} "
              f"{d['yolo_io_read']:<10.1f} {d['yolo_io_write']:<10.1f} "
              f"{'nodejs':<8} {d['nodejs_cpu_pct']:<10.1f} {d['nodejs_mem_mb']:<10.1f} "
              f"{d['nodejs_io_read']:<10.1f} {d['nodejs_io_write']:<10.1f}")

    print("=" * 130)


def print_table4_attribution(data):
    """Table 4: Energy Attribution (교수님 수식 적용)"""
    idle = data['Idle']

    combos = [('A1', 'B1', 'A1+B1'), ('A1', 'B2', 'A1+B2'),
              ('A2', 'B1', 'A2+B1'), ('A2', 'B2', 'A2+B2')]

    print("\n" + "=" * 140)
    print("Table 4: Energy Attribution Model (Concurrent)")
    print("  CPU 귀속: cgroup cpu_percent 비율로 (CPU_conc - CPU_idle) 분배")
    print("  GPU 귀속: YOLO만 GPU 사용 → A가 (GPU_conc - GPU_idle) 전부, B=0")
    print("  Memory 귀속: cgroup memory_mb 비율로 배분 (향후 Mem 에너지 파라미터 필요)")
    print("=" * 140)
    print(f"{'Combo':<10} {'CPU_A(W)':<10} {'CPU_B(W)':<10} {'GPU_A(W)':<10} {'GPU_B(W)':<10} "
          f"{'A_total':<10} {'B_total':<10} {'Sum(A+B)':<10} "
          f"{'Solo_A':<10} {'Solo_B':<10} {'Solo_Sum':<10} {'Error%':<10}")
    print("-" * 140)

    for A, B, AB in combos:
        d = data[AB]

        # CPU attribution by cgroup cpu_percent ratio
        a_cpu_pct = d['yolo_cpu_pct']
        b_cpu_pct = d['nodejs_cpu_pct']
        total_cpu_pct = a_cpu_pct + b_cpu_pct

        cpu_delta = d['cpu_w'] - idle['cpu_w']
        if total_cpu_pct > 0:
            cpu_A = cpu_delta * (a_cpu_pct / total_cpu_pct)
            cpu_B = cpu_delta * (b_cpu_pct / total_cpu_pct)
        else:
            cpu_A = cpu_B = 0

        # GPU attribution: YOLO only
        gpu_delta = d['gpu_w'] - idle['gpu_w']
        gpu_A = gpu_delta
        gpu_B = 0

        # Total attributed
        a_total = cpu_A + gpu_A
        b_total = cpu_B + gpu_B
        sum_ab = a_total + b_total

        # Solo comparison (Solo - Idle)
        solo_a = (data[A]['cpu_w'] - idle['cpu_w']) + (data[A]['gpu_w'] - idle['gpu_w'])
        solo_b = (data[B]['cpu_w'] - idle['cpu_w']) + (data[B]['gpu_w'] - idle['gpu_w'])
        solo_sum = solo_a + solo_b

        error_pct = ((sum_ab - solo_sum) / solo_sum * 100) if solo_sum > 0 else 0

        print(f"{AB:<10} {cpu_A:<10.1f} {cpu_B:<10.1f} {gpu_A:<10.1f} {gpu_B:<10.1f} "
              f"{a_total:<10.1f} {b_total:<10.1f} {sum_ab:<10.1f} "
              f"{solo_a:<10.1f} {solo_b:<10.1f} {solo_sum:<10.1f} {error_pct:<+10.1f}")

    print("=" * 140)


def print_table5_validation_wall(data):
    """Table 5: Wall Power Validation (RPICT)"""
    idle = data['Idle']

    combos = [('A1', 'B1', 'A1+B1'), ('A1', 'B2', 'A1+B2'),
              ('A2', 'B1', 'A2+B1'), ('A2', 'B2', 'A2+B2')]

    print("\n" + "=" * 120)
    print("Table 5: Wall Power Validation (RPICT)")
    print("  Expected = Solo_A_delta + Solo_B_delta + Idle")
    print("  Measured = Concurrent Wall")
    print("=" * 120)
    print(f"{'Combo':<10} {'Idle':<10} {'dA_solo':<10} {'dB_solo':<10} "
          f"{'Expected':<10} {'Measured':<10} {'Error(W)':<10} {'Error%':<10}")
    print("-" * 120)

    for A, B, AB in combos:
        da = data[A]['wall'] - idle['wall']
        db = data[B]['wall'] - idle['wall']
        expected = da + db + idle['wall']
        measured = data[AB]['wall']
        error = measured - expected
        error_pct = (error / expected * 100) if expected > 0 else 0

        print(f"{AB:<10} {idle['wall']:<10.1f} {da:<10.1f} {db:<10.1f} "
              f"{expected:<10.1f} {measured:<10.1f} {error:<+10.1f} {error_pct:<+10.1f}")

    print("=" * 120)


def export_csv(data):
    """Export all data to CSV for further analysis"""
    rows = []
    for name in PHASES:
        d = data[name]
        d['phase'] = name
        rows.append(d)
    df = pd.DataFrame(rows)

    cols = ['phase', 'wall', 'cpu_w', 'gpu_w', 'dram_w', 'others',
            'cpu_pct', 'gpu_util_pct', 'iowait_pct', 'io_read_kbs', 'io_write_kbs', 'mem_used_pct',
            'yolo_cpu_pct', 'yolo_mem_mb', 'yolo_io_read', 'yolo_io_write',
            'nodejs_cpu_pct', 'nodejs_mem_mb', 'nodejs_io_read', 'nodejs_io_write',
            'samples']
    df = df[cols]
    outfile = OUTPUT_DIR / 'comprehensive_table.csv'
    df.to_csv(outfile, index=False, float_format='%.2f')
    print(f"\nCSV saved: {outfile}")
    return df


if __name__ == "__main__":
    print("Loading all data (Host + Cgroup + RPICT)...")
    data = load_all()

    print_table1_power(data)
    print_table2_utilization(data)
    print_table3_cgroup(data)
    print_table4_attribution(data)
    print_table5_validation_wall(data)

    export_csv(data)
