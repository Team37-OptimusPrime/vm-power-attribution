#!/usr/bin/env python3
"""
Phase 1.5 test2 모든 데이터를 하나의 CSV로 통합
- Host (RAPL, GPU)
- Cgroup (CPU%, Memory, IO per slice)
- RPICT (Wall Power)
"""

import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# 경로 설정
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data/raw/alienware/phase1.5/20260206_020631_test2"
RPICT_FILE = BASE_DIR / "data/raw/rpict/rpict_phase1.5-test2.csv"
OUTPUT_DIR = BASE_DIR / "data/raw/phase1.5_merged"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_and_tag_host_data():
    """Host 데이터 로드 및 phase 태깅"""
    phases = ['baseline', 'yolo_solo', 'nodejs_solo', 'concurrent']
    dfs = []

    for phase in phases:
        file_path = DATA_DIR / f"{phase}_host.csv"
        if file_path.exists():
            df = pd.read_csv(file_path, parse_dates=['timestamp'])
            df['phase'] = phase
            dfs.append(df)

    return pd.concat(dfs, ignore_index=True)

def load_and_tag_cgroup_data():
    """Cgroup 데이터 로드 및 phase 태깅, wide format으로 변환"""
    phases = ['baseline', 'yolo_solo', 'nodejs_solo', 'concurrent']
    dfs = []

    for phase in phases:
        file_path = DATA_DIR / f"{phase}_cgroup.csv"
        if file_path.exists():
            df = pd.read_csv(file_path, parse_dates=['timestamp'])
            df['phase'] = phase
            dfs.append(df)

    merged = pd.concat(dfs, ignore_index=True)

    # Long to Wide: yolo.slice와 nodejs.slice를 컬럼으로 분리
    yolo_df = merged[merged['cgroup'] == 'yolo.slice'].copy()
    nodejs_df = merged[merged['cgroup'] == 'nodejs.slice'].copy()

    # 컬럼 이름 변경
    yolo_df = yolo_df.rename(columns={
        'cpu_percent': 'yolo_cpu_pct',
        'memory_mb': 'yolo_memory_mb',
        'io_read_kbs': 'yolo_io_read_kbs',
        'io_write_kbs': 'yolo_io_write_kbs',
        'num_procs': 'yolo_num_procs'
    })

    nodejs_df = nodejs_df.rename(columns={
        'cpu_percent': 'nodejs_cpu_pct',
        'memory_mb': 'nodejs_memory_mb',
        'io_read_kbs': 'nodejs_io_read_kbs',
        'io_write_kbs': 'nodejs_io_write_kbs',
        'num_procs': 'nodejs_num_procs'
    })

    # 필요한 컬럼만 선택
    yolo_cols = ['timestamp', 'phase', 'yolo_cpu_pct', 'yolo_memory_mb',
                 'yolo_io_read_kbs', 'yolo_io_write_kbs']
    nodejs_cols = ['timestamp', 'nodejs_cpu_pct', 'nodejs_memory_mb',
                   'nodejs_io_read_kbs', 'nodejs_io_write_kbs']

    yolo_df = yolo_df[yolo_cols]
    nodejs_df = nodejs_df[['timestamp'] + nodejs_cols[1:]]

    # timestamp로 병합
    wide_df = pd.merge(yolo_df, nodejs_df, on='timestamp', how='outer')

    return wide_df

def load_rpict_data():
    """RPICT 벽면 전력 데이터"""
    if RPICT_FILE.exists():
        df = pd.read_csv(RPICT_FILE, parse_dates=['timestamp'])
        df = df.rename(columns={'power1_w': 'wall_power_w'})
        return df[['timestamp', 'wall_power_w', 'voltage_v', 'current1_a']]
    return None

