
import os
import pandas as pd
import numpy as np
from datetime import timedelta

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHASE3_DIR = os.path.join(BASE_DIR, "data/raw/alienware/phase3_fixed")
RPICT_DIR = os.path.join(BASE_DIR, "data/raw/rpict")
REPORT_FILE = os.path.join(BASE_DIR, "reports/phase3/system_power.tsv")

MEMORY_POWER = 6.4
STORAGE_FACTOR = 0.0025 # W / (MB/s)

def load_rpict():
    # Load both phase3.csv and phase3-rerun.csv
    f1 = os.path.join(RPICT_DIR, "phase3.csv")
    f2 = os.path.join(RPICT_DIR, "phase3-rerun.csv")
    
    df1 = pd.read_csv(f1)
    df2 = pd.read_csv(f2)
    
    # Parse dates
    df1['timestamp'] = pd.to_datetime(df1['timestamp'])
    df2['timestamp'] = pd.to_datetime(df2['timestamp'])
    
    # Concatenate and sort
    df = pd.concat([df1, df2]).sort_values('timestamp').drop_duplicates('timestamp')
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
    
    # Storage
    io_read = df_h_filt['io_read_kbs'].mean()
    io_write = df_h_filt['io_write_kbs'].mean()
    io_total_mb = (io_read + io_write) / 1024.0
    storage_power = io_total_mb * STORAGE_FACTOR
    
    return {
        'duration': duration,
        'wall_power': wall_power,
        'cpu_power': cpu_power,
        'gpu0_power': gpu0_power,
        'gpu1_power': gpu1_power,
        'storage_power': storage_power
    }

def main():
    print(f"Loading RPICT data from {RPICT_DIR}...")
    rpict_df = load_rpict()
    print(f"Loaded {len(rpict_df)} rows of RPICT data.")
    
    print(f"Loading Report from {REPORT_FILE}...")
    report_df = pd.read_csv(REPORT_FILE, sep='\t')
    
    print("\n--- Verifying Each Experiment ---\n")
    
    discrepancies = []
    
    for idx, row in report_df.iterrows():
        phase_name = row['experiment']
        # File name convention mapping
        # Report: "A2_yolo_medium", Host File: "A2_yolo_medium_host.csv"
        # Report: "baseline", Host File: "baseline_host.csv"
        
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
            
        # Compare
        # Tolerances: Power +/- 1W (due to windowing jitter), Duration +/- 1s
        
        rep_wall = float(row['wall_power_W'])
        rep_cpu = float(row['cpu_power_W'])
        rep_gpu = float(row['gpu0_power_W']) + float(row['gpu1_power_W'])
        
        diff_wall = abs(calc['wall_power'] - rep_wall)
        diff_cpu = abs(calc['cpu_power'] - rep_cpu)
        diff_gpu = abs((calc['gpu0_power'] + calc['gpu1_power']) - rep_gpu)
        
        if diff_wall < 1.0 and diff_cpu < 0.5 and diff_gpu < 1.0:
            print("OK")
        else:
            print("MISMATCH")
            print(f"  Metric | Report | Calc | Diff")
            print(f"  -------|--------|------|-----")
            if diff_wall >= 1.0: print(f"  Wall   | {rep_wall:6.2f} | {calc['wall_power']:6.2f} | {diff_wall:4.2f}")
            if diff_cpu >= 0.5:  print(f"  CPU    | {rep_cpu:6.2f} | {calc['cpu_power']:6.2f} | {diff_cpu:4.2f}")
            if diff_gpu >= 1.0:  print(f"  GPU    | {rep_gpu:6.2f} | {calc['gpu0_power']+calc['gpu1_power']:6.2f} | {diff_gpu:4.2f}")
            discrepancies.append(phase_name)

    if not discrepancies:
        print("\n[SUCCESS] All data points verified with high accuracy!")
    else:
        print(f"\n[WARNING] Found discrepancies in {len(discrepancies)} experiments.")

if __name__ == "__main__":
    main()
