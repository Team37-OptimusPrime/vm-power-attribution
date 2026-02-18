#!/usr/bin/env python3
"""Phase 2.2 데이터 추출: 교수님 요청 형태 (TSV)

교수님 요청 항목:
1. Storage I/O 에너지: 2.5 J/GB
2. 동시실행 + 단독실행의:
   - 시스템 전체: Wall Power, CPU Power, GPU Power, Memory Power, Duration
   - 워크로드별: CPU 이용률, GPU 이용률, Storage I/O량, CPU/GPU/Memory 할당량
3. 단독실행 결과 (동일 cgroup 제약)

출력: TSV 파일 2개
  - system_power.tsv: 실험별 시스템 전력
  - workload_usage.tsv: 워크로드별 자원 사용량
"""

import csv
import os
from datetime import datetime
from pathlib import Path

BASE = Path(os.path.expanduser(
    "~/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution"))
RPICT_FILE = BASE / "data/raw/rpict/phase2.2.csv"
OUTPUT_DIR = BASE / "reports/phase2"

# 실험 Phase 정의
PHASES = [
    ("baseline", "idle", None, None),
    ("A1_yolo_nano", "solo", "A1(YOLO_Nano)", None),
    ("A2_yolo_medium", "solo", "A2(YOLO_Medium)", None),
    ("B1_nodejs_light", "solo", "B1(Node_Light)", None),
    ("B2_nodejs_heavy", "solo", "B2(Node_Heavy)", None),
    ("A1B1_concurrent", "concurrent", "A1(YOLO_Nano)", "B1(Node_Light)"),
    ("A1B2_concurrent", "concurrent", "A1(YOLO_Nano)", "B2(Node_Heavy)"),
    ("A2B1_concurrent", "concurrent", "A2(YOLO_Medium)", "B1(Node_Light)"),
    ("A2B2_concurrent", "concurrent", "A2(YOLO_Medium)", "B2(Node_Heavy)"),
]

# 안정 구간: 앞 15초 제거, 뒤 5초 제거
TRIM_START = 15
TRIM_END = 5


def parse_ts(s):
    """ISO timestamp -> datetime"""
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {s}")


def read_csv_rows(filepath):
    """CSV 파일 읽기 -> list of dicts"""
    rows = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def get_stable_range(rows, trim_start=TRIM_START, trim_end=TRIM_END):
    """안정 구간의 행만 반환 (앞뒤 trim)"""
    if not rows:
        return []
    t0 = parse_ts(rows[0]["timestamp"])
    t_last = parse_ts(rows[-1]["timestamp"])
    total_dur = (t_last - t0).total_seconds()

    stable = []
    for r in rows:
        t = parse_ts(r["timestamp"])
        elapsed = (t - t0).total_seconds()
        if elapsed >= trim_start and elapsed <= (total_dur - trim_end):
            stable.append(r)
    return stable


def avg(rows, col):
    """열의 평균값"""
    vals = []
    for r in rows:
        try:
            v = float(r[col])
            vals.append(v)
        except (ValueError, KeyError):
            pass
    return sum(vals) / len(vals) if vals else 0.0


def total_io_mb(rows, col):
    """IO rate (KB/s) 열에서 총 IO량 (MB) 계산 - 시간 간격 기반"""
    total_kb = 0.0
    for i in range(1, len(rows)):
        t1 = parse_ts(rows[i - 1]["timestamp"])
        t2 = parse_ts(rows[i]["timestamp"])
        dt = (t2 - t1).total_seconds()
        try:
            rate = float(rows[i][col])
        except (ValueError, KeyError):
            rate = 0.0
        total_kb += rate * dt
    return total_kb / 1024.0  # KB -> MB


def get_duration(rows):
    """전체 측정 시간(초)"""
    if len(rows) < 2:
        return 0.0
    t0 = parse_ts(rows[0]["timestamp"])
    t_last = parse_ts(rows[-1]["timestamp"])
    return (t_last - t0).total_seconds()


def get_stable_duration(stable_rows):
    """안정 구간 시간(초)"""
    if len(stable_rows) < 2:
        return 0.0
    t0 = parse_ts(stable_rows[0]["timestamp"])
    t_last = parse_ts(stable_rows[-1]["timestamp"])
    return (t_last - t0).total_seconds()


def load_rpict():
    """RPICT 데이터 로드"""
    rows = read_csv_rows(RPICT_FILE)
    result = []
    for r in rows:
        result.append({
            "timestamp": parse_ts(r["timestamp"]),
            "wall_power_w": float(r["power1_w"]),
        })
    return result


def get_rpict_avg(rpict_data, t_start, t_end):
    """시간 범위에 해당하는 RPICT wall power 평균"""
    vals = [r["wall_power_w"] for r in rpict_data
            if t_start <= r["timestamp"] <= t_end]
    return sum(vals) / len(vals) if vals else 0.0


