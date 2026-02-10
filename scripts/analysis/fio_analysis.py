#!/usr/bin/env python3
"""
Phase 2.0b: fio Storage 에너지 분석
fio 실험 결과에서 Storage 에너지 파라미터 도출

Storage_power = Wall(fio) - Wall(idle) - dCPU
              = (순수 Storage에 의한 추가 전력)

Storage_per_throughput = Storage_power / Throughput(MB/s)
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path

BASE_DIR = Path("/Users/rainyforest/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution")
DATA_DIR = BASE_DIR / "data/raw/alienware/phase2.0_fio"
RPICT_DIR = BASE_DIR / "data/raw/rpict"
OUTPUT_DIR = BASE_DIR / "reports/phase2"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 앞뒤 트림 (안정화 + fio 시작 전/후)
TRIM_START = 8   # host_logger가 fio보다 3초 먼저 시작 + warmup 5초
TRIM_END = -3


def load_host_data(name):
    """host CSV 로드 + 트림 + 평균"""
    filepath = DATA_DIR / f"{name}_host.csv"
    if not filepath.exists():
        return None

    df = pd.read_csv(filepath)
    df_trim = df.iloc[TRIM_START:TRIM_END] if len(df) > abs(TRIM_START) + abs(TRIM_END) else df

    result = {
        'cpu_w': df_trim['rapl_package_w'].mean(),
        'gpu_w': df_trim['gpu_power_w'].mean(),
        'cpu_pct': df_trim['cpu_pct'].mean(),
        'iowait_pct': df_trim['iowait_pct'].mean(),
        'io_read_kbs': df_trim['io_read_kbs'].mean(),
        'io_write_kbs': df_trim['io_write_kbs'].mean(),
        'samples': len(df_trim),
    }

    # CPU frequency (있으면)
    freq_cols = [c for c in df_trim.columns if c.endswith('_mhz')]
    if freq_cols:
        result['avg_freq_mhz'] = df_trim[freq_cols].mean().mean()

    return result


def load_fio_result(name):
    """fio JSON 결과 파싱"""
    filepath = DATA_DIR / f"{name}_fio.json"
    if not filepath.exists():
        return None

    with open(filepath) as f:
        data = json.load(f)

    job = data['jobs'][0]
    result = {}

    # Read 성능
    if job['read']['io_bytes'] > 0:
        result['read_bw_mbs'] = job['read']['bw'] / 1024  # KB/s → MB/s
        result['read_iops'] = job['read']['iops']
        result['read_lat_us'] = job['read']['lat_ns']['mean'] / 1000

    # Write 성능
    if job['write']['io_bytes'] > 0:
        result['write_bw_mbs'] = job['write']['bw'] / 1024
        result['write_iops'] = job['write']['iops']
        result['write_lat_us'] = job['write']['lat_ns']['mean'] / 1000

    return result


def analyze():
    print("=" * 100)
    print("Phase 2.0b: fio Storage Energy Analysis")
    print("=" * 100)

    # Idle baseline
    idle = load_host_data("idle_baseline")
    if idle is None:
        print("[ERROR] idle_baseline_host.csv 없음")
        return

    print(f"\nIdle Baseline: CPU={idle['cpu_w']:.2f}W, GPU={idle['gpu_w']:.2f}W")

    # fio 테스트별 분석
    tests = [
        ('seq_read',   'Sequential Read',  '1M'),
        ('seq_write',  'Sequential Write', '1M'),
        ('rand_read',  'Random Read',      '4K'),
        ('rand_write', 'Random Write',     '4K'),
    ]

    results = []

    print(f"\n{'Test':<20} {'CPU(W)':<10} {'dCPU(W)':<10} {'GPU(W)':<10} "
          f"{'IOWait%':<10} {'Throughput':<15} {'IOPS':<12}")
    print("-" * 100)

    for test_name, label, bs in tests:
        host = load_host_data(test_name)
        fio = load_fio_result(test_name)

        if host is None:
            print(f"{label:<20} (데이터 없음)")
            continue

        d_cpu = host['cpu_w'] - idle['cpu_w']
        d_gpu = host['gpu_w'] - idle['gpu_w']

        # Throughput & IOPS
        if fio:
            if 'read_bw_mbs' in fio:
                throughput = f"{fio['read_bw_mbs']:.0f} MB/s"
                iops = f"{fio['read_iops']:.0f}"
                throughput_val = fio['read_bw_mbs']
            else:
                throughput = f"{fio['write_bw_mbs']:.0f} MB/s"
                iops = f"{fio['write_iops']:.0f}"
                throughput_val = fio['write_bw_mbs']
        else:
            throughput = "N/A"
            iops = "N/A"
            throughput_val = 0

        print(f"{label:<20} {host['cpu_w']:<10.2f} {d_cpu:<+10.2f} {host['gpu_w']:<10.2f} "
              f"{host['iowait_pct']:<10.2f} {throughput:<15} {iops:<12}")

        results.append({
            'test': test_name,
            'label': label,
            'bs': bs,
            'cpu_w': host['cpu_w'],
            'gpu_w': host['gpu_w'],
            'd_cpu': d_cpu,
            'd_gpu': d_gpu,
            'iowait_pct': host['iowait_pct'],
            'throughput_mbs': throughput_val,
            'samples': host['samples'],
        })

    print("-" * 100)

    if not results:
        print("[ERROR] fio 데이터 없음")
        return

    # Storage 에너지 파라미터 계산
    print("\n" + "=" * 100)
    print("Storage Energy Parameters (Host sensor 기준, RPICT 보정 전)")
    print("  Storage_delta = dCPU (fio의 CPU 오버헤드)")
    print("  순수 Storage 전력은 RPICT(Wall) 기반으로 계산해야 정확")
    print("=" * 100)
    print(f"\n{'Test':<20} {'dCPU(W)':<12} {'Throughput':<15} {'CPU/Throughput':<18}")
    print("-" * 65)

    for r in results:
        if r['throughput_mbs'] > 0:
            per_tp = r['d_cpu'] / r['throughput_mbs']
            print(f"{r['label']:<20} {r['d_cpu']:<+12.2f} {r['throughput_mbs']:<15.0f} {per_tp:<18.4f} W/(MB/s)")
        else:
            print(f"{r['label']:<20} {r['d_cpu']:<+12.2f} {'N/A':<15} {'N/A':<18}")

    print("\n" + "=" * 100)
    print("RPICT Wall Power로 계산해야 할 값:")
    print("  Storage_power = Wall(fio) - Wall(idle) - dCPU(fio)")
    print("  → RPICT 데이터를 타임스탬프 기반으로 매칭 필요")
    print("=" * 100)

    # NVMe 데이터시트 참조값
    print("\n참조: Samsung 980 NVMe (데이터시트)")
    print("  Idle: ~30mW (PS3)")
    print("  Sequential Read (3,500 MB/s): ~3.5W")
    print("  Sequential Write (3,000 MB/s): ~3.9W")

    # 결과 CSV
    df = pd.DataFrame(results)
    outfile = OUTPUT_DIR / 'fio_results.csv'
    df.to_csv(outfile, index=False, float_format='%.3f')
    print(f"\n결과 저장: {outfile}")


if __name__ == "__main__":
    analyze()
