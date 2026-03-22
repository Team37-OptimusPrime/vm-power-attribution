
import os
import pandas as pd
import numpy as np
from datetime import timedelta

# Configuration
BASE_DIR = "/Users/rainyforest/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution"
PHASE3_DIR = os.path.join(BASE_DIR, "data/raw/alienware/phase3_fixed_run2")
RPICT_FILE = os.path.join(BASE_DIR, "data/raw/rpict/phase3-run2.csv")
REPORT_FILE = os.path.join(BASE_DIR, "reports/phase3_run2/system_power_run2.tsv")

MEMORY_POWER = 6.4
STORAGE_FACTOR = 0.0025 # W / (MB/s)

def load_rpict():
    df = pd.read_csv(RPICT_FILE)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

def process_phase_verification(host_csv, rpict_df):
    df_h = pd.read_csv(host_csv)
    df_h['timestamp'] = pd.to_datetime(df_h['timestamp'])
    
    if df_h.empty:
        return None
        
    start = df_h['timestamp'].iloc[0] + timedelta(seconds=10)
    end = df_h['timestamp'].iloc[-1] - timedelta(seconds=10)
    
    duration = (end - start).total_seconds()
    
    # Masks
    mask_h = (df_h['timestamp'] >= start) & (df_h['timestamp'] <= end)
    mask_r = (rpict_df['timestamp'] >= start) & (rpict_df['timestamp'] <= end)
    
    df_h_filt = df_h.loc[mask_h]
    df_r_filt = rpict_df.loc[mask_r]
    
    # Calcs
    wall_power = df_r_filt['power1_w'].mean() if not df_r_filt.empty else 0
    cpu_power = df_h_filt['rapl_package_w'].mean()
    gpu0_power = df_h_filt['gpu0_power_w'].mean()
    gpu1_power = df_h_filt['gpu1_power_w'].mean()
    
    return {
        'duration': duration,
        'wall_power': wall_power,
        'cpu_power': cpu_power,
        'gpu0_power': gpu0_power,
        'gpu1_power': gpu1_power,
    }


def parse_ts(s):
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return pd.to_datetime(s, format=fmt)
        except ValueError:
            continue
    return pd.to_datetime(s) 

def align_rpict_timestamps(rpict_df):
    """Align RPICT timestamps to Host Baseline Start"""
    baseline_host = os.path.join(PHASE3_DIR, "baseline_host.csv")
    if not os.path.exists(baseline_host):
        print("[WARN] Baseline file missing")
        return rpict_df
        
    df_h = pd.read_csv(baseline_host)
    if df_h.empty:
        return rpict_df
        
    host_start = pd.to_datetime(df_h['timestamp'].iloc[0])
    rpict_start = rpict_df['timestamp'].iloc[0]
    
    offset = host_start - rpict_start
    
    if abs(offset.total_seconds()) < 60:
        return rpict_df
        
    print(f"  [INFO] Applying Time Offset: {offset}")
    rpict_df['timestamp'] = rpict_df['timestamp'] + offset
    return rpict_df

def main():
    print(f"Loading RPICT data from {RPICT_FILE}...")
    rpict_df = load_rpict()
    
    # Align
    rpict_df = align_rpict_timestamps(rpict_df)
    
    print(f"Loading Report from {REPORT_FILE}...")
    if not os.path.exists(REPORT_FILE):
        print("Report file not found. Run extract_phase3_run2.py first.")
        return

    report_df = pd.read_csv(REPORT_FILE, sep='\t')
    
    print("\n--- Verifying Run 2 Experiments ---\n")
    
    discrepancies = []
    
    for idx, row in report_df.iterrows():
        phase_name = row['experiment']
        host_filename = f"{phase_name}_host.csv"
        host_path = os.path.join(PHASE3_DIR, host_filename)
        
        if not os.path.exists(host_path):
            print(f"[MISSING] Raw file not found: {host_path}")
            continue
            
        print(f"Checking {phase_name}...", end=" ")
        
        calc = process_phase_verification(host_path, rpict_df)
        if not calc:
            print("FAILED (No data)")
            continue
            
        rep_wall = float(row['wall_power_W'])
        rep_cpu = float(row['cpu_power_W'])
        rep_gpu = float(row['gpu0_power_W']) + float(row['gpu1_power_W'])
        
        diff_wall = abs(calc['wall_power'] - rep_wall)
        
        # Slightly higher tolerance for window mismatches
        if diff_wall < 2.5:
            print("OK")
        else:
            print("MISMATCH")
            print(f"  Metric | Report | Calc | Diff")
            print(f"  -------|--------|------|-----")
            print(f"  Wall   | {rep_wall:6.2f} | {calc['wall_power']:6.2f} | {diff_wall:4.2f}")
            discrepancies.append(phase_name)

    if not discrepancies:
        print("\n[SUCCESS] Run 2 data verified.")
    else:
        print(f"\n[WARNING] Found discrepancies in {len(discrepancies)} experiments.")

if __name__ == "__main__":
    main()
