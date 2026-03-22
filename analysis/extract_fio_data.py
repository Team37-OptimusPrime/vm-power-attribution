import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Configuration
BASE_DIR = "/Users/rainyforest/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution"
DATA_DIR = os.path.join(BASE_DIR, "data/raw/alienware/phase2.1_fio")
RPICT_FILE = os.path.join(BASE_DIR, "data/raw/rpict/phase2.1.csv") # Assuming phase 2.1 has its own RPICT file? Or shared?
# Checking if RPICT splits by phase. Phase 2.2 used phase2.2.csv. 
# Likely phase2.1 used phase2.1.csv or phase2.csv.
# Let's try phase2.1.csv first, if not exist, check dir.

OUTPUT_FILE = os.path.join(BASE_DIR, "reports/phase2.2/fio_power_data.tsv")

def load_rpict_data(filepath):
    if not os.path.exists(filepath):
        return None
    df = pd.read_csv(filepath)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

def get_stable_window(df, trim_seconds=10):
    if df.empty:
        return None, None
    start = pd.to_datetime(df['timestamp'].iloc[0]) + timedelta(seconds=trim_seconds)
    end = pd.to_datetime(df['timestamp'].iloc[-1]) - timedelta(seconds=trim_seconds)
    return start, end

def process_phase(phase_name, host_file, rpict_df):
    if not os.path.exists(host_file):
        return None
    
    df_host = pd.read_csv(host_file)
    df_host['timestamp'] = pd.to_datetime(df_host['timestamp'])
    
    start, end = get_stable_window(df_host)
    if not start:
        return None
        
    # Valid duration
    duration = (end - start).total_seconds()
        
    mask_h = (df_host['timestamp'] >= start) & (df_host['timestamp'] <= end)
    df_h_filt = df_host.loc[mask_h]
    
    # RPICT
    wall_power = 0
    if rpict_df is not None:
        mask_r = (rpict_df['timestamp'] >= start) & (rpict_df['timestamp'] <= end)
        if mask_r.any():
            wall_power = rpict_df.loc[mask_r, 'power1_w'].mean()
            
    # Host Metrics
    cpu_power = df_h_filt['rapl_package_w'].mean()
    gpu_power = df_h_filt['gpu_power_w'].mean() if 'gpu_power_w' in df_h_filt.columns else (df_h_filt['gpu0_power_w'].mean() + df_h_filt['gpu1_power_w'].mean())
    
    # IO Throughput
    # Host logs 'io_read_kbs', 'io_write_kbs'
    # For fio seq_read, we expect heavy read. For write, heavy write.
    read_mb_s = df_h_filt['io_read_kbs'].mean() / 1024.0
    write_mb_s = df_h_filt['io_write_kbs'].mean() / 1024.0
    total_mb_s = read_mb_s + write_mb_s
    
    return {
        'Phase': phase_name,
        'Duration(s)': duration,
        'Wall_Power(W)': wall_power,
        'CPU_Power(W)': cpu_power,
        'GPU_Power(W)': gpu_power,
        'Read(MB/s)': read_mb_s,
        'Write(MB/s)': write_mb_s,
        'Total_Throughput(MB/s)': total_mb_s
    }

def main():
    # Find RPICT file
    rpict_path = RPICT_FILE
    if not os.path.exists(rpict_path):
        # Fallback check
        common_rpict = os.path.join(BASE_DIR, "data/raw/rpict/phase2.csv")
        if os.path.exists(common_rpict):
            rpict_path = common_rpict
        else:
            print(f"Warning: RPICT file not found at {RPICT_FILE}")
            rpict_path = None
            
    rpict_df = load_rpict_data(rpict_path) if rpict_path else None
    
    results = []
    
    # Phases to look for in phase2.1_fio
    # Typically: baseline, seq_read, seq_write, rand_read, rand_write...
    # Based on user email: 'Idle', 'seq_write', 'seq_read'
    
    target_phases = ['baseline', 'seq_read', 'seq_write']
    
    # Check directory content to match filenames
    if not os.path.exists(DATA_DIR):
        print(f"Error: Data dir {DATA_DIR} not found")
        return

    files = os.listdir(DATA_DIR)
    
    for phase_key in target_phases:
        # Find matching host file
        # e.g. "fio_seq_read_host.csv" or "seq_read_host.csv"
        # Let's search loosely
        match = None
        for f in files:
            if phase_key in f and f.endswith('_host.csv'):
                match = f
                break
        
        if match:
            res = process_phase(phase_key, os.path.join(DATA_DIR, match), rpict_df)
            if res:
                results.append(res)
                
    # Calculate Energy Efficiency if Idle exists
    idle_row = next((r for r in results if r['Phase'] == 'baseline'), None)
    
    final_rows = []
    if idle_row:
        idle_wall = idle_row['Wall_Power(W)']
        idle_cpu = idle_row['CPU_Power(W)']
        idle_gpu = idle_row['GPU_Power(W)']
        
        for r in results:
            row = r.copy()
            # Delta
            d_wall = r['Wall_Power(W)'] - idle_wall
            d_cpu = r['CPU_Power(W)'] - idle_cpu
            d_gpu = r['GPU_Power(W)'] - idle_gpu
            
            # Attribution (Storage Power = dWall - dCPU - dGPU)
            # Only valid for active phases
            if r['Phase'] != 'baseline':
                storage_power_ac = d_wall - d_cpu - d_gpu
                throughput = r['Total_Throughput(MB/s)']
                
                if throughput > 10: # Avoid div by zero
                    efficiency_j_mb = storage_power_ac / throughput
                    efficiency_j_gb = efficiency_j_mb * 1000
                else:
                    efficiency_j_mb = 0
                    efficiency_j_gb = 0
                    
                row['dWall(W)'] = d_wall
                row['dCPU(W)'] = d_cpu
                row['dGPU(W)'] = d_gpu
                row['Storage_Power_AC(W)'] = storage_power_ac
                row['Efficiency(J/GB)'] = efficiency_j_gb
            else:
                row['dWall(W)'] = 0
                row['dCPU(W)'] = 0
                row['dGPU(W)'] = 0
                row['Storage_Power_AC(W)'] = 0
                row['Efficiency(J/GB)'] = 0
                
            final_rows.append(row)
    else:
        final_rows = results

    df_out = pd.DataFrame(final_rows)
    
    # Columns order
    cols = ['Phase', 'Duration(s)', 
            'Wall_Power(W)', 'CPU_Power(W)', 'GPU_Power(W)', 
            'Total_Throughput(MB/s)', 
            'dWall(W)', 'dCPU(W)', 'dGPU(W)', 
            'Storage_Power_AC(W)', 'Efficiency(J/GB)']
            
    # Filter available columns
    cols = [c for c in cols if c in df_out.columns]
    df_out = df_out[cols]
    
    print(df_out)
    df_out.to_csv(OUTPUT_FILE, sep='\t', index=False)
    print(f"Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
