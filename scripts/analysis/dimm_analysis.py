#!/usr/bin/env python3
"""
Phase 2.0a: DIMM 실험 분석
32GB vs 16GB idle 전력 비교 → Memory_per_DIMM(W) 도출
"""

import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data/raw/alienware/phase2.0_dimm"
RPICT_DIR = BASE_DIR / "data/raw/rpict"
OUTPUT_DIR = BASE_DIR / "reports/phase2"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_host_runs(prefix):
    """prefix(32gb/16gb)의 반복 측정 결과 로드 + 평균"""
    runs = sorted(DATA_DIR.glob(f"{prefix}_run*_host.csv"))
    if not runs:
        print(f"[WARN] {prefix} 데이터 없음: {DATA_DIR}/{prefix}_run*_host.csv")
        return None

    all_means = []
    for run_file in runs:
        df = pd.read_csv(run_file)
        # 앞뒤 5행 트림 (안정화)
        df_trim = df.iloc[5:-5] if len(df) > 15 else df

        means = {
            'run': run_file.stem,
            'cpu_w': df_trim['rapl_package_w'].mean(),
            'gpu_w': df_trim['gpu_power_w'].mean(),
            'cpu_pct': df_trim['cpu_pct'].mean(),
            'gpu_util': df_trim['gpu_util_pct'].mean(),
            'mem_pct': df_trim['mem_used_pct'].mean(),
            'samples': len(df_trim),
        }

        # CPU frequency (있으면)
        freq_cols = [c for c in df_trim.columns if c.endswith('_mhz')]
        if freq_cols:
            means['avg_freq_mhz'] = df_trim[freq_cols].mean().mean()

        all_means.append(means)
        print(f"  {run_file.name}: CPU={means['cpu_w']:.2f}W, GPU={means['gpu_w']:.2f}W ({means['samples']} samples)")

    return pd.DataFrame(all_means)


def analyze():
    print("=" * 80)
    print("Phase 2.0a: DIMM Experiment Analysis")
    print("=" * 80)

    # 32GB 데이터
    print("\n[32GB Runs]")
    df_32 = load_host_runs("32gb")

    # 16GB 데이터
    print("\n[16GB Runs]")
    df_16 = load_host_runs("16gb")

    # 검증용 (선택)
    print("\n[32GB Verify Runs]")
    df_32v = load_host_runs("32gb_verify")

    if df_32 is None or df_16 is None:
        print("\n[ERROR] 32gb와 16gb 데이터가 모두 필요합니다.")
        print("  sudo -E ./run_dimm_experiment.sh 32gb")
        print("  (BIOS DIMM 비활성화)")
        print("  sudo -E ./run_dimm_experiment.sh 16gb")
        return

    # 평균값 계산
    avg_32 = df_32[['cpu_w', 'gpu_w']].mean()
    avg_16 = df_16[['cpu_w', 'gpu_w']].mean()

    print("\n" + "=" * 80)
    print("Results (Host Sensor 기준 - RPICT 없이)")
    print("=" * 80)
    print(f"{'Config':<15} {'CPU(W)':<12} {'GPU(W)':<12} {'CPU+GPU(W)':<12}")
    print("-" * 55)
    print(f"{'32GB (2 DIMM)':<15} {avg_32['cpu_w']:<12.2f} {avg_32['gpu_w']:<12.2f} {avg_32['cpu_w']+avg_32['gpu_w']:<12.2f}")
    print(f"{'16GB (1 DIMM)':<15} {avg_16['cpu_w']:<12.2f} {avg_16['gpu_w']:<12.2f} {avg_16['cpu_w']+avg_16['gpu_w']:<12.2f}")

    # CPU/GPU 차이 (이상적으로 0에 가까워야)
    d_cpu = avg_32['cpu_w'] - avg_16['cpu_w']
    d_gpu = avg_32['gpu_w'] - avg_16['gpu_w']
    print(f"\n{'Delta':<15} {d_cpu:<+12.2f} {d_gpu:<+12.2f}")

    if abs(d_cpu) > 1.0 or abs(d_gpu) > 1.0:
        print("[WARN] CPU 또는 GPU 전력 차이가 1W 이상 → 실험 조건 동일하지 않을 수 있음")

    print("\n" + "=" * 80)
    print("RPICT Wall Power 비교 (이 값이 핵심)")
    print("=" * 80)
    print("  RPICT 데이터를 별도로 매칭해야 합니다.")
    print("  → 타임스탬프 기반으로 매칭하거나")
    print("  → 실험 시간대의 RPICT 평균을 직접 계산하세요.")
    print()
    print("  Memory_per_DIMM = Wall(32GB) - Wall(16GB)")
    print("  Memory_per_GB   = Memory_per_DIMM / 16")
    print()
    print("  예상: DDR4 DIMM idle = 1~2W/DIMM → 총 차이 1~2W")

    # 재현성 검증
    if df_32v is not None:
        avg_32v = df_32v[['cpu_w', 'gpu_w']].mean()
        print("\n" + "=" * 80)
        print("재현성 검증 (32GB → 16GB → 32GB)")
        print("=" * 80)
        print(f"  32GB (initial): CPU={avg_32['cpu_w']:.2f}W, GPU={avg_32['gpu_w']:.2f}W")
        print(f"  16GB          : CPU={avg_16['cpu_w']:.2f}W, GPU={avg_16['gpu_w']:.2f}W")
        print(f"  32GB (verify) : CPU={avg_32v['cpu_w']:.2f}W, GPU={avg_32v['gpu_w']:.2f}W")
        d_repro = abs(avg_32['cpu_w'] - avg_32v['cpu_w'])
        print(f"  재현성 오차 (CPU): {d_repro:.3f}W {'OK' if d_repro < 0.5 else 'WARN'}")

    # 결과 CSV 저장
    results = {
        'config': ['32GB', '16GB'],
        'cpu_w': [avg_32['cpu_w'], avg_16['cpu_w']],
        'gpu_w': [avg_32['gpu_w'], avg_16['gpu_w']],
    }
    if df_32v is not None:
        results['config'].append('32GB_verify')
        results['cpu_w'].append(avg_32v['cpu_w'])
        results['gpu_w'].append(avg_32v['gpu_w'])

    pd.DataFrame(results).to_csv(OUTPUT_DIR / 'dimm_results.csv', index=False, float_format='%.3f')
    print(f"\n결과 저장: {OUTPUT_DIR / 'dimm_results.csv'}")


if __name__ == "__main__":
    analyze()
