#!/usr/bin/env python3
"""
Phase 2.1: fio Storage 에너지 분석 (v2 - 교수님 피드백 반영)

핵심 공식:
  Storage_power = Wall(RPICT) - Wall_idle(RPICT) - dCPU(RAPL) - dGPU(nvidia-smi)
  Storage_rate  = Storage_power / Throughput(MB/s)   [W per MB/s]

이전 v1의 문제: delta 전체(~46W)를 storage로 귀속 → 대부분 CPU였음
v2: CPU/GPU delta를 명시적으로 분리
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
# 새 데이터가 phase2.1_fio에 있으면 사용, 없으면 phase2.0_fio fallback
DATA_DIR_V2 = BASE_DIR / "data/raw/alienware/phase2.1_fio"
DATA_DIR_V1 = BASE_DIR / "data/raw/alienware/phase2.0_fio"
RPICT_DIR = BASE_DIR / "data/raw/rpict"

TRIM_PCT = 10.0  # 앞뒤 10% 트림


def get_data_dir():
    if DATA_DIR_V2.exists() and any(DATA_DIR_V2.glob("*_host.csv")):
        return DATA_DIR_V2
    return DATA_DIR_V1


def load_host(name, data_dir):
    """host CSV 로드 + 트림 + 평균"""
    f = data_dir / f"{name}_host.csv"
    if not f.exists():
        return None

    df = pd.read_csv(f)
    n = len(df)
    trim = int(n * TRIM_PCT / 100)
    if trim > 0 and n > 2 * trim:
        df = df.iloc[trim:n-trim]

    result = {
        'rapl_pkg_w': df['rapl_package_w'].mean(),
        'rapl_core_w': df['rapl_core_w'].mean(),
        'gpu_total_w': df['gpu_power_w'].mean(),
        'cpu_pct': df['cpu_pct'].mean(),
        'iowait_pct': df['iowait_pct'].mean(),
        'io_read_kbs': df['io_read_kbs'].mean(),
        'io_write_kbs': df['io_write_kbs'].mean(),
        'samples': len(df),
    }

    # Per-GPU power
    gpu_cols = [c for c in df.columns if c.startswith('gpu') and c.endswith('_power_w') and c != 'gpu_power_w']
    for col in gpu_cols:
        result[col] = df[col].mean()

    # CPU frequency
    freq_cols = [c for c in df.columns if c.endswith('_mhz')]
    if freq_cols:
        result['avg_freq_mhz'] = df[freq_cols].mean().mean()

    return result


def load_fio_json(name, data_dir):
    """fio JSON 결과 파싱"""
    f = data_dir / f"{name}_fio.json"
    if not f.exists():
        return None

    with open(f) as fp:
        data = json.load(fp)

    job = data['jobs'][0]
    result = {}

    if job['read']['io_bytes'] > 0:
        result['read_bw_mbs'] = job['read']['bw'] / 1024
        result['read_iops'] = job['read']['iops']
        result['read_io_gb'] = job['read']['io_bytes'] / (1024**3)
        result['sys_cpu_pct'] = job.get('sys_cpu', 0)

    if job['write']['io_bytes'] > 0:
        result['write_bw_mbs'] = job['write']['bw'] / 1024
        result['write_iops'] = job['write']['iops']
        result['write_io_gb'] = job['write']['io_bytes'] / (1024**3)
        result['sys_cpu_pct'] = job.get('sys_cpu', 0)

    return result


def load_rpict(keyword):
    """RPICT wall power 로드 (fio 관련 파일 검색)"""
    # 패턴들을 시도
    patterns = [
        f"rpict*fio*v2*.csv",
        f"rpict*fio*.csv",
        f"*fio*rpict*.csv",
    ]
    for pat in patterns:
        files = sorted(RPICT_DIR.glob(pat), key=lambda f: f.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    return None


def analyze():
    data_dir = get_data_dir()
    print("=" * 90)
    print("Phase 2.1: fio Storage Energy Analysis (v2)")
    print(f"Data: {data_dir}")
    print("=" * 90)

    # ── Idle Baseline ──
    idle = load_host("idle_baseline", data_dir)
    if idle is None:
        print("[ERROR] idle_baseline_host.csv not found")
        return

    print(f"\n{'='*90}")
    print("1. Idle Baseline (Config A: 2GPU+2DIMM)")
    print(f"{'='*90}")
    print(f"  RAPL package:  {idle['rapl_pkg_w']:.2f}W")
    print(f"  GPU total:     {idle['gpu_total_w']:.2f}W")
    gpu_cols = [k for k in idle if k.startswith('gpu') and k.endswith('_power_w')]
    for col in sorted(gpu_cols):
        print(f"    {col}: {idle[col]:.2f}W")
    print(f"  CPU%:          {idle['cpu_pct']:.2f}%")
    print(f"  IO wait%:      {idle['iowait_pct']:.2f}%")
    print(f"  Avg freq:      {idle.get('avg_freq_mhz', 0):.0f}MHz")

    # ── fio Tests ──
    tests = [
        ('seq_read',  'Sequential Read'),
        ('seq_write', 'Sequential Write'),
    ]

    print(f"\n{'='*90}")
    print("2. fio Test Results (Host Sensor)")
    print(f"{'='*90}")

    results = []

    for test_name, label in tests:
        host = load_host(test_name, data_dir)
        fio = load_fio_json(test_name, data_dir)

        if host is None:
            print(f"\n  [{label}] - no data")
            continue

        d_cpu = host['rapl_pkg_w'] - idle['rapl_pkg_w']
        d_gpu = host['gpu_total_w'] - idle['gpu_total_w']

        throughput = 0
        if fio:
            throughput = fio.get('read_bw_mbs', 0) or fio.get('write_bw_mbs', 0)

        print(f"\n  [{label}]")
        print(f"    RAPL package:  {host['rapl_pkg_w']:.2f}W  (delta: {d_cpu:+.2f}W)")
        print(f"    GPU total:     {host['gpu_total_w']:.2f}W  (delta: {d_gpu:+.2f}W)")
        for col in sorted(gpu_cols):
            if col in host:
                print(f"      {col}: {host[col]:.2f}W")
        print(f"    CPU%:          {host['cpu_pct']:.1f}%")
        print(f"    IO wait%:      {host['iowait_pct']:.1f}%")
        print(f"    Avg freq:      {host.get('avg_freq_mhz', 0):.0f}MHz")
        if fio:
            print(f"    Throughput:    {throughput:.0f} MB/s")
            iops = fio.get('read_iops', 0) or fio.get('write_iops', 0)
            print(f"    IOPS:          {iops:.0f}")
            print(f"    fio sys_cpu:   {fio.get('sys_cpu_pct', 0):.1f}%")

        results.append({
            'test': test_name,
            'label': label,
            'd_cpu': d_cpu,
            'd_gpu': d_gpu,
            'throughput_mbs': throughput,
            'cpu_w': host['rapl_pkg_w'],
            'gpu_w': host['gpu_total_w'],
            'iowait_pct': host['iowait_pct'],
        })

    # ── 핵심: Storage 전력 분리 ──
    print(f"\n{'='*90}")
    print("3. Storage Power Isolation (핵심)")
    print("   Formula: Storage_power = Wall_delta - dCPU(RAPL) - dGPU(nvidia-smi)")
    print(f"{'='*90}")

    # RPICT 데이터 있는지 확인
    rpict_file = load_rpict("fio")
    rpict_available = False
    rpict_idle_wall = None
    rpict_fio_walls = {}

    if rpict_file:
        print(f"\n  RPICT file found: {rpict_file.name}")
        rpict_df = pd.read_csv(rpict_file)
        print(f"  Total samples: {len(rpict_df)}, duration: ~{len(rpict_df)*3:.0f}s")
        rpict_available = True
        # RPICT는 수동으로 구간을 지정해야 할 수 있음
        print(f"  (RPICT 데이터가 있으면 아래 추정값 대신 실측값 사용 가능)")
    else:
        print(f"\n  [WARN] RPICT fio 데이터 없음 → Phase 2.0 component 기준 idle wall 사용")

    # Phase 2.0 component Config A 의 idle wall power 사용
    comp_rpict = list(RPICT_DIR.glob("rpict_component_A-phase2.csv"))
    if comp_rpict:
        comp_df = pd.read_csv(comp_rpict[0])
        n = len(comp_df)
        trim = int(n * TRIM_PCT / 100)
        if trim > 0:
            comp_df = comp_df.iloc[trim:n-trim]
        config_a_wall = comp_df['power1_w'].mean()
        print(f"\n  Config A idle wall (RPICT): {config_a_wall:.2f}W")
    else:
        config_a_wall = 44.49  # fallback
        print(f"\n  Config A idle wall (fallback): {config_a_wall:.2f}W")

    print(f"\n  {'Test':<20} {'dCPU':<10} {'dGPU':<10} {'dWall*':<12} {'Stor_pwr':<12} {'Throughput':<12} {'Rate':<15}")
    print(f"  {'':<20} {'(RAPL)':<10} {'(smi)':<10} {'(est.)':<12} {'(est.)':<12} {'(MB/s)':<12} {'(W per MB/s)':<15}")
    print(f"  {'-'*85}")

    for r in results:
        if r['throughput_mbs'] <= 0:
            continue

        # Wall delta 추정:
        # PSU 효율 고려: wall 측에서 CPU가 dCPU만큼 더 소비하면,
        # wall에서는 dCPU / PSU_eff 만큼 증가
        # Config A idle에서 PSU 효율 ~75% (1000W PSU at 4.4% load)
        psu_eff = 0.75

        # 역산: fio 시 wall power = idle_wall + (dCPU + dGPU + dStorage) / psu_eff
        # 하지만 RPICT가 없으면 wall_fio를 모름
        # → RPICT 데이터가 있을 때만 정확한 계산 가능

        # RPICT가 없는 경우: v1 데이터에서 대략 추정
        # seq_read 시 wall ~88W (이전 RPICT 데이터 기준)
        # 여기서는 placeholder로 계산 구조만 보여줌

        # 추정: 이전 RPICT 데이터 사용
        est_wall_delta = "RPICT 필요"
        est_storage = "RPICT 필요"
        est_rate = "RPICT 필요"

        print(f"  {r['label']:<20} {r['d_cpu']:<+10.2f} {r['d_gpu']:<+10.2f} "
              f"{est_wall_delta:<12} {est_storage:<12} "
              f"{r['throughput_mbs']:<12.0f} {est_rate:<15}")

    # ── 계산 방법 가이드 ──
    print(f"\n{'='*90}")
    print("4. RPICT 데이터 수집 후 계산 방법")
    print(f"{'='*90}")
    print("""
  RPICT를 fio 실험과 동시에 수집한 후:

  1) RPICT에서 idle 구간과 fio 구간의 wall power 평균 추출
     Wall_idle = RPICT idle 구간 평균 (≈ Config A idle = {:.1f}W)
     Wall_fio  = RPICT fio 구간 평균

  2) Host 센서에서 delta 추출
     dCPU = RAPL(fio) - RAPL(idle)
     dGPU = nvidia-smi(fio) - nvidia-smi(idle)

  3) 순수 Storage 전력 = Wall_delta - dCPU/PSU_eff - dGPU/PSU_eff
     (PSU 효율 보정: DC측 delta가 wall에서는 1/eff 배로 나타남)

     또는 단순화:
     Storage_wall = Wall_fio - Wall_idle - dCPU - dGPU
     (PSU 효율이 선형이라 가정하면, 각 delta가 wall에 동일 비율로 반영)

  4) Storage_rate = Storage_wall / Throughput(MB/s)
     → 이 값을 실제 워크로드의 IO량에 곱하면 워크로드별 Storage 에너지

  참조: Samsung 980 NVMe 데이터시트
    Idle: ~30mW (PS3)
    Sequential Read (3,500 MB/s): ~3.5W
    Sequential Write (3,000 MB/s): ~3.9W
