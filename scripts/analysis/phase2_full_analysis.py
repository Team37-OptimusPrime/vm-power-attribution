#!/usr/bin/env python3
"""
Phase 2.0 Component Isolation - Full Analysis
4 configs (A/B/C/D) cross-validated decomposition
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent.parent.parent
DATA_DIR = BASE / "data" / "raw" / "alienware" / "phase2.0_component"
RPICT_DIR = BASE / "data" / "raw" / "rpict"

TRIM_PCT = 10.0  # trim 10% from each end

def load_host(config: str) -> list:
    """Load 3 runs for a config, return list of per-run mean dicts"""
    results = []
    for run in range(1, 4):
        f = DATA_DIR / f"config_{config}_run{run}_host.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f)
        n = len(df)
        trim = int(n * TRIM_PCT / 100)
        if trim > 0 and n > 2 * trim:
            df = df.iloc[trim:n-trim]

        row = {
            'config': config, 'run': run, 'samples': len(df),
            'cpu_pct': df['cpu_pct'].mean(),
            'rapl_package_w': df['rapl_package_w'].mean(),
            'rapl_core_w': df['rapl_core_w'].mean(),
            'rapl_dram_w': df['rapl_dram_w'].mean(),
            'mem_used_pct': df['mem_used_pct'].mean(),
        }

        # GPU power
        if 'gpu_power_w' in df.columns:
            row['gpu_total_w'] = df['gpu_power_w'].mean()

        # Per-GPU details
        gpu_cols = [c for c in df.columns if c.startswith('gpu') and c.endswith('_power_w') and c != 'gpu_power_w']
        for col in gpu_cols:
            row[col] = df[col].mean()

        # Per-GPU temps
        temp_cols = [c for c in df.columns if c.startswith('gpu') and c.endswith('_temp_c')]
        for col in temp_cols:
            row[col] = df[col].mean()

        # IO
        if 'io_read_kbs' in df.columns:
            row['io_read_kbs'] = df['io_read_kbs'].mean()
            row['io_write_kbs'] = df['io_write_kbs'].mean()

        # CPU freq (average across all cores)
        freq_cols = [c for c in df.columns if c.endswith('_mhz')]
        if freq_cols:
            row['avg_cpu_mhz'] = df[freq_cols].mean().mean()
            row['cpu0_mhz'] = df['cpu0_mhz'].mean() if 'cpu0_mhz' in df.columns else 0

        results.append(row)
    return results


def load_rpict(config: str) -> dict:
    """Load RPICT wall power for a config"""
    pattern = f"rpict_component_{config}-phase2.csv"
    files = list(RPICT_DIR.glob(pattern))
    if not files:
        # try other patterns
        for p in [f"rpict_component_{config}.csv", f"*component*{config}*.csv"]:
            files = list(RPICT_DIR.glob(p))
            if files:
                break

    if not files:
        return None

    df = pd.read_csv(files[0])
    n = len(df)
    trim = int(n * TRIM_PCT / 100)
    if trim > 0 and n > 2 * trim:
        df = df.iloc[trim:n-trim]

    power_col = None
    for col in ['power1_w', 'power_w', 'watts']:
        if col in df.columns:
            power_col = col
            break

    if power_col is None:
        return None

    return {
        'wall_mean': df[power_col].mean(),
        'wall_std': df[power_col].std(),
        'wall_median': df[power_col].median(),
        'samples': len(df),
        'file': files[0].name,
    }


def main():
    print("=" * 70)
    print("Phase 2.0: Component Isolation - Full Analysis")
    print("=" * 70)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 1. Data Loading
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    configs = {}
    for cfg in ['A', 'B', 'C', 'D']:
        runs = load_host(cfg)
        if not runs:
            print(f"[ERROR] Config {cfg}: no data")
            continue

        # Average across runs
        avg = {}
        numeric_keys = [k for k in runs[0] if k not in ('config', 'run')]
        for key in numeric_keys:
            vals = [r[key] for r in runs if key in r]
            avg[key] = np.mean(vals)
            avg[f'{key}_std'] = np.std(vals)

        avg['config'] = cfg
        avg['n_runs'] = len(runs)
        avg['runs'] = runs

        # RPICT
        rpict = load_rpict(cfg)
        if rpict:
            avg['wall_w'] = rpict['wall_mean']
            avg['wall_std'] = rpict['wall_std']
            avg['wall_samples'] = rpict['samples']

        configs[cfg] = avg

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 2. Hardware Verification
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 70)
    print("1. Hardware Configuration Verification")
    print("=" * 70)

    expected = {
        'A': {'gpu': 2, 'dimm': 2, 'ram_gb': 32, 'desc': '2GPU+2DIMM(32GB)'},
        'B': {'gpu': 2, 'dimm': 1, 'ram_gb': 16, 'desc': '2GPU+1DIMM(16GB)'},
        'C': {'gpu': 1, 'dimm': 1, 'ram_gb': 16, 'desc': '1GPU+1DIMM(16GB)'},
        'D': {'gpu': 1, 'dimm': 2, 'ram_gb': 32, 'desc': '1GPU+2DIMM(32GB)'},
    }

    for cfg in ['A', 'B', 'C', 'D']:
        if cfg not in configs:
            continue
        d = configs[cfg]
        exp = expected[cfg]
        # Check GPU count from per-gpu columns
        gpu_cols = [k for k in d if k.startswith('gpu') and k.endswith('_power_w') and k != 'gpu_total_w']
        n_gpus = len(gpu_cols)
        print(f"  Config {cfg} ({exp['desc']}): {n_gpus} GPU detected, "
              f"RAPL_DRAM={d.get('rapl_dram_w', 0):.3f}W, "
              f"CPU_avg={d.get('avg_cpu_mhz', 0):.0f}MHz")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 3. Per-Config Summary
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 70)
    print("2. Per-Config Measurement Summary")
    print("=" * 70)

    print(f"\n{'Config':<8} {'Wall(W)':<12} {'CPU/RAPL(W)':<14} {'GPU_total(W)':<14} "
          f"{'RAPL_DRAM(W)':<14} {'CPU%':<8} {'Others(W)':<12}")
    print("-" * 82)

    for cfg in ['A', 'B', 'C', 'D']:
        if cfg not in configs:
            continue
        d = configs[cfg]
        wall = d.get('wall_w', None)
        cpu = d['rapl_package_w']
        gpu = d['gpu_total_w']
        dram = d.get('rapl_dram_w', 0)
        cpu_pct = d['cpu_pct']

        if wall:
            others = wall - cpu - gpu
            print(f"{cfg:<8} {wall:<12.2f} {cpu:<14.2f} {gpu:<14.2f} {dram:<14.3f} {cpu_pct:<8.1f} {others:<12.2f}")
        else:
            print(f"{cfg:<8} {'N/A':<12} {cpu:<14.2f} {gpu:<14.2f} {dram:<14.3f} {cpu_pct:<8.1f} {'N/A':<12}")

    # Per-run detail
    print("\n--- Per-Run Detail ---")
    for cfg in ['A', 'B', 'C', 'D']:
        if cfg not in configs:
            continue
        print(f"\n  Config {cfg}:")
        for r in configs[cfg]['runs']:
            gpu_detail = ""
            if 'gpu0_power_w' in r:
                gpu_detail += f"GPU0={r['gpu0_power_w']:.2f}W"
            if 'gpu1_power_w' in r:
                gpu_detail += f" GPU1={r['gpu1_power_w']:.2f}W"
            print(f"    Run{r['run']}: RAPL={r['rapl_package_w']:.2f}W, "
                  f"GPU_total={r['gpu_total_w']:.2f}W ({gpu_detail}), "
                  f"DRAM={r['rapl_dram_w']:.3f}W, CPU%={r['cpu_pct']:.1f}%, "
                  f"samples={r['samples']}")

    # RPICT detail
    print("\n--- RPICT Wall Power Detail ---")
    for cfg in ['A', 'B', 'C', 'D']:
        rpict = load_rpict(cfg)
        if rpict:
            print(f"  Config {cfg}: mean={rpict['wall_mean']:.2f}W, "
                  f"std={rpict['wall_std']:.2f}W, "
                  f"median={rpict['wall_median']:.2f}W, "
                  f"samples={rpict['samples']}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 4. Component Isolation (Cross-Validated)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 70)
    print("3. Component Isolation (Cross-Validated)")
    print("=" * 70)

    A = configs.get('A', {})
    B = configs.get('B', {})
    C = configs.get('C', {})
    D = configs.get('D', {})

    # ── Memory per DIMM ──
    print("\n--- 3a. Memory per DIMM ---")
    mem_estimates = []

    if A.get('wall_w') and B.get('wall_w'):
        raw_ab = A['wall_w'] - B['wall_w']
        cpu_diff_ab = A['rapl_package_w'] - B['rapl_package_w']
        gpu_diff_ab = A['gpu_total_w'] - B['gpu_total_w']
        mem_ab = raw_ab - cpu_diff_ab - gpu_diff_ab
        mem_estimates.append(mem_ab)
        print(f"  [Primary] A - B:")
        print(f"    Wall diff (raw):   {raw_ab:+.2f}W")
        print(f"    CPU diff (RAPL):   {cpu_diff_ab:+.2f}W")
        print(f"    GPU diff:          {gpu_diff_ab:+.2f}W")
        print(f"    Memory/DIMM:       {mem_ab:+.2f}W")

    if D.get('wall_w') and C.get('wall_w'):
        raw_dc = D['wall_w'] - C['wall_w']
        cpu_diff_dc = D['rapl_package_w'] - C['rapl_package_w']
        gpu_diff_dc = D['gpu_total_w'] - C['gpu_total_w']
        mem_dc = raw_dc - cpu_diff_dc - gpu_diff_dc
        mem_estimates.append(mem_dc)
        print(f"  [Cross-val] D - C:")
        print(f"    Wall diff (raw):   {raw_dc:+.2f}W")
        print(f"    CPU diff (RAPL):   {cpu_diff_dc:+.2f}W")
        print(f"    GPU diff:          {gpu_diff_dc:+.2f}W")
        print(f"    Memory/DIMM:       {mem_dc:+.2f}W")

    if len(mem_estimates) == 2:
        mem_avg = np.mean(mem_estimates)
        mem_diff = abs(mem_estimates[0] - mem_estimates[1])
        print(f"\n  ** Cross-validation: |A-B| vs |D-C| difference = {mem_diff:.2f}W")
        print(f"  ** Best estimate Memory/DIMM = {mem_avg:.2f}W")
    elif len(mem_estimates) == 1:
        mem_avg = mem_estimates[0]
        print(f"\n  ** Memory/DIMM estimate = {mem_avg:.2f}W (single estimate)")

    # ── GPU idle per card ──
    print("\n--- 3b. GPU idle per card ---")
    gpu_estimates = []

    if B.get('wall_w') and C.get('wall_w'):
        raw_bc = B['wall_w'] - C['wall_w']
        cpu_diff_bc = B['rapl_package_w'] - C['rapl_package_w']
        gpu_diff_bc = B['gpu_total_w'] - C['gpu_total_w']  # nvidia-smi already measures this
        # GPU idle = raw wall diff - CPU diff
        # Note: nvidia-smi measures GPU power directly, so we also correct for that
        gpu_bc_raw = raw_bc - cpu_diff_bc
        gpu_bc_from_smi = gpu_diff_bc
        gpu_estimates.append(gpu_bc_raw)
        print(f"  [Primary] B - C:")
        print(f"    Wall diff (raw):        {raw_bc:+.2f}W")
        print(f"    CPU diff (RAPL):        {cpu_diff_bc:+.2f}W")
        print(f"    GPU idle (wall-based):  {gpu_bc_raw:+.2f}W  (wall - cpu_diff)")
        print(f"    GPU diff (nvidia-smi):  {gpu_diff_bc:+.2f}W  (direct measurement)")
        print(f"    Hidden GPU overhead:    {gpu_bc_raw - gpu_diff_bc:+.2f}W  (PCIe + VRM for GPU)")

    if A.get('wall_w') and D.get('wall_w'):
        raw_ad = A['wall_w'] - D['wall_w']
        cpu_diff_ad = A['rapl_package_w'] - D['rapl_package_w']
        gpu_diff_ad = A['gpu_total_w'] - D['gpu_total_w']
        gpu_ad_raw = raw_ad - cpu_diff_ad
        gpu_estimates.append(gpu_ad_raw)
        print(f"  [Cross-val] A - D:")
        print(f"    Wall diff (raw):        {raw_ad:+.2f}W")
        print(f"    CPU diff (RAPL):        {cpu_diff_ad:+.2f}W")
        print(f"    GPU idle (wall-based):  {gpu_ad_raw:+.2f}W  (wall - cpu_diff)")
        print(f"    GPU diff (nvidia-smi):  {gpu_diff_ad:+.2f}W  (direct measurement)")
        print(f"    Hidden GPU overhead:    {gpu_ad_raw - gpu_diff_ad:+.2f}W  (PCIe + VRM for GPU)")

    if len(gpu_estimates) == 2:
        gpu_avg = np.mean(gpu_estimates)
        gpu_diff_cv = abs(gpu_estimates[0] - gpu_estimates[1])
        print(f"\n  ** Cross-validation: |B-C| vs |A-D| difference = {gpu_diff_cv:.2f}W")
        print(f"  ** Best estimate GPU_idle_total_wall = {gpu_avg:.2f}W per card")

    # ── Fixed Others ──
    print("\n--- 3c. Fixed Others (Minimum Config C: 1GPU+1DIMM) ---")
    if C.get('wall_w'):
        wall_c = C['wall_w']
        cpu_c = C['rapl_package_w']
        gpu_c = C['gpu_total_w']
        residual_c = wall_c - cpu_c - gpu_c
        print(f"  Wall power:            {wall_c:.2f}W")
        print(f"  CPU (RAPL package):   -{cpu_c:.2f}W")
        print(f"  GPU (nvidia-smi):     -{gpu_c:.2f}W")
        print(f"  ─────────────────────────")
        print(f"  Residual:              {residual_c:.2f}W")
        print(f"  = 1 DIMM idle + Storage idle + Chipset + VRM_loss + Fan + PSU_loss")

        if mem_estimates:
            # Subtract 1 DIMM
            fixed_core = residual_c - mem_avg
            print(f"\n  After removing 1 DIMM ({mem_avg:.2f}W):")
            print(f"  Pure Fixed Others:     {fixed_core:.2f}W")
            print(f"  = Storage_idle + Chipset + VRM_loss + Fan + PSU_loss")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 5. RAPL DRAM Analysis
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 70)
    print("4. RAPL DRAM Analysis")
    print("=" * 70)

    for cfg in ['A', 'B', 'C', 'D']:
        if cfg not in configs:
            continue
        d = configs[cfg]
        print(f"  Config {cfg}: RAPL_DRAM = {d.get('rapl_dram_w', 0):.4f}W "
              f"(std={d.get('rapl_dram_w_std', 0):.4f})")

    if mem_estimates:
        print(f"\n  Physical isolation says: Memory/DIMM = {mem_avg:.2f}W")
        print(f"  RAPL DRAM reports:      ~{configs.get('A', {}).get('rapl_dram_w', 0):.4f}W")
        rapl_dram_val = configs.get('A', {}).get('rapl_dram_w', 0)
        if rapl_dram_val < 0.1:
            print(f"  --> RAPL DRAM is essentially ZERO on this platform!")
            print(f"  --> i7-11700KF does NOT report memory power via RAPL")
            print(f"  --> Physical isolation is the ONLY way to measure memory power")
        else:
            print(f"  --> RAPL DRAM shows some reading, compare with physical result")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 6. Superposition Verification
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 70)
    print("5. Superposition Verification")
    print("=" * 70)

    if all(cfg in configs and configs[cfg].get('wall_w') for cfg in ['A', 'B', 'C', 'D']):
        wall_a = A['wall_w']
        wall_b = B['wall_w']
        wall_c = C['wall_w']
        wall_d = D['wall_w']

        # A = C + 1 GPU_idle + 1 DIMM
        if gpu_estimates and mem_estimates:
            predicted_a = wall_c + gpu_avg + mem_avg
            error_a = wall_a - predicted_a
            print(f"  A (measured):  {wall_a:.2f}W")
            print(f"  A (predicted): C + GPU_idle + MEM_DIMM = {wall_c:.2f} + {gpu_avg:.2f} + {mem_avg:.2f} = {predicted_a:.2f}W")
            print(f"  Error:         {error_a:+.2f}W ({abs(error_a)/wall_a*100:.1f}%)")

        # Consistency: A - B = D - C (both should give memory)
        ab_diff = wall_a - wall_b
        dc_diff = wall_d - wall_c
        print(f"\n  A - B = {ab_diff:.2f}W  (should be ~Memory/DIMM)")
        print(f"  D - C = {dc_diff:.2f}W  (should be ~Memory/DIMM)")
        print(f"  Difference: {abs(ab_diff - dc_diff):.2f}W")

        # Consistency: B - C = A - D (both should give GPU_idle)
        bc_diff = wall_b - wall_c
        ad_diff = wall_a - wall_d
        print(f"\n  B - C = {bc_diff:.2f}W  (should be ~GPU_idle)")
        print(f"  A - D = {ad_diff:.2f}W  (should be ~GPU_idle)")
        print(f"  Difference: {abs(bc_diff - ad_diff):.2f}W")

        # Closure: A - B - C + D should be ~0
        # (A-B) - (C-D) = (A-C) - (B-D)
        # If components are additive: A = base + gpu + mem, B = base + gpu, C = base + mem_removed_gpu_removed...
        # Actually: A-B-D+C should be ~0 (2x2 design balance)
        closure = wall_a - wall_b - wall_d + wall_c
        print(f"\n  Closure test: A - B - D + C = {closure:.2f}W (should be ~0)")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 7. PSU Efficiency Analysis
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 70)
    print("6. PSU Efficiency Analysis (1000W 80+ Gold)")
    print("=" * 70)

    # 80 Plus Gold efficiency curve (approximate)
    # 20% load: 88%, 50% load: 90%, 100% load: 87%
    # At very low loads (<10%): significantly worse
    # Extrapolation for <10% load based on typical curves

    for cfg in ['A', 'B', 'C', 'D']:
        if cfg not in configs or not configs[cfg].get('wall_w'):
            continue
        d = configs[cfg]
        wall = d['wall_w']
        load_pct = wall / 1000 * 100

        # Estimate efficiency at this load
        # Linear interpolation from known points
        # 5% load: ~75%, 10% load: ~82%, 20% load: ~88%
        if load_pct < 10:
            eff = 0.70 + (load_pct / 10) * 0.12  # 70% at 0% to 82% at 10%
        elif load_pct < 20:
            eff = 0.82 + ((load_pct - 10) / 10) * 0.06  # 82% at 10% to 88% at 20%
        else:
            eff = 0.88

        dc_power = wall * eff
        psu_loss = wall - dc_power
        print(f"  Config {cfg}: Wall={wall:.1f}W, Load={load_pct:.1f}%, "
              f"Est.Eff={eff*100:.0f}%, DC={dc_power:.1f}W, PSU_loss={psu_loss:.1f}W")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 8. CPU Nonlinearity Check
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 70)
    print("7. CPU Nonlinearity Check (Idle)")
    print("=" * 70)

    for cfg in ['A', 'B', 'C', 'D']:
        if cfg not in configs:
            continue
        d = configs[cfg]
        print(f"  Config {cfg}: CPU%={d['cpu_pct']:.2f}%, RAPL_pkg={d['rapl_package_w']:.2f}W, "
              f"RAPL_core={d['rapl_core_w']:.2f}W, "
              f"Avg_freq={d.get('avg_cpu_mhz', 0):.0f}MHz")

    print(f"\n  All configs are idle -> CPU should be nearly identical")
    if all(cfg in configs for cfg in ['A', 'B', 'C', 'D']):
        rapl_vals = [configs[c]['rapl_package_w'] for c in ['A', 'B', 'C', 'D']]
        print(f"  RAPL package range: {min(rapl_vals):.2f} - {max(rapl_vals):.2f}W "
              f"(spread={max(rapl_vals)-min(rapl_vals):.2f}W)")
        cpu_pcts = [configs[c]['cpu_pct'] for c in ['A', 'B', 'C', 'D']]
        print(f"  CPU% range: {min(cpu_pcts):.2f} - {max(cpu_pcts):.2f}% "
              f"(spread={max(cpu_pcts)-min(cpu_pcts):.2f}%)")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 9. Final 5-Component Model Parameters
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 70)
    print("8. FINAL: 5-Component Attribution Model Parameters")
    print("=" * 70)

    print(f"\n  Component          | Method                | Value")
    print(f"  ─────────────────────────────────────────────────────")
    print(f"  CPU                | RAPL package-0        | Direct measurement")

    if all(cfg in configs for cfg in ['A', 'B', 'C', 'D']):
        gpu0_vals = []
        for cfg in ['A', 'B', 'C', 'D']:
            if 'gpu0_power_w' in configs[cfg]:
                gpu0_vals.append(configs[cfg]['gpu0_power_w'])
        if gpu0_vals:
            print(f"  GPU (per card)     | nvidia-smi            | Direct ({np.mean(gpu0_vals):.1f}W idle)")

    if mem_estimates:
        print(f"  Memory (per DIMM)  | Physical isolation    | {mem_avg:.2f}W")

    if C.get('wall_w'):
        print(f"  Storage+Chipset+..| Residual (Config C)   | {residual_c:.2f}W total")
        if mem_estimates:
            print(f"  Pure Fixed Others  | Residual - 1 DIMM     | {fixed_core:.2f}W")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 10. Full Power Budget Reconstruction
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 70)
    print("9. Full Power Budget Reconstruction")
    print("=" * 70)

    for cfg in ['A', 'B', 'C', 'D']:
        if cfg not in configs or not configs[cfg].get('wall_w'):
            continue
        d = configs[cfg]
        wall = d['wall_w']
        cpu = d['rapl_package_w']
        gpu = d['gpu_total_w']
        exp = expected[cfg]
        n_dimm = exp['dimm']
        n_gpu = exp['gpu']

        mem_power = n_dimm * mem_avg if mem_estimates else 0
        accounted = cpu + gpu + mem_power

        if mem_estimates and C.get('wall_w'):
            others = wall - accounted
            print(f"\n  Config {cfg} ({exp['desc']}):")
            print(f"    Wall power:      {wall:.2f}W (100%)")
            print(f"    CPU (RAPL):      {cpu:.2f}W ({cpu/wall*100:.1f}%)")
            print(f"    GPU (nvidia-smi):{gpu:.2f}W ({gpu/wall*100:.1f}%)")
            print(f"    Memory ({n_dimm} DIMM): {mem_power:.2f}W ({mem_power/wall*100:.1f}%)")
            print(f"    Fixed Others:    {others:.2f}W ({others/wall*100:.1f}%)")
            print(f"    Total accounted: {accounted:.2f}W ({accounted/wall*100:.1f}%)")

    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)


if __name__ == '__main__':
    main()
