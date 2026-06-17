
import pandas as pd
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN1_FILE = os.path.join(BASE, "reports/phase3/system_power.tsv")
RUN2_FILE = os.path.join(BASE, "reports/phase3_run2/system_power_run2.tsv")

RUN1_WL_FILE = os.path.join(BASE, "reports/phase3/workload_usage.tsv")
RUN2_WL_FILE = os.path.join(BASE, "reports/phase3_run2/workload_usage_run2.tsv")

def load_data():
    df1 = pd.read_csv(RUN1_FILE, sep='\t')
    df2 = pd.read_csv(RUN2_FILE, sep='\t')
    return df1, df2

def check_io(wl_file, run_name):
    print(f"\n--- Storage I/O Check ({run_name}) ---")
    df = pd.read_csv(wl_file, sep='\t')
    
    # Filter for non-YOLO workloads
    non_yolo = df[~df['workload'].str.contains('YOLO', case=False, na=False)]
    
    # Check max I/O for these
    max_io = non_yolo['io_total_MB'].astype(float).max()
    print(f"Max I/O for non-YOLO workloads: {max_io} MB")
    
    if max_io < 1.0:
        print("CONFIRMED: Storage I/O is effectively zero for non-YOLO workloads.")
    else:
        print("NOTE: Some non-YOLO workloads have I/O activity.")
        print(non_yolo[['workload', 'io_total_MB']])

def main():
    if not os.path.exists(RUN1_FILE) or not os.path.exists(RUN2_FILE):
        print("Missing report files.")
        return

    df1, df2 = load_data()
    
    # Merge on experiment
    merged = pd.merge(df1, df2, on="experiment", suffixes=('_run1', '_run2'))
    
    print("\n--- Power Variance Analysis (Run 1 vs Run 2) ---\n")
    print(f"{'Experiment':<25} | {'Wall_1':<6} | {'Wall_2':<6} | {'Diff':<5} | {'% Diff'}")
    print("-" * 65)
    
    total_diff_pct = 0
    count = 0
    
    for idx, row in merged.iterrows():
        w1 = float(row['wall_power_W_run1'])
        w2 = float(row['wall_power_W_run2'])
        diff = abs(w1 - w2)
        pct = (diff / w1) * 100 if w1 > 0 else 0
        
        print(f"{row['experiment']:<25} | {w1:6.2f} | {w2:6.2f} | {diff:5.2f} | {pct:5.2f}%")
        
        total_diff_pct += pct
        count += 1
        
    print("-" * 65)
    print(f"Average Variance: {total_diff_pct/count:.2f}%")
    
    check_io(RUN1_WL_FILE, "Run 1")
    check_io(RUN2_WL_FILE, "Run 2")

if __name__ == "__main__":
    main()
