#!/usr/bin/env python3
"""Phase 3 데이터 추출: 다중 AI 워크로드 확장 실험 (TSV)

Phase 2.2 추출 스크립트 기반, Phase 3 워크로드 확장:
- 새 워크로드: PT (PyTorch GEMM), RN (ResNet18), GPT (GPT-2)
- AI+AI 동시실행 조합 지원
- GPU 할당: AI+B2 → AI=GPU0, B2=GPU1(idle)
            AI+AI → A=GPU0, B=GPU1

출력: TSV 파일 2개
  - system_power_<run>.tsv: 실험별 시스템 전력
  - workload_usage_<run>.tsv: 워크로드별 자원 사용량

Usage:
  python3 extract_phase3_data.py                            # 기본 (run1, PyTorch 포함)
  python3 extract_phase3_data.py --run run3                 # run3 (PyTorch 포함)
  python3 extract_phase3_data.py --run run4 --no-pt         # run4 (PyTorch 제외)
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

BASE = Path(os.path.expanduser(
    "~/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution"))
OUTPUT_DIR = BASE / "reports/phase3"

# 실험 Phase 정의 (전체 — PyTorch 포함)
# (파일 prefix, 타입, workload_A, workload_B, concurrent_type)
# concurrent_type: None(solo/idle), "ai_b2", "ai_ai"
PHASES_ALL = [
    # Baseline
    ("baseline", "idle", None, None, None),

    # Solo — 모든 AI는 yolo.slice(GPU0), B2는 nodejs.slice
    ("A2_yolo_medium", "solo", "A2(YOLO_Medium)", None, None),
    ("PT_pytorch_gemm", "solo", "PT(PyTorch_GEMM)", None, None),
    ("RN_resnet18", "solo", "RN(ResNet18)", None, None),
    ("GPT_gpt2", "solo", "GPT(GPT-2)", None, None),
    ("B2_nodejs_heavy", "solo", "B2(Node_Heavy)", None, None),

    # AI + B2 동시실행
    ("A2B2_concurrent", "concurrent", "A2(YOLO_Medium)", "B2(Node_Heavy)", "ai_b2"),
    ("PTB2_concurrent", "concurrent", "PT(PyTorch_GEMM)", "B2(Node_Heavy)", "ai_b2"),
    ("RNB2_concurrent", "concurrent", "RN(ResNet18)", "B2(Node_Heavy)", "ai_b2"),
    ("GPTB2_concurrent", "concurrent", "GPT(GPT-2)", "B2(Node_Heavy)", "ai_b2"),

    # AI + AI 동시실행 (A→GPU0/yolo.slice, B→GPU1/nodejs.slice)
    ("A2PT_concurrent", "concurrent", "A2(YOLO_Medium)", "PT(PyTorch_GEMM)", "ai_ai"),
    ("A2RN_concurrent", "concurrent", "A2(YOLO_Medium)", "RN(ResNet18)", "ai_ai"),
    ("A2GPT_concurrent", "concurrent", "A2(YOLO_Medium)", "GPT(GPT-2)", "ai_ai"),
    ("PTRN_concurrent", "concurrent", "PT(PyTorch_GEMM)", "RN(ResNet18)", "ai_ai"),
    ("PTGPT_concurrent", "concurrent", "PT(PyTorch_GEMM)", "GPT(GPT-2)", "ai_ai"),
    ("RNGPT_concurrent", "concurrent", "RN(ResNet18)", "GPT(GPT-2)", "ai_ai"),
]

# PyTorch 제외 버전 (11 phases) — 정확한 이름 일치로 필터
PT_PHASE_NAMES = {
    "PT_pytorch_gemm", "PTB2_concurrent", "A2PT_concurrent",
    "PTRN_concurrent", "PTGPT_concurrent",
}
PHASES_NOPT = [p for p in PHASES_ALL if p[0] not in PT_PHASE_NAMES]

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


def get_stable_duration(stable_rows):
    """안정 구간 시간(초)"""
    if len(stable_rows) < 2:
        return 0.0
    t0 = parse_ts(stable_rows[0]["timestamp"])
    t_last = parse_ts(stable_rows[-1]["timestamp"])
    return (t_last - t0).total_seconds()


def load_rpict():
    """RPICT 데이터 로드 (여러 파일 병합)"""
    result = []
    for rpict_file in RPICT_FILES:
        if not rpict_file.exists():
            print(f"[WARN] RPICT 파일 없음: {rpict_file}")
            continue
        rows = read_csv_rows(rpict_file)
        for r in rows:
            result.append({
                "timestamp": parse_ts(r["timestamp"]),
                "wall_power_w": float(r["power1_w"]),
            })
        print(f"  RPICT 로드: {rpict_file.name} ({len(rows)}개 샘플)")
    if not result:
        print("[WARN] RPICT 데이터 없음. Wall power는 0.0으로 표시됩니다.")
    result.sort(key=lambda x: x["timestamp"])
    return result


def get_rpict_avg(rpict_data, t_start, t_end):
    """시간 범위에 해당하는 RPICT wall power 평균"""
    vals = [r["wall_power_w"] for r in rpict_data
            if t_start <= r["timestamp"] <= t_end]
    return sum(vals) / len(vals) if vals else 0.0


def filter_cgroup(rows, cgroup_name):
    """특정 cgroup의 행만 필터"""
    return [r for r in rows if r.get("cgroup", "").strip() == cgroup_name]


def is_ai_workload(wl_name):
    """AI 워크로드 여부 확인"""
    if wl_name is None:
        return False
    return any(tag in wl_name for tag in ["YOLO", "PyTorch", "ResNet", "GPT"])


def process_data(data_dir, rpict_data, phases=None):
    """Phase 3 데이터 처리"""
    if phases is None:
        phases = PHASES_ALL
    system_rows = []
    workload_rows = []

    for phase_name, phase_type, wl_a, wl_b, concurrent_type in phases:
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
        gpu0_util = avg(host_stable, "gpu0_util_pct")
        gpu1_util = avg(host_stable, "gpu1_util_pct")

        # Memory Power: 0.2 W/GB × 32GB = 6.4W
        mem_power = 0.2 * 32  # 6.4W

        gpu0_r = round(gpu0_power, 2)
        gpu1_r = round(gpu1_power, 2)
        gpu_total_r = round(gpu0_r + gpu1_r, 2)

        # GPU 할당 노트
        if concurrent_type == "ai_ai":
            gpu_note = f"AI+AI: {wl_a}→GPU0, {wl_b}→GPU1"
        elif concurrent_type == "ai_b2":
            gpu_note = f"AI+B2: {wl_a}→GPU0, {wl_b}→CPU_only(GPU1_idle)"
        elif phase_type == "solo" and is_ai_workload(wl_a):
            gpu_note = f"Solo_AI: {wl_a}→GPU0, GPU1_idle"
        elif phase_type == "solo":
            gpu_note = f"Solo_CPU: {wl_a}→CPU_only, GPU0+GPU1_idle"
        else:
            gpu_note = "idle: GPU0+GPU1_idle"

        # Others = Wall - CPU - GPU0 - GPU1 - Memory
        component_sum = cpu_power + gpu0_r + gpu1_r + mem_power
        others_power = wall_power - component_sum

        # 시스템 행
        sys_row = {
            "round": "fixed",
            "experiment": phase_name,
            "type": phase_type,
            "concurrent_type": concurrent_type or "-",
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
            "others_W": f"{others_power:.2f}",
            "component_sum_W": f"{component_sum:.2f}",
            "memory_power_note": "calculated:0.2W/GB×32GB",
            "others_note": "wall-(cpu+gpu0+gpu1+memory):PSU_loss+VRM+fans+motherboard",
            "gpu_note": gpu_note,
        }
        system_rows.append(sys_row)

        # cgroup 데이터 (워크로드별)
        if cgroup_file.exists() and phase_type != "idle":
            cg_raw = read_csv_rows(cgroup_file)
            cg_stable = get_stable_range(cg_raw)

            workloads_info = []

            if phase_type == "solo":
                if is_ai_workload(wl_a):
                    # Solo AI → yolo.slice, GPU0
                    workloads_info = [(wl_a, "yolo.slice", "GPU0", 1)]
                else:
                    # Solo B2 → nodejs.slice, no GPU
                    workloads_info = [(wl_a, "nodejs.slice", "GPU1(idle)", 0)]

            elif phase_type == "concurrent":
                if concurrent_type == "ai_b2":
                    # AI → yolo.slice(GPU0), B2 → nodejs.slice(GPU1 idle)
                    workloads_info = [
                        (wl_a, "yolo.slice", "GPU0", 1),
                        (wl_b, "nodejs.slice", "GPU1(idle)", 0),
                    ]
                elif concurrent_type == "ai_ai":
                    # AI_A → yolo.slice(GPU0), AI_B → nodejs.slice(GPU1)
                    workloads_info = [
                        (wl_a, "yolo.slice", "GPU0", 1),
                        (wl_b, "nodejs.slice", "GPU1", 1),
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
                # GPU 물리 분리: yolo.slice → GPU0, nodejs.slice → GPU1
                if "yolo" in cg_name:
                    gpu_util = gpu0_util
                    gpu_pw = gpu0_power
                else:
                    gpu_util = gpu1_util
                    gpu_pw = gpu1_power

                # 동시실행 상대 워크로드
                if phase_type == "concurrent":
                    co_wl = wl_b if wl_name == wl_a else wl_a
                else:
                    co_wl = "-"

                wl_row = {
                    "round": "fixed",
                    "experiment": phase_name,
                    "type": phase_type,
                    "concurrent_type": concurrent_type or "-",
                    "workload": wl_name,
                    "co_workload": co_wl,
                    "cgroup": cg_name,
                    "cpu_util_pct": f"{cpu_util:.1f}",
                    "gpu_util_pct": f"{gpu_util:.1f}",
                    "gpu_power_W": f"{gpu_pw:.2f}",
                    "gpu0_util_pct": f"{gpu0_util:.1f}",
                    "gpu0_power_W": f"{gpu0_power:.2f}",
                    "gpu1_util_pct": f"{gpu1_util:.1f}",
                    "gpu1_power_W": f"{gpu1_power:.2f}",
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
    parser = argparse.ArgumentParser(description="Phase 3 데이터 추출")
    parser.add_argument("--run", default=None,
                        help="Run ID (예: run3, run4). 미지정 시 기존 phase3_fixed 사용")
    parser.add_argument("--no-pt", action="store_true",
                        help="PyTorch 제외 (phase3_nopt_runN 디렉토리 사용)")
    args = parser.parse_args()

    run_id = args.run
    no_pt  = args.no_pt

    # ── RPICT 파일 결정 ──
    if run_id is None:
        # 기본: run1 (기존 두 파일 병합)
        rpict_files = [
            BASE / "data/raw/rpict/phase3.csv",
            BASE / "data/raw/rpict/phase3-rerun.csv",
        ]
    else:
        rpict_files = [BASE / f"data/raw/rpict/phase3_{run_id}.csv"]

    # ── 데이터 디렉토리 결정 ──
    if run_id is None:
        data_dir = BASE / "data/raw/alienware/phase3_fixed"
    elif no_pt:
        data_dir = BASE / f"data/raw/alienware/phase3_nopt_{run_id}"
    else:
        data_dir = BASE / f"data/raw/alienware/phase3_fixed_{run_id}"

    # ── 출력 파일 접미사 ──
    if run_id is None:
        suffix = ""
    elif no_pt:
        suffix = f"_nopt_{run_id}"
    else:
        suffix = f"_{run_id}"

    # ── Phase 목록 ──
    phases = PHASES_NOPT if no_pt else PHASES_ALL

    print("=== Phase 3 데이터 추출 (다중 AI 워크로드 확장) ===")
    print(f"  Run: {run_id or '(기본 run1)'}  |  PyTorch 제외: {no_pt}")
    print(f"  Data dir: {data_dir}")
    print(f"  Phases: {len(phases)}")
    print()

    # ── RPICT 로드 ──
    rpict_data = []
    for rpict_file in rpict_files:
        if not rpict_file.exists():
            print(f"[WARN] RPICT 파일 없음: {rpict_file}")
            continue
        rows = read_csv_rows(rpict_file)
        for r in rows:
            rpict_data.append({
                "timestamp": parse_ts(r["timestamp"]),
                "wall_power_w": float(r["power1_w"]),
            })
        print(f"  RPICT 로드: {rpict_file.name} ({len(rows)}개 샘플)")
    if not rpict_data:
        print("[WARN] RPICT 데이터 없음. Wall power는 0.0으로 표시됩니다.")
    rpict_data.sort(key=lambda x: x["timestamp"])
    if rpict_data:
        print(f"RPICT 데이터: {len(rpict_data)}개 샘플 로드")

    print(f"\n--- Data directory: {data_dir} ---")
    if not data_dir.exists():
        print(f"[ERROR] 데이터 디렉토리가 없습니다: {data_dir}")
        if no_pt:
            print("        먼저 run_experiment_phase3_nopt.sh를 실행하세요.")
        else:
            print("        먼저 run_experiment_phase3.sh를 실행하세요.")
        return

    sys_rows, wl_rows = process_data(data_dir, rpict_data, phases)
    print(f"  시스템 행: {len(sys_rows)}, 워크로드 행: {len(wl_rows)}")

    # TSV 출력
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    sys_cols = [
        "round", "experiment", "type", "concurrent_type",
        "workload_A", "workload_B",
        "duration_s", "wall_power_W", "cpu_power_W",
        "gpu0_power_W", "gpu1_power_W", "gpu_total_W",
        "gpu0_util_pct", "gpu1_util_pct",
        "memory_power_W", "others_W", "component_sum_W",
        "memory_power_note", "others_note", "gpu_note",
    ]
    sys_file = OUTPUT_DIR / f"system_power{suffix}.tsv"
    write_tsv(sys_file, sys_rows, sys_cols)
    print(f"\n[출력] {sys_file}")

    wl_cols = [
        "round", "experiment", "type", "concurrent_type",
        "workload", "co_workload", "cgroup",
        "cpu_util_pct", "gpu_util_pct", "gpu_power_W",
        "gpu0_util_pct", "gpu0_power_W", "gpu1_util_pct", "gpu1_power_W",
        "cpu_alloc_cores", "gpu_alloc", "gpu_alloc_cards",
        "mem_alloc_GB", "mem_used_MB",
        "io_read_MB", "io_write_MB", "io_total_MB",
        "duration_s",
    ]
    wl_file = OUTPUT_DIR / f"workload_usage{suffix}.tsv"
    write_tsv(wl_file, wl_rows, wl_cols)
    print(f"[출력] {wl_file}")

    # 콘솔 미리보기
    print("\n\n===== system_power.tsv 미리보기 =====")
    header = ["experiment", "type", "conc_type", "dur(s)", "wall_W",
              "cpu_W", "gpu0_W", "gpu1_W", "gpu_tot_W", "mem_W",
              "others_W", "comp_sum"]
    print("\t".join(header))
    print("-" * 160)
    for r in sys_rows:
        print("\t".join([
            r["experiment"], r["type"], r["concurrent_type"],
            r["duration_s"], r["wall_power_W"], r["cpu_power_W"],
            r["gpu0_power_W"], r["gpu1_power_W"], r["gpu_total_W"],
            r["memory_power_W"], r["others_W"], r["component_sum_W"],
        ]))

    print("\n\n===== workload_usage.tsv 미리보기 =====")
    header2 = ["experiment", "workload", "co_workload", "cgroup",
               "cpu%", "gpu%", "gpu_W",
               "gpu0_%", "gpu0_W", "gpu1_%", "gpu1_W",
               "io_MB", "dur(s)"]
    print("\t".join(header2))
    print("-" * 160)
    for r in wl_rows:
        print("\t".join([
            r["experiment"], r["workload"], r["co_workload"], r["cgroup"],
            r["cpu_util_pct"], r["gpu_util_pct"], r["gpu_power_W"],
            r["gpu0_util_pct"], r["gpu0_power_W"],
            r["gpu1_util_pct"], r["gpu1_power_W"],
            r["io_total_MB"], r["duration_s"],
        ]))

    # 참고 사항
    print("\n\n===== 참고 사항 =====")
    print("Storage I/O 에너지: ~2.56 J/GB (write 2.39, read 2.75 — GPU delta 제거, ×1024)")
    print("Memory Power: 0.2 W/GB (데이터시트 기준)")
    print("GPU: RTX 3060 × 2장")
    print("  AI+B2: AI→GPU0(연산), GPU1(idle hidden power)")
    print("  AI+AI: AI_A→GPU0, AI_B→GPU1 (양쪽 모두 연산)")
    print("CPU: i7-11700KF, cgroup cpuset 2코어씩 할당")
    print("  Fixed: no_turbo=1, performance governor, 3.6GHz 고정")
    print()

    # 검증 요약
    print("===== 검증 체크리스트 =====")
    ai_solos = [r for r in sys_rows if r["type"] == "solo"
                and r["experiment"] != "B2_nodejs_heavy"]
    for r in ai_solos:
        gpu0_u = float(r["gpu0_util_pct"])
        status = "OK" if gpu0_u > 0 else "WARN"
        print(f"  [{status}] {r['experiment']}: GPU0 util = {r['gpu0_util_pct']}%")

    ai_ai_pairs = [r for r in sys_rows if r.get("concurrent_type") == "ai_ai"]
    for r in ai_ai_pairs:
        gpu0_u = float(r["gpu0_util_pct"])
        gpu1_u = float(r["gpu1_util_pct"])
        status = "OK" if gpu0_u > 0 and gpu1_u > 0 else "WARN"
        print(f"  [{status}] {r['experiment']}: GPU0={r['gpu0_util_pct']}%, GPU1={r['gpu1_util_pct']}%")


if __name__ == "__main__":
    main()
