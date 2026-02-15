#!/usr/bin/env python3
"""
Phase 2.0: Component Isolation Analysis
4개 물리 config (A/B/C/D)로부터 Others 완전 분해

Config A: 2GPU + 2DIMM (32GB) — Full baseline
Config B: 2GPU + 1DIMM (16GB) — DIMM 1개 제거
Config C: 1GPU + 1DIMM (16GB) — GPU 1개 제거
Config D: 1GPU + 2DIMM (32GB) — DIMM 재장착

분리 결과:
  Memory_per_DIMM   = (A - B) cross-validated by (D - C)
  GPU_idle_per_card = (B - C) cross-validated by (A - D)
  Fixed_Others      = Wall - CPU - GPU_total - Memory - Storage_idle
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys

BASE = Path(__file__).parent.parent.parent
DATA_DIR = BASE / "data" / "raw" / "alienware" / "phase2.0_component"
RPICT_DIR = BASE / "data" / "raw" / "rpict"


def load_config(config: str, trim_pct: float = 10.0) -> dict:
    """특정 config의 3회 반복 데이터를 로드하고 평균 계산"""
    results = []

    for run in range(1, 4):
        host_file = DATA_DIR / f"config_{config}_run{run}_host.csv"
        if not host_file.exists():
            print(f"  [SKIP] {host_file.name} 없음")
            continue

        df = pd.read_csv(host_file, parse_dates=['timestamp'])

        # 앞뒤 trim (안정화 구간 제거)
        n = len(df)
        trim_n = int(n * trim_pct / 100)
        df = df.iloc[trim_n:n - trim_n] if trim_n > 0 and n > 2 * trim_n else df

        row = {
            'config': config,
            'run': run,
            'samples': len(df),
            'cpu_pct': df['cpu_pct'].mean(),
            'rapl_package_w': df['rapl_package_w'].mean(),
            'rapl_core_w': df['rapl_core_w'].mean(),
            'mem_used_pct': df['mem_used_pct'].mean(),
        }

        # GPU: 동적 컬럼 감지
        gpu_power_cols = [c for c in df.columns if c.startswith('gpu') and c.endswith('_power_w')]
        if 'gpu_power_w' in df.columns:
            row['gpu_total_w'] = df['gpu_power_w'].mean()
        else:
            row['gpu_total_w'] = sum(df[c].mean() for c in gpu_power_cols)

        for col in gpu_power_cols:
            if col != 'gpu_power_w':
                row[col] = df[col].mean()

        results.append(row)
        print(f"  Config {config} run{run}: RAPL={row['rapl_package_w']:.2f}W, GPU={row['gpu_total_w']:.2f}W, samples={len(df)}")

    if not results:
        return None

    # 3회 평균
    avg = {}
    for key in results[0]:
        if key in ('config', 'run'):
            continue
        vals = [r[key] for r in results if key in r]
        avg[key] = np.mean(vals)
        avg[f'{key}_std'] = np.std(vals)

    avg['config'] = config
    avg['n_runs'] = len(results)
    return avg


def load_rpict_for_config(config: str) -> float:
    """RPICT 데이터에서 해당 config의 평균 Wall power 추출"""
    # rpict_component_A.csv 등의 파일명 패턴
    patterns = [
        f"rpict_component_{config}.csv",
        f"*component*{config}*.csv",
        f"*config*{config}*.csv",
    ]

    for pattern in patterns:
        files = list(RPICT_DIR.glob(pattern))
        if files:
            df = pd.read_csv(files[0])
            # power1_w 또는 power_w 컬럼 찾기
            power_col = None
            for col in ['power1_w', 'power_w', 'watts']:
                if col in df.columns:
                    power_col = col
                    break
            if power_col:
                # 앞뒤 10% trim
                n = len(df)
                trim = int(n * 0.1)
                if trim > 0 and n > 2 * trim:
                    df = df.iloc[trim:n - trim]
                wall = df[power_col].mean()
                print(f"  RPICT Config {config}: {wall:.2f}W ({files[0].name})")
                return wall

    print(f"  [WARN] RPICT for Config {config} not found")
    return None


def analyze():
    print("=" * 60)
    print("Phase 2.0: Component Isolation Analysis")
    print("=" * 60)

    # 데이터 로드
    configs = {}
    for cfg in ['A', 'B', 'C', 'D', 'A_verify']:
        print(f"\n--- Config {cfg} ---")
        data = load_config(cfg)
        if data:
            data['wall_w'] = load_rpict_for_config(cfg)
            configs[cfg] = data

    available = list(configs.keys())
    print(f"\n사용 가능한 Config: {available}")

    if len(available) < 2:
        print("[ERROR] 최소 2개 Config 데이터가 필요합니다.")
        return

    # ── 결과 테이블 ──
    print("\n" + "=" * 60)
    print("측정 결과 요약")
    print("=" * 60)

    header = f"{'Config':<12} {'Wall(W)':<10} {'CPU(W)':<10} {'GPU(W)':<10} {'Others(W)':<10}"
    print(header)
    print("-" * 52)

    for cfg in ['A', 'B', 'C', 'D', 'A_verify']:
        if cfg not in configs:
            continue
        d = configs[cfg]
        wall = d.get('wall_w')
        cpu = d['rapl_package_w']
        gpu = d['gpu_total_w']
        others = wall - cpu - gpu if wall else None
        wall_str = f"{wall:.1f}" if wall else "N/A"
        others_str = f"{others:.1f}" if others else "N/A"
        print(f"{cfg:<12} {wall_str:<10} {cpu:<10.2f} {gpu:<10.2f} {others_str:<10}")

    # ── 컴포넌트 분리 ──
    print("\n" + "=" * 60)
    print("컴포넌트 분리 결과")
    print("=" * 60)

    # Memory per DIMM: A - B (primary), D - C (cross-validation)
    if 'A' in configs and 'B' in configs:
        a, b = configs['A'], configs['B']
        if a.get('wall_w') and b.get('wall_w'):
            mem_ab = a['wall_w'] - b['wall_w']
            # CPU/GPU 차이 보정
            cpu_diff = a['rapl_package_w'] - b['rapl_package_w']
            gpu_diff = a['gpu_total_w'] - b['gpu_total_w']
            mem_ab_corrected = mem_ab - cpu_diff - gpu_diff
            print(f"\n[Memory per DIMM]")
            print(f"  A - B (raw):       {mem_ab:+.2f}W")
            print(f"  CPU diff:          {cpu_diff:+.2f}W")
            print(f"  GPU diff:          {gpu_diff:+.2f}W")
            print(f"  A - B (corrected): {mem_ab_corrected:+.2f}W  <-- Memory_per_DIMM")

    if 'D' in configs and 'C' in configs:
        d_cfg, c = configs['D'], configs['C']
        if d_cfg.get('wall_w') and c.get('wall_w'):
            mem_dc = d_cfg['wall_w'] - c['wall_w']
            cpu_diff = d_cfg['rapl_package_w'] - c['rapl_package_w']
            gpu_diff = d_cfg['gpu_total_w'] - c['gpu_total_w']
            mem_dc_corrected = mem_dc - cpu_diff - gpu_diff
            print(f"  D - C (raw):       {mem_dc:+.2f}W")
            print(f"  D - C (corrected): {mem_dc_corrected:+.2f}W  <-- Cross-validation")

    # GPU idle per card: B - C (primary), A - D (cross-validation)
    if 'B' in configs and 'C' in configs:
        b, c = configs['B'], configs['C']
        if b.get('wall_w') and c.get('wall_w'):
            gpu_bc = b['wall_w'] - c['wall_w']
            cpu_diff = b['rapl_package_w'] - c['rapl_package_w']
            gpu_bc_corrected = gpu_bc - cpu_diff
            print(f"\n[GPU idle per card]")
            print(f"  B - C (raw):       {gpu_bc:+.2f}W")
            print(f"  CPU diff:          {cpu_diff:+.2f}W")
            print(f"  B - C (corrected): {gpu_bc_corrected:+.2f}W  <-- GPU_idle_per_card")

    if 'A' in configs and 'D' in configs:
        a, d_cfg = configs['A'], configs['D']
        if a.get('wall_w') and d_cfg.get('wall_w'):
            gpu_ad = a['wall_w'] - d_cfg['wall_w']
            cpu_diff = a['rapl_package_w'] - d_cfg['rapl_package_w']
            mem_diff = 0  # same DIMM count
            gpu_ad_corrected = gpu_ad - cpu_diff
            print(f"  A - D (raw):       {gpu_ad:+.2f}W")
            print(f"  A - D (corrected): {gpu_ad_corrected:+.2f}W  <-- Cross-validation")

    # Fixed Others: 최소 구성(C: 1GPU + 1DIMM)에서 계산
    if 'C' in configs and configs['C'].get('wall_w'):
        c = configs['C']
        wall_c = c['wall_w']
        cpu_c = c['rapl_package_w']
        gpu_c = c['gpu_total_w']
        fixed = wall_c - cpu_c - gpu_c
        print(f"\n[Fixed Others] (Config C: 최소 구성 1GPU+1DIMM)")
        print(f"  Wall:              {wall_c:.2f}W")
        print(f"  CPU (RAPL):       -{cpu_c:.2f}W")
        print(f"  GPU (nvidia-smi): -{gpu_c:.2f}W")
        print(f"  ─────────────────────────")
        print(f"  Residual:          {fixed:.2f}W")
        print(f"  (= 1 DIMM memory + Storage_idle + Chipset + VRM + Fan)")

    # ── 5-Component 모델 파라미터 ──
    print("\n" + "=" * 60)
    print("5-Component Attribution Model Parameters")
    print("=" * 60)
    print("  CPU:           RAPL package-0 (직접 측정)")
    print("  GPU:           nvidia-smi per-GPU power (직접 측정)")

    if 'A' in configs and 'B' in configs:
        if configs['A'].get('wall_w') and configs['B'].get('wall_w'):
            print(f"  Memory/DIMM:   ~{mem_ab_corrected:.1f}W per 16GB DIMM")

    if 'B' in configs and 'C' in configs:
        if configs['B'].get('wall_w') and configs['C'].get('wall_w'):
            print(f"  GPU idle/card:  ~{gpu_bc_corrected:.1f}W per RTX 3060")

    if 'C' in configs and configs['C'].get('wall_w'):
        print(f"  Fixed Others:   ~{fixed:.1f}W (chipset+VRM+fan+storage_idle)")

    # CSV 출력
    out_file = BASE / "reports" / "integrated" / "component_isolation_results.csv"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for cfg in ['A', 'B', 'C', 'D', 'A_verify']:
        if cfg in configs:
            d = configs[cfg]
            rows.append({
                'config': cfg,
                'wall_w': d.get('wall_w', ''),
                'rapl_package_w': d['rapl_package_w'],
                'gpu_total_w': d['gpu_total_w'],
                'cpu_pct': d['cpu_pct'],
                'mem_used_pct': d['mem_used_pct'],
                'n_runs': d['n_runs'],
            })

    if rows:
        pd.DataFrame(rows).to_csv(out_file, index=False)
        print(f"\n결과 저장: {out_file}")


if __name__ == '__main__':
    analyze()