def filter_cgroup(rows, cgroup_name):
    """특정 cgroup의 행만 필터"""
    return [r for r in rows if r.get("cgroup", "").strip() == cgroup_name]


def process_round(round_name, data_dir, rpict_data):
    """한 라운드(fixed/free) 처리"""
    system_rows = []
    workload_rows = []

    for phase_name, phase_type, wl_a, wl_b in PHASES:
        host_file = data_dir / f"{phase_name}_host.csv"
        cgroup_file = data_dir / f"{phase_name}_cgroup.csv"

        if not host_file.exists():
            print(f"  [SKIP] {host_file} not found")
            continue

        # Host 데이터
        host_raw = read_csv_rows(host_file)
        host_stable = get_stable_range(host_raw)
        duration = get_stable_duration(host_stable)

        if not host_stable:
            print(f"  [WARN] {phase_name}: no stable data")
            continue

        # RPICT wall power (시간 정렬)
        t_start = parse_ts(host_stable[0]["timestamp"])
        t_end = parse_ts(host_stable[-1]["timestamp"])
        wall_power = get_rpict_avg(rpict_data, t_start, t_end)

        # 시스템 전력
        cpu_power = avg(host_stable, "rapl_package_w")
        gpu0_power = avg(host_stable, "gpu0_power_w")
        gpu1_power = avg(host_stable, "gpu1_power_w")
        gpu_total = gpu0_power + gpu1_power
        gpu0_util = avg(host_stable, "gpu0_util_pct")
        gpu1_util = avg(host_stable, "gpu1_util_pct")

        # Memory Power: 0.2 W/GB × 32GB = 6.4W (교수님 지시)
        mem_power = 0.2 * 32  # 6.4W

        # gpu_total: 반올림된 값의 합으로 계산 (산술 일관성)
        gpu0_r = round(gpu0_power, 2)
        gpu1_r = round(gpu1_power, 2)
        gpu_total_r = round(gpu0_r + gpu1_r, 2)

        # 시스템 행
        sys_row = {
            "round": round_name,
            "experiment": phase_name,
            "type": phase_type,
            "workload_A": wl_a or "-",
            "workload_B": wl_b or "-",
            "duration_s": f"{duration:.1f}",
            "wall_power_W": f"{wall_power:.2f}",
            "cpu_power_W": f"{cpu_power:.2f}",
            "gpu0_power_W": f"{gpu0_r:.2f}",
            "gpu1_power_W": f"{gpu1_r:.2f}",
            "gpu_total_W": f"{gpu_total_r:.2f}",
            "gpu0_util_pct": f"{gpu0_util:.1f}",
            "gpu1_util_pct": f"{gpu1_util:.1f}",
            "memory_power_W": f"{mem_power:.1f}",
            "memory_power_note": "calculated:0.2W/GB×32GB",
            "gpu_note": "2cards(RTX3060×2),GPU0=YOLO,GPU1=Node.js",
        }
        system_rows.append(sys_row)

        # cgroup 데이터 (워크로드별)
        if cgroup_file.exists() and phase_type != "idle":
            cg_raw = read_csv_rows(cgroup_file)
            cg_stable = get_stable_range(cg_raw)

            workloads_info = []
            if phase_type == "solo":
                if "yolo" in phase_name.lower():
                    workloads_info = [(wl_a, "yolo.slice", "GPU0", 1)]
                else:
                    workloads_info = [(wl_a, "nodejs.slice", "GPU1(idle)", 0)]
            elif phase_type == "concurrent":
                workloads_info = [
                    (wl_a, "yolo.slice", "GPU0", 1),
                    (wl_b, "nodejs.slice", "GPU1(idle)", 0),
                ]

            for wl_name, cg_name, gpu_assign, gpu_cards in workloads_info:
                cg_filtered = filter_cgroup(cg_stable, cg_name)
                if not cg_filtered:
                    continue

                cpu_util = avg(cg_filtered, "cpu_percent")
                mem_mb = avg(cg_filtered, "memory_mb")
                io_read_total = total_io_mb(cg_filtered, "io_read_kbs")
                io_write_total = total_io_mb(cg_filtered, "io_write_kbs")

                # GPU util/power: cgroup에서 안 나오므로 host에서 가져옴
                # GPU 물리 분리: GPU0=YOLO, GPU1=Node.js → 직접 귀속
                if "yolo" in cg_name:
                    gpu_util = gpu0_util
                    gpu_pw = gpu0_power
                else:
                    gpu_util = gpu1_util
                    gpu_pw = gpu1_power

                wl_row = {
                    "round": round_name,
                    "experiment": phase_name,
                    "type": phase_type,
                    "workload": wl_name,
                    "cgroup": cg_name,
                    "cpu_util_pct": f"{cpu_util:.1f}",
                    "gpu_util_pct": f"{gpu_util:.1f}",
                    "gpu_power_W": f"{gpu_pw:.2f}",
                    "cpu_alloc_cores": "2",
                    "gpu_alloc": gpu_assign,
                    "gpu_alloc_cards": str(gpu_cards),
                    "mem_alloc_GB": f"{4.0:.1f}",  # cgroup limit: 4GB
                    "mem_used_MB": f"{mem_mb:.1f}",
                    "io_read_MB": f"{io_read_total:.1f}",
                    "io_write_MB": f"{io_write_total:.1f}",
                    "io_total_MB": f"{io_read_total + io_write_total:.1f}",
                    "duration_s": f"{duration:.1f}",
                }
                workload_rows.append(wl_row)

    return system_rows, workload_rows


