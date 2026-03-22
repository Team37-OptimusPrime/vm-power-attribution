import os
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta

# Configuration
BASE_DIR = "/Users/rainyforest/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution"
DATA_DIR = os.path.join(BASE_DIR, "data/raw/alienware")
RPICT_FILE = os.path.join(BASE_DIR, "data/raw/rpict/phase2.2.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "reports/phase2.2")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "professor_data_v2.tsv")

# Constants
MEMORY_POWER_CONSTANT = 6.4  # 0.2 W/GB * 32 GB
STORAGE_ENERGY_RATE = 0.0025  # J/MB
GPU_IDLE_HIDDEN_POWER = 7.6  # W (approximate, per card) - Not explicitly used for attribution in this simplified view, but good to know
DURATION = 90  # Seconds, fixed duration for analysis window logic
WINDOW_TRIM = 10  # Seconds to trim from start/end

# Workload Definitions from Config (hardcoded for simplicity as they are fixed in the script)
# GPU0 is YOLO, GPU1 is Node.js (Idle/Hidden)
ALLOCATIONS = {
    'A1': {'cpu': 2, 'gpu': 1, 'mem': 4}, # YOLO Nano
    'A2': {'cpu': 2, 'gpu': 1, 'mem': 4}, # YOLO Medium
    'B1': {'cpu': 2, 'gpu': 0, 'mem': 1}, # Node Light (GPU0 allocated but unused in practice for processing, mostly cpu)
    'B2': {'cpu': 2, 'gpu': 0, 'mem': 1}, # Node Heavy
}
# For concurrent, simply sum allocations? Or just list them side by side.
# The request asks for "Allocated CPU/GPU/Mem" per workload.

def load_rpict_data(filepath):
    """Loads RPICT data and parses timestamps."""
    df = pd.read_csv(filepath)
    # Parse timestamp - format in file: 2026-02-16T16:18:17.294
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

def get_phase_window(host_df, duration=90, trim=10):
    """Determines the stable time window for a phase."""
    # Assuming the host file captures the entire duration roughly
    # We'll take the start time from the first row, end time from last
    # calculate middle window.
    if host_df.empty:
        return None, None
    
    start_time = pd.to_datetime(host_df['timestamp'].iloc[0])
    end_time = pd.to_datetime(host_df['timestamp'].iloc[-1])
    
    # Calculate stable window
    stable_start = start_time + timedelta(seconds=trim)
    stable_end = end_time - timedelta(seconds=trim)
    
    return stable_start, stable_end

def process_phase(mode, phase_name, host_file, cgroup_file, rpict_df):
    """Process a single phase experiment."""
    
    # Load Logs
    if not os.path.exists(host_file) or not os.path.exists(cgroup_file):
        print(f"Warning: Missing files for {phase_name} in {mode}")
        return None

    df_host = pd.read_csv(host_file)
    df_cgroup = pd.read_csv(cgroup_file)
    
    # Parse Timestamps
    df_host['timestamp'] = pd.to_datetime(df_host['timestamp'])
    df_cgroup['timestamp'] = pd.to_datetime(df_cgroup['timestamp'])
    
    # Determine Window
    start_time, end_time = get_phase_window(df_host)
    if start_time is None:
        return None
    
    # Filter Data
    mask_host = (df_host['timestamp'] >= start_time) & (df_host['timestamp'] <= end_time)
    mask_cgroup = (df_cgroup['timestamp'] >= start_time) & (df_cgroup['timestamp'] <= end_time)
    mask_rpict = (rpict_df['timestamp'] >= start_time) & (rpict_df['timestamp'] <= end_time)
    
    df_h_filtered = df_host.loc[mask_host]
    df_cg_filtered = df_cgroup.loc[mask_cgroup]
    df_r_filtered = rpict_df.loc[mask_rpict]
    
    valid_duration = (end_time - start_time).total_seconds()
    if valid_duration <= 0:
        valid_duration = 1 # Avoid div by zero
        
    # --- Metrics Calculation ---
    
    # 1. Power (System Total)
    if not df_r_filtered.empty:
        wall_power = df_r_filtered['power1_w'].mean()
    else:
        wall_power = 0.0 # Should not happen if confirmed RPICT
        
    # 2. Component Power (Averaged over window)
    cpu_power = df_h_filtered['rapl_package_w'].mean()
    gpu_power = df_h_filtered['gpu0_power_w'].mean() + df_h_filtered['gpu1_power_w'].mean()
    mem_power = MEMORY_POWER_CONSTANT
    
    # 3. Storage Energy (Derived from IO amount)
    # Get total IO from cgroup (sum of all cgroups) or host? 
    # Use cgroup for per-workload breakdown, Host for total.
    # Host 'io_read_kbs' + 'io_write_kbs' -> MB/s average
    total_io_rate_mb_s = (df_h_filtered['io_read_kbs'].mean() + df_h_filtered['io_write_kbs'].mean()) / 1024.0
    storage_power = total_io_rate_mb_s * STORAGE_ENERGY_RATE * 1000 # wait, rate is J/MB? No, rate is J/MB. Power = J/s. 
    # Rate = W / (MB/s). So Power = Rate * Throughput. 
    # 0.0025 (J/MB) ? No, professor said 2.5 J/GB = 0.0025 J/MB.
    # Unit check: J/MB * MB/s = J/s = W. Correct.
    storage_power = total_io_rate_mb_s * 2.5 # 2.5 J/GB = 0.0025 J/MB. Wait. 2.5 J/GB.
    # 1 GB = 1024 MB. 2.5 J / 1024 MB = 0.00244 J/MB.
    # Professor said: "0.0025 (J/MB), 즉 2.5(J/GB)". This implies 1GB=1000MB in his head maybe?
    # Let's stick to 0.0025 J/MB as strictly stated.
    storage_power_w = total_io_rate_mb_s * 0.0025 * 1000 # Wait. total_io_rate_mb_s is MB per second.
    # Power (W) = 0.0025 (J/MB ???) No 2.5 J/GB.
    # Let's use 0.0025 W / (MB/s) as derived in my previous report verification?
    # Report says: "Storage rate (AC) 0.0025 W/(MB/s)".
    # Yes. Power = 0.0025 * Throughput(MB/s).
    storage_power_val = total_io_rate_mb_s * 0.0025 # This seems low? 2000MB/s -> 5W. Correct.
    
    # 4. Workload Attribution
    # We need to split by cgroup: yolo.slice vs nodejs.slice
    # Also need to identify which workload corresponds to which.
    
    # Identify workloads in this phase
    # name format: "A1_yolo_nano" or "A1B1_concurrent"
    workloads = []
    
    # Simple logic based on phase name string
    is_concurrent = 'concurrent' in phase_name
    
    if is_concurrent:
        # A1B1 -> [A1, B1]
        parts = re.match(r"([AB]\d)([AB]\d)_concurrent", phase_name)
        if parts:
            w_codes = parts.groups()
    else:
        # A1_yolo_nano -> [A1]
        code = phase_name.split('_')[0]
        w_codes = [code]
        
    attribution_data = {}
    
    for code in w_codes:
        # Map code to cgroup
        cgroup_name = "yolo.slice" if code.startswith('A') else "nodejs.slice"
        
        # Filter cgroup data
        cg_data = df_cg_filtered[df_cg_filtered['cgroup'] == cgroup_name]
        
        if cg_data.empty:
            cpu_util = 0
            io_mb_s = 0
        else:
            cpu_util = cg_data['cpu_percent'].mean()
            io_kbs = cg_data['io_read_kbs'].mean() + cg_data['io_write_kbs'].mean()
            io_mb_s = io_kbs / 1024.0
            
        # GPU Util? Must map from host GPU stats.
        # GPU0 -> A (YOLO), GPU1 -> B (Node/Idle)
        if code.startswith('A'):
            gpu_util = df_h_filtered['gpu0_util_pct'].mean()
        else:
            gpu_util = df_h_filtered['gpu1_util_pct'].mean()
            
        # Allocations
        alloc_cpu = 200/100 # 2 cores? cpu.max says 200000 100000 -> 2 cores.
        alloc_gpu = 1
        alloc_mem = 4 # GB (Based on memory.max 4GB)
        
        attribution_data[code] = {
            'cpu_util': cpu_util,
            'gpu_util': gpu_util,
            'io_mb_s': io_mb_s,
            'alloc_cpu': 2, # Cores
            'alloc_gpu': 1, # Cards
            'alloc_mem': 4, # GB
        }

    return {
        'mode': mode,
        'phase': phase_name,
        'duration': valid_duration,
        'wall_power': wall_power,
        'cpu_power': cpu_power,
        'gpu_power': gpu_power,
        'mem_power': mem_power,
        'storage_power': storage_power_val,
        'workloads': attribution_data
    }

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    # Load RPICT
    if os.path.exists(RPICT_FILE):
        rpict_df = load_rpict_data(RPICT_FILE)
    else:
        print("Error: RPICT file not found.")
        return

    results = []

    # Iterate Modes
    for mode in ['fixed', 'free']:
        mode_dir = os.path.join(DATA_DIR, f"phase2.2_{mode}")
        if not os.path.exists(mode_dir):
            continue
            
        # Files in directory
        files = os.listdir(mode_dir)
        # Identify pairs of _host.csv
        phases = set()
        for f in files:
            if f.endswith('_host.csv') and not f.startswith('baseline'):
                phases.add(f.replace('_host.csv', ''))
        
        # Sort for stable order
        sorted_phases = sorted(list(phases))
        
        for p in sorted_phases:
            host_f = os.path.join(mode_dir, f"{p}_host.csv")
            cg_f = os.path.join(mode_dir, f"{p}_cgroup.csv")
            
            res = process_phase(mode, p, host_f, cg_f, rpict_df)
            if res:
                results.append(res)

    # --- Generate Tables ---
    
    # Flatten Data for TSV
    rows = []
    for r in results:
        # Base System Data
        base_row = {
            'Mode': r['mode'],
            'Phase': r['phase'],
            'Duration(s)': f"{r['duration']:.2f}",
            'Wall_Power(W)': f"{r['wall_power']:.2f}",
            'CPU_Power(W)': f"{r['cpu_power']:.2f}",
            'GPU_Power(W)': f"{r['gpu_power']:.2f}",
            'Mem_Power(W)': f"{r['mem_power']:.2f}",
            'Storage_I/O_Power(W)': f"{r['storage_power']:.4f}",
            'Wall_Energy(J)': f"{r['wall_power'] * r['duration']:.2f}",
        }
        
        # Workload Data columns
        # We need to handle 1 or 2 workloads.
        # TSV format needs to be consistent. 
        # Maybe "Workload 1", "Workload 2" columns? Or one row per workload?
        # User asked for: "Mult-workload basic data... and power... and time"
        # "3. Single-workload ... same constraints"
        
        # Let's flatten to One Row Per Phase, with columns for W1 and W2.
        # W1 = A (YOLO) usually, W2 = B (Node).
        
        w_keys = sorted(r['workloads'].keys())
        
        # Prefixes A and B
        for w_code in w_keys:
            # Determine prefix (A or B)
            # If A1B1 -> A1 is A, B1 is B.
            # If A1 Solo -> A.
            # If B1 Solo -> B? Or just W1?
            # Let's map strictly to A and B columns for clarity if possible.
            
            prefix = "W1" 
            if w_code.startswith('B'): prefix = "W2"
            elif w_code.startswith('A'): prefix = "W1"
            
            wd = r['workloads'][w_code]
            
            base_row[f'{prefix}_Name'] = w_code
            base_row[f'{prefix}_CPU_Util(%)'] = f"{wd['cpu_util']:.2f}"
            base_row[f'{prefix}_GPU_Util(%)'] = f"{wd['gpu_util']:.2f}"
            base_row[f'{prefix}_IO(MB/s)'] = f"{wd['io_mb_s']:.2f}"
            base_row[f'{prefix}_CPU_Alloc'] = wd['alloc_cpu']
            base_row[f'{prefix}_GPU_Alloc'] = wd['alloc_gpu']
            base_row[f'{prefix}_Mem_Alloc(GB)'] = wd['alloc_mem']
            
        rows.append(base_row)
        
    df_out = pd.DataFrame(rows)
    
    # Reorder columns nicely
    cols = ['Mode', 'Phase', 'Duration(s)', 
            'W1_Name', 'W1_CPU_Alloc', 'W1_GPU_Alloc', 'W1_Mem_Alloc(GB)', 'W1_CPU_Util(%)', 'W1_GPU_Util(%)', 'W1_IO(MB/s)',
            'W2_Name', 'W2_CPU_Alloc', 'W2_GPU_Alloc', 'W2_Mem_Alloc(GB)', 'W2_CPU_Util(%)', 'W2_GPU_Util(%)', 'W2_IO(MB/s)',
            'Wall_Power(W)', 'CPU_Power(W)', 'GPU_Power(W)', 'Mem_Power(W)', 'Storage_I/O_Power(W)', 'Wall_Energy(J)']
            
    # Ensure all columns exist (Concurrent has W1/W2, Solo might miss one)
    for c in cols:
        if c not in df_out.columns:
            df_out[c] = ""
            
    df_out = df_out[cols]
    
    # Sort
    df_out.sort_values(by=['Mode', 'Phase'], inplace=True)
    
    print(f"Generating TSV: {OUTPUT_FILE}")
    print(df_out.head())
    
    df_out.to_csv(OUTPUT_FILE, sep='\t', index=False)
    print("Done.")

if __name__ == "__main__":
    main()
