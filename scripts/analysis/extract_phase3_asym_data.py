#!/usr/bin/env python3
"""비대칭 자원할당 실험 (phase3_asym) 데이터 추출 → TSV

파일 명명 규칙:
  baseline_host.csv
  solo_{wl}_1to1_host.csv
  {wl_a}_{wl_b}_{ratio}_host.csv   (ratio: 1to1 / 2to1 / 1to2)

추가 컬럼: ratio (기존 system_power_all.tsv 형식 + ratio 컬럼)
  - 1to1 : AI=2코어/4GB  | NonAI=2코어/4GB  (equal, 기존과 동일)
  - 2to1 : AI=3코어/6GB  | NonAI=1코어/2GB  (AI-heavy)
  - 1to2 : AI=1코어/2GB  | NonAI=3코어/6GB  (NonAI-heavy)

Usage:
  python3 extract_phase3_asym_data.py [--run 1]
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

BASE = Path(os.path.expanduser(
    "~/Desktop/Univ./Ewha/2025-2026 Capstone PJT/vm-power-attribution"))
OUTPUT_DIR = BASE / "reports/phase3"

# (file_prefix, phase_type, concurrent_type, wl_a, wl_b, ratio,
#   ai_cores, nonai_cores, ai_mem_gb, nonai_mem_gb)
PHASES = [
    # Baseline
    ("baseline", "idle",       None,    None,              None,              "-",    "-", "-", "-", "-"),

    # Solo (1:1 기준으로만 측정)
    ("solo_yolo_1to1",   "solo", None, "A2(YOLO_Medium)",  None,              "1to1", "2", "-", "4", "-"),
    ("solo_resnet_1to1", "solo", None, "RN(ResNet18)",      None,              "1to1", "2", "-", "4", "-"),
    ("solo_gpt2_1to1",   "solo", None, "GPT(GPT-2)",        None,              "1to1", "2", "-", "4", "-"),
    ("solo_nodejs_1to1", "solo", None, "B2(Node_Heavy)",    None,              "1to1", "-", "2", "-", "4"),

    # YOLO + Node.js — 3 ratios
    ("yolo_nodejs_1to1", "concurrent", "ai_b2", "A2(YOLO_Medium)", "B2(Node_Heavy)", "1to1", "2", "2", "4", "4"),
    ("yolo_nodejs_2to1", "concurrent", "ai_b2", "A2(YOLO_Medium)", "B2(Node_Heavy)", "2to1", "3", "1", "6", "2"),
    ("yolo_nodejs_1to2", "concurrent", "ai_b2", "A2(YOLO_Medium)", "B2(Node_Heavy)", "1to2", "1", "3", "2", "6"),

    # ResNet + Node.js — 3 ratios
    ("resnet_nodejs_1to1", "concurrent", "ai_b2", "RN(ResNet18)", "B2(Node_Heavy)", "1to1", "2", "2", "4", "4"),
    ("resnet_nodejs_2to1", "concurrent", "ai_b2", "RN(ResNet18)", "B2(Node_Heavy)", "2to1", "3", "1", "6", "2"),
    ("resnet_nodejs_1to2", "concurrent", "ai_b2", "RN(ResNet18)", "B2(Node_Heavy)", "1to2", "1", "3", "2", "6"),

    # GPT2 + Node.js — 3 ratios
    ("gpt2_nodejs_1to1", "concurrent", "ai_b2", "GPT(GPT-2)", "B2(Node_Heavy)", "1to1", "2", "2", "4", "4"),
    ("gpt2_nodejs_2to1", "concurrent", "ai_b2", "GPT(GPT-2)", "B2(Node_Heavy)", "2to1", "3", "1", "6", "2"),
    ("gpt2_nodejs_1to2", "concurrent", "ai_b2", "GPT(GPT-2)", "B2(Node_Heavy)", "1to2", "1", "3", "2", "6"),

    # YOLO + ResNet (AI+AI) — 3 ratios
    ("yolo_resnet_1to1", "concurrent", "ai_ai", "A2(YOLO_Medium)", "RN(ResNet18)", "1to1", "2", "2", "4", "4"),
    ("yolo_resnet_2to1", "concurrent", "ai_ai", "A2(YOLO_Medium)", "RN(ResNet18)", "2to1", "3", "1", "6", "2"),
    ("yolo_resnet_1to2", "concurrent", "ai_ai", "A2(YOLO_Medium)", "RN(ResNet18)", "1to2", "1", "3", "2", "6"),
]

TRIM_START = 15
TRIM_END   = 5


def parse_ts(s):
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(f"Cannot parse: {s}")


def read_csv_rows(filepath):
    with open(filepath) as f:
        return list(csv.DictReader(f))


def get_stable(rows):
    if not rows:
        return []
    t0     = parse_ts(rows[0]["timestamp"])
    t_last = parse_ts(rows[-1]["timestamp"])
    total  = (t_last - t0).total_seconds()
    return [r for r in rows
            if TRIM_START <= (parse_ts(r["timestamp"]) - t0).total_seconds() <= total - TRIM_END]


def avg(rows, col):
    vals = []
    for r in rows:
        try:
            vals.append(float(r[col]))
        except (ValueError, KeyError):
            pass
    return sum(vals) / len(vals) if vals else 0.0


def stable_duration(rows):
    if len(rows) < 2:
        return 0.0
    return (parse_ts(rows[-1]["timestamp"]) - parse_ts(rows[0]["timestamp"])).total_seconds()


def total_io_mb(rows, col):
    total = 0.0
    for i in range(1, len(rows)):
        dt = (parse_ts(rows[i]["timestamp"]) - parse_ts(rows[i-1]["timestamp"])).total_seconds()
        try:
            total += float(rows[i][col]) * dt
        except (ValueError, KeyError):
            pass
    return total / 1024.0


def filter_cgroup(rows, name):
    return [r for r in rows if r.get("cgroup", "").strip() == name]


def get_rpict_avg(rpict, t0, t1):
    vals = [r["w"] for r in rpict if t0 <= r["ts"] <= t1]
    return sum(vals) / len(vals) if vals else 0.0


def load_rpict(path):
    if not path.exists():
        print(f"[WARN] RPICT 파일 없음: {path}")
        return []
    rows = read_csv_rows(path)
    data = []
    for r in rows:
        try:
            data.append({"ts": parse_ts(r["timestamp"]), "w": float(r["power1_w"])})
        except (ValueError, KeyError):
            pass
    data.sort(key=lambda x: x["ts"])
    print(f"  RPICT 로드: {path.name} ({len(data)}개 샘플)")
    return data


def is_ai(wl):
    return wl is not None and any(t in wl for t in ["YOLO", "ResNet", "GPT", "PyTorch"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="1", help="Run 번호 (기본: 1)")
    args = parser.parse_args()
    run_num = args.run

    data_dir   = BASE / f"data/raw/alienware/phase3_asym_run{run_num}"
    rpict_path = BASE / "data/raw/rpict/phase3_asymmetric.csv"
    run_label  = f"asym_run{run_num}"

    print(f"=== Phase3 비대칭 데이터 추출 (run{run_num}) ===")
    print(f"  Data : {data_dir}")
    print(f"  RPICT: {rpict_path}")

    if not data_dir.exists():
        print(f"[ERROR] 데이터 디렉토리 없음: {data_dir}"); return

    rpict = load_rpict(rpict_path)

    sys_rows = []
    wl_rows  = []

    for (prefix, phase_type, conc_type, wl_a, wl_b, ratio,
         ai_cores, nonai_cores, ai_mem, nonai_mem) in PHASES:

        host_f   = data_dir / f"{prefix}_host.csv"
        cgroup_f = data_dir / f"{prefix}_cgroup.csv"

        if not host_f.exists():
            print(f"  [SKIP] {prefix}")
            continue

        host_raw    = read_csv_rows(host_f)
        host_stable = get_stable(host_raw)
        if not host_stable:
            print(f"  [WARN] {prefix}: 안정 구간 없음"); continue

        dur       = stable_duration(host_stable)
        t0        = parse_ts(host_stable[0]["timestamp"])
        t1        = parse_ts(host_stable[-1]["timestamp"])
        wall_w    = get_rpict_avg(rpict, t0, t1)
        cpu_w     = avg(host_stable, "rapl_package_w")
        gpu0_w    = avg(host_stable, "gpu0_power_w")
        gpu1_w    = avg(host_stable, "gpu1_power_w")
        gpu0_util = avg(host_stable, "gpu0_util_pct")
        gpu1_util = avg(host_stable, "gpu1_util_pct")
        mem_w     = 6.4   # 0.2W/GB × 32GB
        comp_sum  = cpu_w + gpu0_w + gpu1_w + mem_w
        others_w  = wall_w - comp_sum

        # GPU note
        if conc_type == "ai_ai":
            gpu_note = f"AI+AI: {wl_a}→GPU0, {wl_b}→GPU1"
        elif conc_type == "ai_b2":
            gpu_note = f"AI+B2: {wl_a}→GPU0, {wl_b}→CPU_only(GPU1_idle)"
        elif phase_type == "solo" and is_ai(wl_a):
            gpu_note = f"Solo_AI: {wl_a}→GPU0, GPU1_idle"
        elif phase_type == "solo":
            gpu_note = f"Solo_CPU: {wl_a}→CPU_only, GPU0+GPU1_idle"
        else:
            gpu_note = "idle: GPU0+GPU1_idle"

        # ratio별 cgroup 할당 정보
        if ratio == "1to1":
            ratio_note = "AI=cpuset0-1/4GB | NonAI=cpuset2-3/4GB"
        elif ratio == "2to1":
            ratio_note = "AI=cpuset0-2/6GB | NonAI=cpuset3/2GB"
        elif ratio == "1to2":
            ratio_note = "AI=cpuset0/2GB | NonAI=cpuset1-3/6GB"
        else:
            ratio_note = "-"

        sys_rows.append({
            "run":              run_label,
            "ratio":            ratio,
            "experiment":       prefix,
            "type":             phase_type,
            "concurrent_type":  conc_type or "-",
            "workload_A":       wl_a or "-",
            "workload_B":       wl_b or "-",
            "ai_cores":         ai_cores,
            "nonai_cores":      nonai_cores,
            "ai_mem_GB":        ai_mem,
            "nonai_mem_GB":     nonai_mem,
            "duration_s":       f"{dur:.1f}",
            "wall_power_W":     f"{wall_w:.2f}",
            "cpu_power_W":      f"{cpu_w:.2f}",
            "gpu0_power_W":     f"{gpu0_w:.2f}",
            "gpu1_power_W":     f"{gpu1_w:.2f}",
            "gpu_total_W":      f"{gpu0_w + gpu1_w:.2f}",
            "gpu0_util_pct":    f"{gpu0_util:.1f}",
            "gpu1_util_pct":    f"{gpu1_util:.1f}",
            "memory_power_W":   f"{mem_w:.1f}",
            "others_W":         f"{others_w:.2f}",
            "component_sum_W":  f"{comp_sum:.2f}",
            "memory_power_note":"calculated:0.2W/GB×32GB",
            "others_note":      "wall-(cpu+gpu0+gpu1+memory):PSU_loss+VRM+fans+motherboard",
            "ratio_note":       ratio_note,
            "gpu_note":         gpu_note,
        })

        # ── workload_usage 행 ──
        if cgroup_f.exists() and phase_type != "idle":
            cg_raw    = read_csv_rows(cgroup_f)
            cg_stable = get_stable(cg_raw)

            # 워크로드별 cgroup 매핑
            if phase_type == "solo":
                if is_ai(wl_a):
                    wl_list = [(wl_a, "yolo.slice", "GPU0", gpu0_util, gpu0_w,
                                ai_cores, ai_mem)]
                else:
                    wl_list = [(wl_a, "nodejs.slice", "none", 0.0, 0.0,
                                nonai_cores, nonai_mem)]
            elif conc_type == "ai_b2":
                wl_list = [
                    (wl_a, "yolo.slice",   "GPU0",      gpu0_util, gpu0_w, ai_cores,    ai_mem),
                    (wl_b, "nodejs.slice", "none",      0.0,       0.0,    nonai_cores, nonai_mem),
                ]
            elif conc_type == "ai_ai":
                wl_list = [
                    (wl_a, "yolo.slice",   "GPU0", gpu0_util, gpu0_w, ai_cores,    ai_mem),
                    (wl_b, "nodejs.slice", "GPU1", gpu1_util, gpu1_w, nonai_cores, nonai_mem),
                ]
            else:
                wl_list = []

            for (wl_name, cg_name, gpu_assign, wl_gpu_util, wl_gpu_w,
                 alloc_cores, alloc_mem) in wl_list:
                cg_rows = filter_cgroup(cg_stable, cg_name)
                if not cg_rows:
                    continue

                cpu_util   = avg(cg_rows, "cpu_percent")
                mem_mb     = avg(cg_rows, "memory_mb")
                io_read_mb = total_io_mb(cg_rows, "io_read_kbs")
                io_wrt_mb  = total_io_mb(cg_rows, "io_write_kbs")
                co_wl      = wl_b if wl_name == wl_a else wl_a

                wl_rows.append({
                    "run":              run_label,
                    "ratio":            ratio,
                    "experiment":       prefix,
                    "type":             phase_type,
                    "concurrent_type":  conc_type or "-",
                    "workload":         wl_name,
                    "co_workload":      co_wl or "-",
                    "cgroup":           cg_name,
                    "cpu_util_pct":     f"{cpu_util:.1f}",
                    "gpu_util_pct":     f"{wl_gpu_util:.1f}",
                    "gpu_power_W":      f"{wl_gpu_w:.2f}",
                    "gpu0_util_pct":    f"{gpu0_util:.1f}",
                    "gpu0_power_W":     f"{gpu0_w:.2f}",
                    "gpu1_util_pct":    f"{gpu1_util:.1f}",
                    "gpu1_power_W":     f"{gpu1_w:.2f}",
                    "cpu_alloc_cores":  str(alloc_cores),
                    "gpu_alloc":        gpu_assign,
                    "mem_alloc_GB":     str(alloc_mem),
                    "mem_used_MB":      f"{mem_mb:.1f}",
                    "io_read_MB":       f"{io_read_mb:.1f}",
                    "io_write_MB":      f"{io_wrt_mb:.1f}",
                    "io_total_MB":      f"{io_read_mb + io_wrt_mb:.1f}",
                    "duration_s":       f"{dur:.1f}",
                })

    # ── TSV 출력 ──
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    SYS_COLS = [
        "run", "ratio", "experiment", "type", "concurrent_type",
        "workload_A", "workload_B",
        "ai_cores", "nonai_cores", "ai_mem_GB", "nonai_mem_GB",
        "duration_s", "wall_power_W", "cpu_power_W",
        "gpu0_power_W", "gpu1_power_W", "gpu_total_W",
        "gpu0_util_pct", "gpu1_util_pct",
        "memory_power_W", "others_W", "component_sum_W",
        "memory_power_note", "others_note", "ratio_note", "gpu_note",
    ]
    WL_COLS = [
        "run", "ratio", "experiment", "type", "concurrent_type",
        "workload", "co_workload", "cgroup",
        "cpu_util_pct", "gpu_util_pct", "gpu_power_W",
        "gpu0_util_pct", "gpu0_power_W", "gpu1_util_pct", "gpu1_power_W",
        "cpu_alloc_cores", "gpu_alloc", "mem_alloc_GB",
        "mem_used_MB", "io_read_MB", "io_write_MB", "io_total_MB",
        "duration_s",
    ]

    sys_tsv = OUTPUT_DIR / f"system_power_asym_run{run_num}.tsv"
    wl_tsv  = OUTPUT_DIR / f"workload_usage_asym_run{run_num}.tsv"

    def write_tsv(path, rows, cols):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    write_tsv(sys_tsv, sys_rows, SYS_COLS)
    write_tsv(wl_tsv,  wl_rows,  WL_COLS)
    print(f"\n[출력] {sys_tsv}  ({len(sys_rows)} rows)")
    print(f"[출력] {wl_tsv}  ({len(wl_rows)} rows)")

    # ── 콘솔 미리보기 ──
    print("\n===== system_power_asym 미리보기 =====")
    hdr = ["ratio", "experiment", "dur(s)", "wall_W", "cpu_W",
           "gpu0_W", "gpu1_W", "gpu0_%", "gpu1_%", "others_W"]
    print("\t".join(hdr))
    print("-" * 120)
    for r in sys_rows:
        print("\t".join([
            r["ratio"], r["experiment"], r["duration_s"],
            r["wall_power_W"], r["cpu_power_W"],
            r["gpu0_power_W"], r["gpu1_power_W"],
            r["gpu0_util_pct"], r["gpu1_util_pct"],
            r["others_W"],
        ]))

    # ── 핵심 분석: 비율별 wall power 변화 ──
    print("\n===== 비율별 Wall Power 비교 (핵심 분석) =====")
    pairs = [
        ("yolo_nodejs",   "YOLO+Node.js"),
        ("resnet_nodejs", "ResNet+Node.js"),
        ("gpt2_nodejs",   "GPT2+Node.js"),
        ("yolo_resnet",   "YOLO+ResNet"),
    ]
    print(f"{'Pair':<22} {'1:1(W)':>8} {'2:1(W)':>8} {'1:2(W)':>8} {'Δmax(W)':>9} {'Δmax(%)':>9}")
    print("-" * 70)
    for key, label in pairs:
        vals = {}
        for r in sys_rows:
            if r["experiment"].startswith(key) and r["type"] == "concurrent":
                vals[r["ratio"]] = float(r["wall_power_W"])
        if len(vals) == 3:
            v = [vals.get("1to1",0), vals.get("2to1",0), vals.get("1to2",0)]
            delta = max(v) - min(v)
            pct   = delta / min(v) * 100 if min(v) > 0 else 0
            print(f"{label:<22} {v[0]:>8.2f} {v[1]:>8.2f} {v[2]:>8.2f} {delta:>9.2f} {pct:>8.1f}%")

    # ── Solo vs Concurrent 비교 ──
    print("\n===== Solo vs Concurrent (1:1 equal, 기존 실험과 비교) =====")
    solo_map = {}
    for r in sys_rows:
        if r["type"] == "solo" and r["ratio"] == "1to1":
            solo_map[r["workload_A"]] = float(r["wall_power_W"])

    print(f"{'Workload':<20} {'Solo(W)':>8} {'Concurrent(W)':>14} {'Diff(W)':>9}")
    print("-" * 55)
    for r in sys_rows:
        if r["type"] == "concurrent" and r["ratio"] == "1to1":
            wla = r["workload_A"]
            wlb = r["workload_B"]
            conc_w = float(r["wall_power_W"])
            solo_a = solo_map.get(wla, 0)
            solo_b = solo_map.get(wlb, 0)
            diff   = conc_w - (solo_a + solo_b)
            print(f"{r['experiment']:<20} ({solo_a:.1f}+{solo_b:.1f}) → {conc_w:>6.2f}  diff={diff:+.2f}")

    print("\n===== 검증 =====")
    for r in sys_rows:
        if r["type"] == "solo" and is_ai(r["workload_A"]):
            ok = "OK" if float(r["gpu0_util_pct"]) > 10 else "WARN"
            print(f"  [{ok}] {r['experiment']}: GPU0 util={r['gpu0_util_pct']}%")
    for r in sys_rows:
        if r.get("concurrent_type") == "ai_ai":
            ok = "OK" if float(r["gpu0_util_pct"]) > 10 and float(r["gpu1_util_pct"]) > 10 else "WARN"
            print(f"  [{ok}] {r['experiment']} [{r['ratio']}]: GPU0={r['gpu0_util_pct']}%, GPU1={r['gpu1_util_pct']}%")


if __name__ == "__main__":
    main()