def write_tsv(filepath, rows, columns):
    """TSV 파일 작성"""
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    print("=== Phase 2.2 데이터 추출 (교수님 요청 TSV) ===\n")

    rpict_data = load_rpict()
    print(f"RPICT 데이터: {len(rpict_data)}개 샘플 로드")

    all_system = []
    all_workload = []

    for round_name in ["fixed", "free"]:
        data_dir = BASE / f"data/raw/alienware/phase2.2_{round_name}"
        print(f"\n--- Round: {round_name} ({data_dir}) ---")
        sys_rows, wl_rows = process_round(round_name, data_dir, rpict_data)
        all_system.extend(sys_rows)
        all_workload.extend(wl_rows)
        print(f"  시스템 행: {len(sys_rows)}, 워크로드 행: {len(wl_rows)}")

    # TSV 출력
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    sys_cols = [
        "round", "experiment", "type", "workload_A", "workload_B",
        "duration_s", "wall_power_W", "cpu_power_W",
        "gpu0_power_W", "gpu1_power_W", "gpu_total_W",
        "gpu0_util_pct", "gpu1_util_pct",
        "memory_power_W", "memory_power_note", "gpu_note",
    ]
    sys_file = OUTPUT_DIR / "system_power.tsv"
    write_tsv(sys_file, all_system, sys_cols)
    print(f"\n[출력] {sys_file}")

    wl_cols = [
        "round", "experiment", "type", "workload", "cgroup",
        "cpu_util_pct", "gpu_util_pct", "gpu_power_W",
        "cpu_alloc_cores", "gpu_alloc", "gpu_alloc_cards",
        "mem_alloc_GB", "mem_used_MB",
        "io_read_MB", "io_write_MB", "io_total_MB",
        "duration_s",
    ]
    wl_file = OUTPUT_DIR / "workload_usage.tsv"
    write_tsv(wl_file, all_workload, wl_cols)
    print(f"[출력] {wl_file}")

    # 콘솔 미리보기
    print("\n\n===== system_power.tsv 미리보기 =====")
    print("\t".join(["round", "experiment", "type", "dur(s)", "wall_W",
                     "cpu_W", "gpu0_W", "gpu1_W", "gpu_tot_W", "mem_W"]))
    print("-" * 120)
    for r in all_system:
        print("\t".join([
            r["round"], r["experiment"], r["type"],
            r["duration_s"], r["wall_power_W"], r["cpu_power_W"],
            r["gpu0_power_W"], r["gpu1_power_W"], r["gpu_total_W"],
            r["memory_power_W"],
        ]))

    print("\n\n===== workload_usage.tsv 미리보기 =====")
    print("\t".join(["round", "experiment", "workload", "cpu%", "gpu%",
                     "cpu_cores", "gpu_cards", "mem_GB", "io_MB", "dur(s)"]))
    print("-" * 120)
    for r in all_workload:
        print("\t".join([
            r["round"], r["experiment"], r["workload"],
            r["cpu_util_pct"], r["gpu_util_pct"],
            r["cpu_alloc_cores"], r["gpu_alloc_cards"],
            r["mem_alloc_GB"], r["io_total_MB"], r["duration_s"],
        ]))

    # 추가 정보
    print("\n\n===== 참고 사항 =====")
    print("Storage I/O 에너지: ~2.56 J/GB (write 2.39, read 2.75 — GPU delta 제거, ×1024)")
    print("Memory Power: 0.2 W/GB (데이터시트 기준, 교수님 지시)")
    print("GPU: RTX 3060 × 2장, GPU0=YOLO(연산), GPU1=Node.js(idle hidden power)")
    print("CPU: i7-11700KF, cgroup cpuset 2코어씩 할당")
    print("  Fixed round: no_turbo=1, performance governor, 3.6GHz 고정")
    print("  Free round: turbo 허용, default governor")


if __name__ == "__main__":
    main()
