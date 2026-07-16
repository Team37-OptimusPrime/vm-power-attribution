#!/usr/bin/env python3
"""3-way / 4-way 동시실행 실험 (phase3_3way) 데이터 추출 → TSV

산출물 3종:
  1) system_power_3way_run{N}.tsv   — 기존 스프레드시트 형식 (workload_C/D 컬럼 확장)
  2) workload_usage_3way_run{N}.tsv — 워크로드(cgroup)별 자원 사용량
  3) validation_3way_run{N}.tsv     — 귀속 검증: concurrent 귀속 전력 vs solo 실측 (오차%)

귀속 모델 (논문 III장):
  CPU  : (RAPL - idle) × util_i / Σutil        (cgroup cpu_percent 비례)
  GPU  : 점유 디바이스의 (P_dev - P_dev_idle)   (dedicated GPU → 전액 귀속)
  MEM  : 0.2 W/GB × 할당 4GB = 0.8 W           (할당 비례)
  STO  : 무시 (본 실험 워크로드의 I/O는 수 MB 수준 — β=2.5 J/GB 기준 <0.01W)

Usage:
  python3 extract_3way_data.py --run 1
  python3 extract_3way_data.py --run 1 --data-root /path/to/revision-2026  # 데이터 위치 오버라이드
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

TRIM_START = 15
TRIM_END   = 5

MEM_W_PER_GB   = 0.2
MEM_TOTAL_GB   = 32
MEM_ALLOC_GB   = 4          # 워크로드당 할당
MEM_W_ALLOC    = MEM_W_PER_GB * MEM_ALLOC_GB   # 0.8 W

# (prefix, type, workloads) — workloads: (이름, cgroup, gpu 디바이스 or None)
PHASES = [
    ("baseline",    "idle", []),
    ("solo_yolo",   "solo", [("A2(YOLO_Medium)", "yolo.slice", 0)]),
    ("solo_resnet", "solo", [("RN(ResNet18)",    "yolo.slice", 0)]),
    ("solo_nodejs", "solo", [("B2(Node_Heavy)",  "work.slice", None)]),
    ("solo_gpt2",   "solo", [("GPT(GPT-2)",      "yolo.slice", 0)]),
    ("solo_ffmpeg", "solo", [("FF(ffmpeg_x264)", "work.slice", None)]),
    # GPU1 배치 solo (run2+): concurrent와 동일 디바이스 기준값 — GPU0/GPU1
    # 전력 비대칭(동일 ResNet이 GPU0 141W vs GPU1 163W)을 검증에서 제거
    ("solo_resnet_gpu1", "solo", [("RN(ResNet18)", "nodejs.slice", 1)]),
    ("solo_gpt2_gpu1",   "solo", [("GPT(GPT-2)",   "nodejs.slice", 1)]),
    ("case1_yolo_resnet_nodejs", "concurrent", [
        ("A2(YOLO_Medium)", "yolo.slice",   0),
        ("RN(ResNet18)",    "nodejs.slice", 1),
        ("B2(Node_Heavy)",  "work.slice",   None)]),
    ("case2_yolo_gpt2_ffmpeg", "concurrent", [
        ("A2(YOLO_Medium)", "yolo.slice",   0),
        ("GPT(GPT-2)",      "nodejs.slice", 1),
        ("FF(ffmpeg_x264)", "work.slice",   None)]),
    ("case3_yolo_gpt2_nodejs_ffmpeg", "concurrent", [
        ("A2(YOLO_Medium)", "yolo.slice",   0),
        ("GPT(GPT-2)",      "nodejs.slice", 1),
        ("B2(Node_Heavy)",  "work.slice",   None),
        ("FF(ffmpeg_x264)", "work2.slice",  None)]),
]

# solo 기준값 매핑: (워크로드 이름, 배치 GPU) → solo phase prefix.
# 디바이스 일치 solo가 있으면 우선 사용 (없으면 GPU0 solo로 폴백 + 경고)
SOLO_OF = {
    ("A2(YOLO_Medium)", 0):    "solo_yolo",
    ("RN(ResNet18)", 0):       "solo_resnet",
    ("RN(ResNet18)", 1):       "solo_resnet_gpu1",
    ("GPT(GPT-2)", 0):         "solo_gpt2",
    ("GPT(GPT-2)", 1):         "solo_gpt2_gpu1",
    ("B2(Node_Heavy)", None):  "solo_nodejs",
    ("FF(ffmpeg_x264)", None): "solo_ffmpeg",
}
SOLO_FALLBACK = {   # 디바이스 일치 solo가 없는 run1용 폴백
    ("RN(ResNet18)", 1): "solo_resnet",
    ("GPT(GPT-2)", 1):   "solo_gpt2",
}

CPUSET = {"yolo.slice": "0-1", "nodejs.slice": "2-3",
          "work.slice": "4-5", "work2.slice": "6-7"}


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


def total_io_mb(rows, col):
    tot = 0.0
    for i in range(1, len(rows)):
        dt = (parse_ts(rows[i]["timestamp"]) - parse_ts(rows[i-1]["timestamp"])).total_seconds()
        try:
            tot += float(rows[i][col]) * dt
        except (ValueError, KeyError):
            pass
    return tot / 1024.0


def filter_cgroup(rows, name):
    return [r for r in rows if r.get("cgroup", "").strip() == name]


def load_rpict(path):
    if not path.exists():
        print(f"[WARN] RPICT 파일 없음: {path} — wall_power_W는 0으로 기록됨")
        return []
    data = []
    for r in read_csv_rows(path):
        try:
            data.append({"ts": parse_ts(r["timestamp"]), "w": float(r["power1_w"])})
        except (ValueError, KeyError):
            pass
    data.sort(key=lambda x: x["ts"])
    print(f"  RPICT 로드: {path.name} ({len(data)}개 샘플)")
    return data


def rpict_avg(rpict, t0, t1):
    vals = [r["w"] for r in rpict if t0 <= r["ts"] <= t1]
    return sum(vals) / len(vals) if vals else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="1")
    ap.add_argument("--data-root", default=None,
                    help="데이터 루트 (기본: repo — data/raw/... 하위 구조 가정)")
    ap.add_argument("--out-dir", default=None,
                    help="TSV 출력 디렉토리 (기본: <root>/reports/phase3_3way)")
    args = ap.parse_args()
    run = args.run

    root = Path(args.data_root) if args.data_root else REPO
    data_dir = root / f"data/raw/alienware/phase3_3way_run{run}"
    rpict_fp = root / f"data/raw/rpict/phase3_3way_run{run}.csv"
    out_dir  = Path(args.out_dir) if args.out_dir else root / "reports/phase3_3way"
    run_label = f"3way_run{run}"

    print(f"=== 3-way/4-way 데이터 추출 (run{run}) ===")
    print(f"  Data : {data_dir}")
    if not data_dir.exists():
        print("[ERROR] 데이터 디렉토리 없음"); return

    rpict = load_rpict(rpict_fp)

    # ── 1패스: phase별 시스템 지표 수집 ────────────────────────────
    metrics = {}   # prefix → dict
    for prefix, ptype, wls in PHASES:
        host_f = data_dir / f"{prefix}_host.csv"
        if not host_f.exists():
            print(f"  [SKIP] {prefix}"); continue
        host = get_stable(read_csv_rows(host_f))
        if not host:
            print(f"  [WARN] {prefix}: 안정 구간 없음"); continue
        t0, t1 = parse_ts(host[0]["timestamp"]), parse_ts(host[-1]["timestamp"])

        cg_f = data_dir / f"{prefix}_cgroup.csv"
        cg = get_stable(read_csv_rows(cg_f)) if cg_f.exists() else []

        metrics[prefix] = {
            "type": ptype, "wls": wls,
            "dur": (t1 - t0).total_seconds(),
            "wall": rpict_avg(rpict, t0, t1),
            "cpu": avg(host, "rapl_package_w"),
            "gpu0": avg(host, "gpu0_power_w"), "gpu1": avg(host, "gpu1_power_w"),
            "gpu0_util": avg(host, "gpu0_util_pct"), "gpu1_util": avg(host, "gpu1_util_pct"),
            "cg": cg,
        }

    if "baseline" not in metrics:
        print("[ERROR] baseline 없음 — 귀속 계산 불가"); return
    B = metrics["baseline"]
    cpu_idle, gpu_idle = B["cpu"], {0: B["gpu0"], 1: B["gpu1"]}

    def cg_util(prefix, slice_name):
        return avg(filter_cgroup(metrics[prefix]["cg"], slice_name), "cpu_percent")

    def gpu_active(prefix, dev):
        if dev is None:
            return 0.0
        return metrics[prefix][f"gpu{dev}"] - gpu_idle[dev]

    # solo 기준값: 워크로드 유발 전력 = CPU_active(전액) + GPU_active(자기 디바이스) + MEM_alloc
    # 키: (워크로드, 배치 GPU) — 디바이스 일치 solo 우선, 없으면 GPU0 solo 폴백 + 경고
    def make_ref(solo_prefix, matched):
        m = metrics[solo_prefix]
        _, _, dev = m["wls"][0]
        cpu = m["cpu"] - cpu_idle
        gpu = gpu_active(solo_prefix, dev)
        return {"cpu": cpu, "gpu": gpu, "mem": MEM_W_ALLOC,
                "total": cpu + gpu + MEM_W_ALLOC,
                "src": solo_prefix, "device_matched": matched}

    solo_ref = {}
    for key, solo_prefix in SOLO_OF.items():
        if solo_prefix in metrics:
            solo_ref[key] = make_ref(solo_prefix, matched=True)
    for key, fb_prefix in SOLO_FALLBACK.items():
        if key not in solo_ref and fb_prefix in metrics:
            solo_ref[key] = make_ref(fb_prefix, matched=False)
            print(f"  [WARN] {key[0]}@GPU{key[1]}: 디바이스 일치 solo 없음 → {fb_prefix}(GPU0) 폴백")

    # ── 출력 행 구성 ────────────────────────────────────────────
    sys_rows, wl_rows, val_rows = [], [], []

    for prefix, ptype, wls in PHASES:
        if prefix not in metrics:
            continue
        m = metrics[prefix]
        names = [w[0] for w in wls] + ["-"] * (4 - len(wls))
        ai_n    = sum(1 for w in wls if w[2] is not None)
        nonai_n = len(wls) - ai_n

        conc_type = "-"
        if ptype == "concurrent":
            conc_type = f"{len(wls)}way_" + ("ai_ai_nonai" if len(wls) == 3 else "ai_ai_nonai_nonai")

        mem_w    = MEM_W_PER_GB * MEM_TOTAL_GB   # 시스템 전체 (기존 형식과 동일)
        comp_sum = m["cpu"] + m["gpu0"] + m["gpu1"] + mem_w
        cpusets  = " | ".join(f"{w[0].split('(')[0]}={CPUSET[w[1]]}/4GB" for w in wls) if wls else "-"

        gpu_note = ", ".join(
            f"{w[0].split('(')[0]}→GPU{w[2]}" if w[2] is not None else f"{w[0].split('(')[0]}→CPU_only"
            for w in wls) if wls else "idle: GPU0+GPU1_idle"

        sys_rows.append({
            "run": run_label, "ratio": "equal", "experiment": prefix, "type": ptype,
            "concurrent_type": conc_type,
            "workload_A": names[0], "workload_B": names[1],
            "workload_C": names[2], "workload_D": names[3],
            "ai_cores":  str(2 * ai_n)    if wls else "-",
            "nonai_cores": str(2 * nonai_n) if wls else "-",
            "ai_mem_GB": str(4 * ai_n)    if wls else "-",
            "nonai_mem_GB": str(4 * nonai_n) if wls else "-",
            "duration_s": f"{m['dur']:.1f}",
            "wall_power_W": f"{m['wall']:.2f}",
            "cpu_power_W": f"{m['cpu']:.2f}",
            "gpu0_power_W": f"{m['gpu0']:.2f}", "gpu1_power_W": f"{m['gpu1']:.2f}",
            "gpu_total_W": f"{m['gpu0'] + m['gpu1']:.2f}",
            "gpu0_util_pct": f"{m['gpu0_util']:.1f}", "gpu1_util_pct": f"{m['gpu1_util']:.1f}",
            "memory_power_W": f"{mem_w:.1f}",
            "others_W": f"{m['wall'] - comp_sum:.2f}",
            "component_sum_W": f"{comp_sum:.2f}",
            "memory_power_note": "calculated:0.2W/GB×32GB",
            "others_note": "wall-(cpu+gpu0+gpu1+memory):PSU_loss+VRM+fans+motherboard",
            "ratio_note": cpusets,
            "gpu_note": gpu_note,
        })

        # workload_usage + 귀속 검증
        if ptype == "idle":
            continue
        utils = {w[1]: cg_util(prefix, w[1]) for w in wls}
        sum_util = sum(utils.values()) or 1.0
        cpu_active = m["cpu"] - cpu_idle

        for wl_name, cgname, dev in wls:
            cg_rows = filter_cgroup(m["cg"], cgname)
            io_r = total_io_mb(cg_rows, "io_read_kbs")
            io_w = total_io_mb(cg_rows, "io_write_kbs")
            wl_rows.append({
                "run": run_label, "ratio": "equal", "experiment": prefix, "type": ptype,
                "concurrent_type": conc_type,
                "workload": wl_name,
                "co_workload": "+".join(n for n in [w[0] for w in wls] if n != wl_name) or "-",
                "cgroup": cgname,
                "cpu_util_pct": f"{utils[cgname]:.1f}",
                "gpu_util_pct": f"{m[f'gpu{dev}_util']:.1f}" if dev is not None else "0.0",
                "gpu_power_W": f"{m[f'gpu{dev}']:.2f}" if dev is not None else "0.00",
                "gpu0_util_pct": f"{m['gpu0_util']:.1f}", "gpu0_power_W": f"{m['gpu0']:.2f}",
                "gpu1_util_pct": f"{m['gpu1_util']:.1f}", "gpu1_power_W": f"{m['gpu1']:.2f}",
                "cpu_alloc_cores": "2",
                "gpu_alloc": f"GPU{dev}" if dev is not None else "none",
                "mem_alloc_GB": str(MEM_ALLOC_GB),
                "mem_used_MB": f"{avg(cg_rows, 'memory_mb'):.1f}",
                "io_read_MB": f"{io_r:.1f}", "io_write_MB": f"{io_w:.1f}",
                "io_total_MB": f"{io_r + io_w:.1f}",
                "duration_s": f"{m['dur']:.1f}",
            })

            # 귀속 검증 (concurrent만) — 디바이스 일치 solo 기준
            ref_key = (wl_name, dev)
            if ptype == "concurrent" and ref_key in solo_ref:
                attr_cpu = cpu_active * utils[cgname] / sum_util
                attr_gpu = gpu_active(prefix, dev)
                attr = attr_cpu + attr_gpu + MEM_W_ALLOC
                sref = solo_ref[ref_key]
                ref = sref["total"]
                err = attr - ref
                val_rows.append({
                    "run": run_label, "experiment": prefix,
                    "n_workloads": str(len(wls)),
                    "workload": wl_name, "cgroup": cgname,
                    "solo_measured_W": f"{ref:.2f}",
                    "attributed_W": f"{attr:.2f}",
                    "attr_cpu_W": f"{attr_cpu:.2f}",
                    "attr_gpu_W": f"{attr_gpu:.2f}",
                    "attr_mem_W": f"{MEM_W_ALLOC:.2f}",
                    "error_W": f"{err:+.2f}",
                    "error_pct": f"{err / ref * 100:+.1f}" if ref > 0 else "-",
                    "solo_source": sref["src"],
                    "device_matched": "Y" if sref["device_matched"] else "N(GPU0폴백)",
                })

    # ── TSV 출력 ─────────────────────────────────────────────
    os.makedirs(out_dir, exist_ok=True)
    SYS_COLS = ["run", "ratio", "experiment", "type", "concurrent_type",
                "workload_A", "workload_B", "workload_C", "workload_D",
                "ai_cores", "nonai_cores", "ai_mem_GB", "nonai_mem_GB",
                "duration_s", "wall_power_W", "cpu_power_W",
                "gpu0_power_W", "gpu1_power_W", "gpu_total_W",
                "gpu0_util_pct", "gpu1_util_pct",
                "memory_power_W", "others_W", "component_sum_W",
                "memory_power_note", "others_note", "ratio_note", "gpu_note"]
    WL_COLS = ["run", "ratio", "experiment", "type", "concurrent_type",
               "workload", "co_workload", "cgroup",
               "cpu_util_pct", "gpu_util_pct", "gpu_power_W",
               "gpu0_util_pct", "gpu0_power_W", "gpu1_util_pct", "gpu1_power_W",
               "cpu_alloc_cores", "gpu_alloc", "mem_alloc_GB",
               "mem_used_MB", "io_read_MB", "io_write_MB", "io_total_MB", "duration_s"]
    VAL_COLS = ["run", "experiment", "n_workloads", "workload", "cgroup",
                "solo_measured_W", "attributed_W",
                "attr_cpu_W", "attr_gpu_W", "attr_mem_W", "error_W", "error_pct",
                "solo_source", "device_matched"]

    def write_tsv(path, rows, cols):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    for name, rows, cols in [
            (f"system_power_3way_run{run}.tsv", sys_rows, SYS_COLS),
            (f"workload_usage_3way_run{run}.tsv", wl_rows, WL_COLS),
            (f"validation_3way_run{run}.tsv", val_rows, VAL_COLS)]:
        write_tsv(out_dir / name, rows, cols)
        print(f"[출력] {out_dir / name} ({len(rows)} rows)")

    # ── 콘솔 요약 ─────────────────────────────────────────────
    print("\n===== 귀속 검증: concurrent 귀속 vs solo 실측 =====")
    print(f"{'case':<34}{'workload':<20}{'solo(W)':>9}{'attr(W)':>9}{'err(W)':>9}{'err(%)':>8}")
    print("-" * 90)
    for r in val_rows:
        print(f"{r['experiment']:<34}{r['workload']:<20}{r['solo_measured_W']:>9}"
              f"{r['attributed_W']:>9}{r['error_W']:>9}{r['error_pct']:>8}")

    errs = [abs(float(r["error_pct"])) for r in val_rows if r["error_pct"] != "-"]
    if errs:
        print(f"\n  평균 |오차| = {sum(errs)/len(errs):.1f}%   최대 |오차| = {max(errs):.1f}%   (n={len(errs)})")


if __name__ == "__main__":
    main()
