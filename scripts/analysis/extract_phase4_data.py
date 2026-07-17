#!/usr/bin/env python3
"""Phase 4 워크로드 확장 실험 데이터 추출 → TSV

신규 워크로드 4종(ResNet-CPU / ffmpeg / stress-ng / fio) + 기존 GPU-AI 2종의
solo 에너지 구조와, 신규 자원조합 concurrent 쌍 4개의 귀속 검증을 산출한다.

산출물:
  1) system_power_phase4_run{N}.tsv   — 스프레드시트 형식 (3-way와 동일 스키마)
  2) workload_usage_phase4_run{N}.tsv — 워크로드(cgroup)별 자원 사용량
  3) validation_phase4_run{N}.tsv     — 귀속 검증 (성분 분해 + 오차%)

귀속 모델 (논문 III장):
  CPU  : (RAPL - idle) × util_i / Σutil
  GPU  : 점유 디바이스의 (P_dev - P_dev_idle)  — phase4는 solo/concurrent 모두 GPU0
  MEM  : 0.2 W/GB × 할당 4GB = 0.8 W
  STO  : β 2.5 J/GB × I/O rate(GB/s)          — fio 워크로드에 적용

Usage:
  python3 extract_phase4_data.py --run 1 [--data-root PATH] [--out-dir PATH]
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

TRIM_START = 15
TRIM_END   = 5
MEM_W_ALLOC   = 0.2 * 4      # 0.8 W (할당 4GB)
MEM_W_SYSTEM  = 0.2 * 32     # 6.4 W (시스템 표기용)
STORAGE_BETA  = 2.5          # J/GB

# (prefix, type, workloads) — (이름, cgroup, gpu dev or None, io계측 여부)
PHASES = [
    ("baseline",        "idle", []),
    ("solo_resnet_cpu", "solo", [("RN-CPU(ResNet18_CPU)", "yolo.slice",   None, False)]),
    ("solo_ffmpeg",     "solo", [("FF(ffmpeg_x264)",      "yolo.slice",   None, False)]),
    ("solo_stressmem",  "solo", [("MEM(stress-ng_vm)",    "nodejs.slice", None, False)]),
    ("solo_fio_randrw", "solo", [("IO(fio_randrw)",       "nodejs.slice", None, True)]),
    ("solo_fio_bursty", "solo", [("IO(fio_bursty)",       "nodejs.slice", None, True)]),
    ("solo_nodejs",     "solo", [("B2(Node_Heavy)",       "nodejs.slice", None, False)]),
    ("solo_yolo",       "solo", [("A2(YOLO_Medium)",      "yolo.slice",   0,    False)]),
    ("solo_gpt2",       "solo", [("GPT(GPT-2)",           "yolo.slice",   0,    False)]),
    ("C1_resnetcpu_nodejs", "concurrent", [
        ("RN-CPU(ResNet18_CPU)", "yolo.slice",   None, False),
        ("B2(Node_Heavy)",       "nodejs.slice", None, False)]),
    ("C2_ffmpeg_nodejs", "concurrent", [
        ("FF(ffmpeg_x264)",      "yolo.slice",   None, False),
        ("B2(Node_Heavy)",       "nodejs.slice", None, False)]),
    ("C3_yolo_fio", "concurrent", [
        ("A2(YOLO_Medium)",      "yolo.slice",   0,    False),
        ("IO(fio_randrw)",       "nodejs.slice", None, True)]),
    ("C4_gpt2_stressmem", "concurrent", [
        ("GPT(GPT-2)",           "yolo.slice",   0,    False),
        ("MEM(stress-ng_vm)",    "nodejs.slice", None, False)]),
]

# 검증용 solo 매핑 — phase4는 solo/concurrent 배치가 동일해 폴백 불필요
SOLO_OF = {
    "RN-CPU(ResNet18_CPU)": "solo_resnet_cpu",
    "FF(ffmpeg_x264)":      "solo_ffmpeg",
    "MEM(stress-ng_vm)":    "solo_stressmem",
    "IO(fio_randrw)":       "solo_fio_randrw",
    "B2(Node_Heavy)":       "solo_nodejs",
    "A2(YOLO_Medium)":      "solo_yolo",
    "GPT(GPT-2)":           "solo_gpt2",
}

CPUSET = {"yolo.slice": "0-1", "nodejs.slice": "2-3"}
CATEGORY = {
    "RN-CPU(ResNet18_CPU)": "CPU-AI",
    "A2(YOLO_Medium)": "GPU-AI", "GPT(GPT-2)": "GPU-AI",
    "B2(Node_Heavy)": "CPU-NonAI", "FF(ffmpeg_x264)": "CPU-NonAI",
    "MEM(stress-ng_vm)": "Memory-NonAI",
    "IO(fio_randrw)": "IO-NonAI", "IO(fio_bursty)": "IO-NonAI",
}


def parse_ts(s):
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(f"Cannot parse: {s}")


def read_csv_rows(fp):
    with open(fp) as f:
        return list(csv.DictReader(f))


def get_stable(rows):
    if not rows:
        return []
    t0, t1 = parse_ts(rows[0]["timestamp"]), parse_ts(rows[-1]["timestamp"])
    total = (t1 - t0).total_seconds()
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


def filter_cgroup(rows, name):
    return [r for r in rows if r.get("cgroup", "").strip() == name]


def io_rate_mbs(rows):
    """cgroup 행들의 평균 I/O rate (MB/s, read+write)"""
    return (avg(rows, "io_read_kbs") + avg(rows, "io_write_kbs")) / 1024.0


def total_io_mb(rows, col):
    tot = 0.0
    for i in range(1, len(rows)):
        dt = (parse_ts(rows[i]["timestamp"]) - parse_ts(rows[i-1]["timestamp"])).total_seconds()
        try:
            tot += float(rows[i][col]) * dt
        except (ValueError, KeyError):
            pass
    return tot / 1024.0


def load_rpict(path):
    if not path.exists():
        print(f"[WARN] RPICT 없음: {path}")
        return []
    data = []
    for r in read_csv_rows(path):
        try:
            data.append({"ts": parse_ts(r["timestamp"]), "w": float(r["power1_w"])})
        except (ValueError, KeyError):
            pass
    data.sort(key=lambda x: x["ts"])
    return data


def rpict_avg(rpict, t0, t1):
    vals = [r["w"] for r in rpict if t0 <= r["ts"] <= t1]
    return sum(vals) / len(vals) if vals else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="1")
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    run = args.run

    root = Path(args.data_root) if args.data_root else REPO
    data_dir = root / f"data/raw/alienware/phase4_expand_run{run}"
    rpict_fp = root / f"data/raw/rpict/phase4_expand_run{run}.csv"
    out_dir  = Path(args.out_dir) if args.out_dir else root / "reports/phase4"
    run_label = f"phase4_run{run}"

    print(f"=== Phase4 데이터 추출 (run{run}) ===")
    if not data_dir.exists():
        print(f"[ERROR] 없음: {data_dir}"); return
    rpict = load_rpict(rpict_fp)

    metrics = {}
    for prefix, ptype, wls in PHASES:
        f = data_dir / f"{prefix}_host.csv"
        if not f.exists():
            print(f"  [SKIP] {prefix}"); continue
        host = get_stable(read_csv_rows(f))
        if not host:
            continue
        t0, t1 = parse_ts(host[0]["timestamp"]), parse_ts(host[-1]["timestamp"])
        cgf = data_dir / f"{prefix}_cgroup.csv"
        cg = get_stable(read_csv_rows(cgf)) if cgf.exists() else []
        metrics[prefix] = {
            "type": ptype, "wls": wls,
            "dur": (t1-t0).total_seconds(),
            "wall": rpict_avg(rpict, t0, t1),
            "cpu": avg(host, "rapl_package_w"),
            "gpu0": avg(host, "gpu0_power_w"), "gpu1": avg(host, "gpu1_power_w"),
            "gpu0_util": avg(host, "gpu0_util_pct"), "gpu1_util": avg(host, "gpu1_util_pct"),
            "cg": cg,
        }

    if "baseline" not in metrics:
        print("[ERROR] baseline 없음"); return
    B = metrics["baseline"]
    cpu_idle, gpu0_idle = B["cpu"], B["gpu0"]

    def cg_rows(prefix, s):
        return filter_cgroup(metrics[prefix]["cg"], s)

    def sto_w(prefix, s):
        """스토리지 전력: β(J/GB) × I/O rate(GB/s)"""
        return STORAGE_BETA * io_rate_mbs(cg_rows(prefix, s)) / 1024.0

    # solo 기준값
    solo_ref = {}
    for wl, sp in SOLO_OF.items():
        if sp not in metrics:
            continue
        m = metrics[sp]
        _, cgname, dev, has_io = m["wls"][0]
        cpu = m["cpu"] - cpu_idle
        gpu = (m["gpu0"] - gpu0_idle) if dev == 0 else 0.0
        sto = sto_w(sp, cgname) if has_io else 0.0
        solo_ref[wl] = {"cpu": cpu, "gpu": gpu, "sto": sto,
                        "total": cpu + gpu + MEM_W_ALLOC + sto, "src": sp}

    sys_rows, wl_rows, val_rows = [], [], []
    for prefix, ptype, wls in PHASES:
        if prefix not in metrics:
            continue
        m = metrics[prefix]
        names = [w[0] for w in wls] + ["-"] * (2 - len(wls))
        cats = "+".join(CATEGORY.get(w[0], "?") for w in wls) if wls else "-"
        comp_sum = m["cpu"] + m["gpu0"] + m["gpu1"] + MEM_W_SYSTEM
        cpusets = " | ".join(f"{w[0].split('(')[0]}={CPUSET[w[1]]}/4GB" for w in wls) if wls else "-"
        gpu_note = ", ".join(
            f"{w[0].split('(')[0]}→GPU{w[2]}" if w[2] is not None else f"{w[0].split('(')[0]}→CPU_only"
            for w in wls) if wls else "idle"

        sys_rows.append({
            "run": run_label, "ratio": "equal", "experiment": prefix, "type": ptype,
            "concurrent_type": cats if ptype == "concurrent" else "-",
            "workload_A": names[0], "workload_B": names[1],
            "workload_C": "-", "workload_D": "-",
            "ai_cores": "2" if any(CATEGORY.get(w[0],"").endswith("AI") and "NonAI" not in CATEGORY.get(w[0],"") for w in wls) else "-",
            "nonai_cores": "2" if any("NonAI" in CATEGORY.get(w[0],"") for w in wls) else "-",
            "ai_mem_GB": "4" if any(CATEGORY.get(w[0],"").endswith("AI") and "NonAI" not in CATEGORY.get(w[0],"") for w in wls) else "-",
            "nonai_mem_GB": "4" if any("NonAI" in CATEGORY.get(w[0],"") for w in wls) else "-",
            "duration_s": f"{m['dur']:.1f}",
            "wall_power_W": f"{m['wall']:.2f}",
            "cpu_power_W": f"{m['cpu']:.2f}",
            "gpu0_power_W": f"{m['gpu0']:.2f}", "gpu1_power_W": f"{m['gpu1']:.2f}",
            "gpu_total_W": f"{m['gpu0'] + m['gpu1']:.2f}",
            "gpu0_util_pct": f"{m['gpu0_util']:.1f}", "gpu1_util_pct": f"{m['gpu1_util']:.1f}",
            "memory_power_W": f"{MEM_W_SYSTEM:.1f}",
            "others_W": f"{m['wall'] - comp_sum:.2f}",
            "component_sum_W": f"{comp_sum:.2f}",
            "memory_power_note": "calculated:0.2W/GB×32GB",
            "others_note": "wall-(cpu+gpu0+gpu1+memory):PSU_loss+VRM+fans+motherboard",
            "ratio_note": cpusets,
            "gpu_note": gpu_note,
        })

        if ptype == "idle":
            continue
        utils = {w[1]: avg(cg_rows(prefix, w[1]), "cpu_percent") for w in wls}
        sum_util = sum(utils.values()) or 1.0
        cpu_active = m["cpu"] - cpu_idle

        for wl_name, cgname, dev, has_io in wls:
            rows_ = cg_rows(prefix, cgname)
            io_r = total_io_mb(rows_, "io_read_kbs")
            io_w = total_io_mb(rows_, "io_write_kbs")
            wl_rows.append({
                "run": run_label, "ratio": "equal", "experiment": prefix, "type": ptype,
                "concurrent_type": cats if ptype == "concurrent" else "-",
                "workload": wl_name,
                "co_workload": "+".join(n for n in [w[0] for w in wls] if n != wl_name) or "-",
                "cgroup": cgname,
                "cpu_util_pct": f"{utils[cgname]:.1f}",
                "gpu_util_pct": f"{m['gpu0_util']:.1f}" if dev == 0 else "0.0",
                "gpu_power_W": f"{m['gpu0']:.2f}" if dev == 0 else "0.00",
                "gpu0_util_pct": f"{m['gpu0_util']:.1f}", "gpu0_power_W": f"{m['gpu0']:.2f}",
                "gpu1_util_pct": f"{m['gpu1_util']:.1f}", "gpu1_power_W": f"{m['gpu1']:.2f}",
                "cpu_alloc_cores": "2",
                "gpu_alloc": "GPU0" if dev == 0 else "none",
                "mem_alloc_GB": "4",
                "mem_used_MB": f"{avg(rows_, 'memory_mb'):.1f}",
                "io_read_MB": f"{io_r:.1f}", "io_write_MB": f"{io_w:.1f}",
                "io_total_MB": f"{io_r + io_w:.1f}",
                "duration_s": f"{m['dur']:.1f}",
            })

            if ptype == "concurrent" and wl_name in solo_ref:
                attr_cpu = cpu_active * utils[cgname] / sum_util
                attr_gpu = (m["gpu0"] - gpu0_idle) if dev == 0 else 0.0
                attr_sto = sto_w(prefix, cgname) if has_io else 0.0
                attr = attr_cpu + attr_gpu + MEM_W_ALLOC + attr_sto
                ref = solo_ref[wl_name]["total"]
                err = attr - ref
                val_rows.append({
                    "run": run_label, "experiment": prefix, "n_workloads": str(len(wls)),
                    "workload": wl_name, "cgroup": cgname,
                    "category": CATEGORY.get(wl_name, "?"),
                    "solo_measured_W": f"{ref:.2f}", "attributed_W": f"{attr:.2f}",
                    "attr_cpu_W": f"{attr_cpu:.2f}", "attr_gpu_W": f"{attr_gpu:.2f}",
                    "attr_mem_W": f"{MEM_W_ALLOC:.2f}", "attr_sto_W": f"{attr_sto:.2f}",
                    "error_W": f"{err:+.2f}",
                    "error_pct": f"{err / ref * 100:+.1f}" if ref > 0 else "-",
                    "solo_source": solo_ref[wl_name]["src"],
                    "device_matched": "Y",
                })

    os.makedirs(out_dir, exist_ok=True)
    SYS_COLS = ["run","ratio","experiment","type","concurrent_type",
                "workload_A","workload_B","workload_C","workload_D",
                "ai_cores","nonai_cores","ai_mem_GB","nonai_mem_GB",
                "duration_s","wall_power_W","cpu_power_W",
                "gpu0_power_W","gpu1_power_W","gpu_total_W",
                "gpu0_util_pct","gpu1_util_pct",
                "memory_power_W","others_W","component_sum_W",
                "memory_power_note","others_note","ratio_note","gpu_note"]
    WL_COLS = ["run","ratio","experiment","type","concurrent_type",
               "workload","co_workload","cgroup",
               "cpu_util_pct","gpu_util_pct","gpu_power_W",
               "gpu0_util_pct","gpu0_power_W","gpu1_util_pct","gpu1_power_W",
               "cpu_alloc_cores","gpu_alloc","mem_alloc_GB",
               "mem_used_MB","io_read_MB","io_write_MB","io_total_MB","duration_s"]
    VAL_COLS = ["run","experiment","n_workloads","workload","cgroup","category",
                "solo_measured_W","attributed_W",
                "attr_cpu_W","attr_gpu_W","attr_mem_W","attr_sto_W",
                "error_W","error_pct","solo_source","device_matched"]

    def write_tsv(path, rows, cols):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    for name, rows, cols in [
            (f"system_power_phase4_run{run}.tsv", sys_rows, SYS_COLS),
            (f"workload_usage_phase4_run{run}.tsv", wl_rows, WL_COLS),
            (f"validation_phase4_run{run}.tsv", val_rows, VAL_COLS)]:
        write_tsv(out_dir / name, rows, cols)
        print(f"[출력] {out_dir / name} ({len(rows)} rows)")

    print("\n===== 9종 워크로드 에너지 구조 (solo, wall 기준) =====")
    print(f"{'workload':<24}{'category':<14}{'wall':>7}{'cpu':>7}{'gpu0':>7}{'others':>8}")
    for r in sys_rows:
        if r["type"] == "solo":
            print(f"{r['workload_A']:<24}{CATEGORY.get(r['workload_A'],'?'):<14}"
                  f"{r['wall_power_W']:>7}{r['cpu_power_W']:>7}{r['gpu0_power_W']:>7}{r['others_W']:>8}")

    print("\n===== 귀속 검증 =====")
    print(f"{'case':<22}{'workload':<24}{'solo(W)':>9}{'attr(W)':>9}{'err%':>7}")
    for r in val_rows:
        print(f"{r['experiment']:<22}{r['workload']:<24}{r['solo_measured_W']:>9}{r['attributed_W']:>9}{r['error_pct']:>7}")
    errs = [abs(float(r["error_pct"])) for r in val_rows if r["error_pct"] != "-"]
    if errs:
        print(f"\n  평균 |오차| = {sum(errs)/len(errs):.1f}%   최대 = {max(errs):.1f}%")


if __name__ == "__main__":
    main()