""".format(config_a_wall))

    # ── 이전 v1 데이터 역분석 (참고용) ──
    print(f"{'='*90}")
    print("5. 이전 v1 실험 역분석 (참고용)")
    print(f"{'='*90}")

    v1_rpict = list(RPICT_DIR.glob("260210-fio-test-v1.csv"))
    v1_data_dir = DATA_DIR_V1

    if v1_rpict and v1_data_dir.exists():
        v1_idle = load_host("idle_baseline", v1_data_dir)
        v1_read = load_host("seq_read", v1_data_dir)
        v1_read_fio = load_fio_json("seq_read", v1_data_dir)
        v1_write = load_host("seq_write", v1_data_dir)
        v1_write_fio = load_fio_json("seq_write", v1_data_dir)

        # v1 RPICT
        rpict_v1 = pd.read_csv(v1_rpict[0])
        n = len(rpict_v1)
        trim = int(n * TRIM_PCT / 100)
        if trim > 0:
            rpict_v1 = rpict_v1.iloc[trim:n-trim]

        print(f"\n  v1 RPICT: {v1_rpict[0].name}")
        print(f"  Samples: {len(rpict_v1)}, mean wall: {rpict_v1['power1_w'].mean():.1f}W")

        if v1_idle and v1_read:
            d_cpu_read = v1_read['rapl_pkg_w'] - v1_idle['rapl_pkg_w']
            d_gpu_read = v1_read['gpu_total_w'] - v1_idle['gpu_total_w']

            # v1은 1GPU config에서 했으므로 idle wall ≈ 31-33W
            # RPICT에서 fio 시 ~88W 정도였음 (이전 분석 참고)
            print(f"\n  [seq_read v1]")
            print(f"    Idle: RAPL={v1_idle['rapl_pkg_w']:.2f}W, GPU={v1_idle['gpu_total_w']:.2f}W")
            print(f"    fio:  RAPL={v1_read['rapl_pkg_w']:.2f}W, GPU={v1_read['gpu_total_w']:.2f}W")
            print(f"    dCPU={d_cpu_read:+.2f}W, dGPU={d_gpu_read:+.2f}W")
            if v1_read_fio:
                tp = v1_read_fio.get('read_bw_mbs', 0)
                print(f"    Throughput: {tp:.0f} MB/s")
                print(f"    → 순수 Storage = Wall_delta - {d_cpu_read:.1f}W(CPU) - {d_gpu_read:.1f}W(GPU)")
                print(f"    → RPICT가 있어야 Wall_delta 계산 가능")

        if v1_idle and v1_write:
            d_cpu_write = v1_write['rapl_pkg_w'] - v1_idle['rapl_pkg_w']
            d_gpu_write = v1_write['gpu_total_w'] - v1_idle['gpu_total_w']
            print(f"\n  [seq_write v1]")
            print(f"    Idle: RAPL={v1_idle['rapl_pkg_w']:.2f}W, GPU={v1_idle['gpu_total_w']:.2f}W")
            print(f"    fio:  RAPL={v1_write['rapl_pkg_w']:.2f}W, GPU={v1_write['gpu_total_w']:.2f}W")
            print(f"    dCPU={d_cpu_write:+.2f}W, dGPU={d_gpu_write:+.2f}W")
            if v1_write_fio:
                tp = v1_write_fio.get('write_bw_mbs', 0)
                print(f"    Throughput: {tp:.0f} MB/s")
    else:
        print("  v1 데이터 없음")

    print(f"\n{'='*90}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*90}")


if __name__ == "__main__":
    analyze()