def merge_all_data():
    """모든 데이터를 시간 기준으로 병합"""
    print("Loading Host data...")
    host_df = load_and_tag_host_data()
    print(f"  Host: {len(host_df)} rows")

    print("Loading Cgroup data...")
    cgroup_df = load_and_tag_cgroup_data()
    print(f"  Cgroup: {len(cgroup_df)} rows")

    print("Loading RPICT data...")
    rpict_df = load_rpict_data()
    print(f"  RPICT: {len(rpict_df)} rows")

    # Host + Cgroup 병합 (timestamp 기준)
    print("\nMerging Host + Cgroup...")
    merged = pd.merge(host_df, cgroup_df, on=['timestamp', 'phase'], how='outer')
    print(f"  After Host+Cgroup: {len(merged)} rows")

    # RPICT는 샘플링 주기가 다르므로 (3초) 가장 가까운 시간으로 병합
    print("Merging with RPICT (nearest timestamp)...")
    merged = merged.sort_values('timestamp')
    rpict_df = rpict_df.sort_values('timestamp')

    # asof merge로 가장 가까운 RPICT 값 매칭
    merged = pd.merge_asof(
        merged,
        rpict_df,
        on='timestamp',
        direction='nearest',
        tolerance=pd.Timedelta('5s')
    )
    print(f"  Final merged: {len(merged)} rows")

    # 컬럼 순서 정리
    col_order = [
        'timestamp', 'phase',
        # Wall Power (RPICT)
        'wall_power_w', 'voltage_v', 'current1_a',
        # Host Power
        'rapl_package_w', 'rapl_core_w', 'gpu_power_w', 'gpu_temp_c', 'gpu_util_pct',
        # Host System
        'cpu_pct', 'iowait_pct', 'mem_used_pct',
        # YOLO cgroup
        'yolo_cpu_pct', 'yolo_memory_mb', 'yolo_io_read_kbs', 'yolo_io_write_kbs',
        # Node.js cgroup
        'nodejs_cpu_pct', 'nodejs_memory_mb', 'nodejs_io_read_kbs', 'nodejs_io_write_kbs',
    ]

    # 존재하는 컬럼만 선택
    col_order = [c for c in col_order if c in merged.columns]
    merged = merged[col_order]

    return merged

def create_summary_with_all():
    """전체 요약 (하드웨어 정보 포함)"""
    summary = """Phase 1.5 Experiment Summary
============================

Hardware:
- Host: Alienware Aurora R12
- CPU: Intel i7-11700F (8 cores)
- GPU: NVIDIA RTX 3060
- RAM: 32GB DDR4-3467 (16GB x 2)
- Storage: Samsung SSD 980 500GB (NVMe)

Resource Allocation (cgroup v2):
- YOLO: cores 0-1, 4GB RAM
- Node.js: cores 2-3, 4GB RAM

Workloads:
- AI: YOLOv8 Nano (GPU accelerated)
- Non-AI: Node.js Express + curl

Results Summary:
================
| Phase        | Wall(W) | CPU(W) | GPU(W) | Other(W) | YOLO CPU% | Node CPU% |
|--------------|---------|--------|--------|----------|-----------|-----------|
| Idle         |  37.8   |  5.5   |  8.4   |  23.9    |    0.0    |    0.0    |
| YOLO Solo    | 114.5   | 31.9   | 37.4   |  45.2    |   95.6    |    0.0    |
| Node.js Solo |  42.0   |  7.5   |  8.4   |  26.1    |    0.0    |   17.4    |
| Concurrent   | 115.7   | 31.8   | 36.2   |  47.7    |   91.0    |   13.7    |

Key Finding:
- Same resource allocation (2 cores, 4GB each)
- Power difference: 2.7x (114.5W vs 42.0W)
- Delta difference: 18.3x (+77W vs +4W from idle)

Idle Power Breakdown (estimated):
- DRAM (DDR4 x2): ~2-3W
- Storage (NVMe): ~0.5-1W
- Motherboard: ~8-10W
- Fans: ~3-5W
- PSU Loss: ~5-6W
"""
    return summary

def main():
    print("=" * 60)
    print("Phase 1.5 데이터 통합 (Host + Cgroup + RPICT)")
    print("=" * 60)

    # 모든 데이터 병합
    merged_df = merge_all_data()

    # 저장
    output_file = OUTPUT_DIR / "phase1.5_all_data_merged.csv"
    merged_df.to_csv(output_file, index=False)
    print(f"\n✓ Saved: {output_file}")
    print(f"  Total rows: {len(merged_df)}")
    print(f"  Columns: {list(merged_df.columns)}")

    # 요약 저장
    summary = create_summary_with_all()
    summary_file = OUTPUT_DIR / "phase1.5_experiment_summary.txt"
    summary_file.write_text(summary)
    print(f"✓ Saved: {summary_file}")

    # 샘플 출력
    print("\n" + "=" * 60)
    print("Sample data (first 5 rows):")
    print("=" * 60)
    print(merged_df.head().to_string())

    print("\n" + "=" * 60)
    print(f"교수님께 제출할 파일: {output_file.name}")
    print("=" * 60)

if __name__ == '__main__':
    main()
