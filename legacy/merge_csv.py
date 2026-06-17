#!/usr/bin/env python3
"""
Phase 1.5 test2 CSV 파일들을 하나로 병합
교수님께 제출용
"""

import pandas as pd
from pathlib import Path

# 경로 설정
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data/raw/alienware/phase1.5/20260206_020631_test2"
RPICT_FILE = BASE_DIR / "data/raw/rpict/rpict_phase1.5-test2.csv"
OUTPUT_DIR = BASE_DIR / "data/raw/phase1.5_merged"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def merge_host_data():
    """Host 데이터 (RAPL, GPU) 병합"""
    phases = ['baseline', 'yolo_solo', 'nodejs_solo', 'concurrent']
    dfs = []

    for phase in phases:
        file_path = DATA_DIR / f"{phase}_host.csv"
        if file_path.exists():
            df = pd.read_csv(file_path)
            df['phase'] = phase
            dfs.append(df)
            print(f"  Loaded: {phase}_host.csv ({len(df)} rows)")

    merged = pd.concat(dfs, ignore_index=True)

    # 컬럼 순서 정리
    cols = ['phase', 'timestamp'] + [c for c in merged.columns if c not in ['phase', 'timestamp']]
    merged = merged[cols]

    return merged

def merge_cgroup_data():
    """cgroup 데이터 (CPU, Memory, IO per slice) 병합"""
    phases = ['baseline', 'yolo_solo', 'nodejs_solo', 'concurrent']
    dfs = []

    for phase in phases:
        file_path = DATA_DIR / f"{phase}_cgroup.csv"
        if file_path.exists():
            df = pd.read_csv(file_path)
            df['phase'] = phase
            dfs.append(df)
            print(f"  Loaded: {phase}_cgroup.csv ({len(df)} rows)")

    merged = pd.concat(dfs, ignore_index=True)

    # 컬럼 순서 정리
    cols = ['phase', 'timestamp', 'cgroup'] + [c for c in merged.columns if c not in ['phase', 'timestamp', 'cgroup']]
    merged = merged[cols]

    return merged

def load_rpict_data():
    """RPICT 벽면 전력 데이터"""
    if RPICT_FILE.exists():
        df = pd.read_csv(RPICT_FILE)
        print(f"  Loaded: rpict_phase1.5-test2.csv ({len(df)} rows)")
        return df
    return None

def create_summary():
    """요약 통계"""
    summary_data = {
        'Phase': ['Idle', 'YOLO Solo', 'Node.js Solo', 'Concurrent'],
        'Wall_Power_W': [37.8, 114.5, 42.0, 115.7],
        'CPU_RAPL_W': [5.5, 31.9, 7.5, 31.8],
        'GPU_Power_W': [8.4, 37.4, 8.4, 36.2],
        'Other_W': [23.9, 45.2, 26.1, 47.7],
        'YOLO_CPU_pct': [0, 95.6, 0, 91.0],
        'NodeJS_CPU_pct': [0, 0, 17.4, 13.7],
    }
    return pd.DataFrame(summary_data)

def main():
    print("=" * 50)
    print("Phase 1.5 Test2 데이터 병합")
    print("=" * 50)

    # Host 데이터 병합
    print("\n[1] Host 데이터 병합...")
    host_df = merge_host_data()
    host_output = OUTPUT_DIR / "phase1.5_host_all.csv"
    host_df.to_csv(host_output, index=False)
    print(f"  -> Saved: {host_output.name} ({len(host_df)} rows)")

    # Cgroup 데이터 병합
    print("\n[2] Cgroup 데이터 병합...")
    cgroup_df = merge_cgroup_data()
    cgroup_output = OUTPUT_DIR / "phase1.5_cgroup_all.csv"
    cgroup_df.to_csv(cgroup_output, index=False)
    print(f"  -> Saved: {cgroup_output.name} ({len(cgroup_df)} rows)")

    # RPICT 데이터
    print("\n[3] RPICT 데이터...")
    rpict_df = load_rpict_data()
    if rpict_df is not None:
        rpict_output = OUTPUT_DIR / "phase1.5_rpict_wall_power.csv"
        rpict_df.to_csv(rpict_output, index=False)
        print(f"  -> Saved: {rpict_output.name} ({len(rpict_df)} rows)")

    # 요약 통계
    print("\n[4] 요약 통계 생성...")
    summary_df = create_summary()
    summary_output = OUTPUT_DIR / "phase1.5_summary.csv"
    summary_df.to_csv(summary_output, index=False)
    print(f"  -> Saved: {summary_output.name}")
    print("\n요약:")
    print(summary_df.to_string(index=False))

    # 하드웨어 정보
    print("\n[5] 하드웨어 정보 저장...")
    hw_info = """Phase 1.5 Experiment Hardware Configuration
============================================

Host System:
- Model: Alienware Aurora R12
- CPU: Intel Core i7-11700F (8 cores, 16 threads)
- GPU: NVIDIA GeForce RTX 3060
- RAM: 32GB DDR4-3467 (16GB x 2)
- Storage: Samsung SSD 980 500GB (NVMe)

Power Measurement:
- Wall Power: RPICT4V3 CT Sensor (via Raspberry Pi)
- CPU Power: Intel RAPL (Package domain)
- GPU Power: nvidia-smi

Resource Isolation:
- Method: cgroup v2
- YOLO: cpuset.cpus=0-1, memory.max=4GB (yolo.slice)
- Node.js: cpuset.cpus=2-3, memory.max=4GB (nodejs.slice)

Workloads:
- AI: YOLOv8 Nano object detection (GPU accelerated)
- Non-AI: Node.js Express server + curl load generator

Idle Power Breakdown (estimated):
- Total Idle: 37.8W
  - CPU (RAPL): 5.5W
  - GPU: 8.4W
  - Other: 23.9W
    - DRAM (DDR4 x2): ~2-3W
    - Storage (NVMe SSD): ~0.5-1W
    - Motherboard/Chipset: ~8-10W
    - Fans/Cooling: ~3-5W
    - PSU Loss (~15%): ~5-6W
"""
    hw_output = OUTPUT_DIR / "hardware_info.txt"
    hw_output.write_text(hw_info)
    print(f"  -> Saved: {hw_output.name}")

    print("\n" + "=" * 50)
    print(f"모든 파일이 {OUTPUT_DIR}에 저장됨")
    print("=" * 50)

if __name__ == '__main__':
    main()
