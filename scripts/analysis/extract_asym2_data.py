#!/usr/bin/env python3
"""비대칭 자원할당 실험 v2 (5비율 + GPU1 solo + ffmpeg 스케일링) 추출 → TSV

2026-07 재실험 프로토콜용 (직접 cgroup 등록·cpu.max 비례·비율 assert):
  비율 5종: 1to1 / 2to1 / 1to2 / 5to1 / 1to5
  GPU1 디바이스 일치 solo (solo_resnet_gpu1_1to1)
  (옵션) ffmpeg 할당 스케일링 대조군: ffmpeg_scale_{1c,2c,5c}

산출물:
  1) system_power_asym2_run{N}.tsv   — 스프레드시트 형식
  2) workload_usage_asym2_run{N}.tsv
  3) validation_asym2_run{N}.tsv     — 귀속 검증 (디바이스 일치 기준)
  4) ffmpeg_scaling_run{N}.tsv       — 할당 스케일링 대조군 (있을 때만)

Usage:
  python3 extract_asym2_data.py --run 1 [--data-root PATH] [--out-dir PATH]
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TRIM_START, TRIM_END = 15, 5
MEM_W_PER_GB = 0.2

# ratio → (ai_cores, nonai_cores, ai_mem, nonai_mem, ai_cpuset, nonai_cpuset)
RATIOS = {
    "1to1": (2, 2, 4, 4,  "0-1", "2-3"),
    "2to1": (3, 1, 6, 2,  "0-2", "3"),
    "1to2": (1, 3, 2, 6,  "0",   "1-3"),
    "5to1": (5, 1, 10, 2, "0-4", "5"),
    "1to5": (1, 5, 2, 10, "0",   "1-5"),
}
PAIRS = [  # (prefix_base, conc_type, wl_a, wl_b, dev_b)
    ("yolo_nodejs",   "ai_b2", "A2(YOLO_Medium)", "B2(Node_Heavy)", None),
    ("resnet_nodejs", "ai_b2", "RN(ResNet18)",    "B2(Node_Heavy)", None),
    ("gpt2_nodejs",   "ai_b2", "GPT(GPT-2)",      "B2(Node_Heavy)", None),
    ("yolo_resnet",   "ai_ai", "A2(YOLO_Medium)", "RN(ResNet18)",   1),
]
SOLOS = [  # (prefix, wl, cgroup, dev)
    ("solo_yolo_1to1",        "A2(YOLO_Medium)", "yolo.slice",   0),
    ("solo_resnet_1to1",      "RN(ResNet18)",    "yolo.slice",   0),
    ("solo_gpt2_1to1",        "GPT(GPT-2)",      "yolo.slice",   0),
    ("solo_resnet_gpu1_1to1", "RN(ResNet18)",    "nodejs.slice", 1),
    ("solo_nodejs_1to1",      "B2(Node_Heavy)",  "nodejs.slice", None),
]
FFMPEG_SCALE = [("1c", 1, 2, "2"), ("2c", 2, 4, "2-3"), ("5c", 5, 10, "2-6")]


def parse_ts(s):
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(s)


def read_rows(fp):
    with open(fp) as f:
        return list(csv.DictReader(f))


def stable(rows):
    if not rows:
        return []
    t0, t1 = parse_ts(rows[0]["timestamp"]), parse_ts(rows[-1]["timestamp"])
    total = (t1 - t0).total_seconds()
    return [r for r in rows
            if TRIM_START <= (parse_ts(r["timestamp"]) - t0).total_seconds() <= total - TRIM_END]


def avg_bounded(rows, col, lo, hi):
    """물리적으로 가능한 범위만 평균 — RAPL energy 카운터 래핑 시 한 샘플이
    수십만 W 음수로 튀는 것을 차단 (asym2 run3 yolo_resnet_5to1에서 실증: -242,642W)"""
    v = []
    for r in rows:
        try:
            x = float(r[col])
            if lo <= x <= hi:
                v.append(x)
        except (ValueError, KeyError):
            pass
    return sum(v) / len(v) if v else 0.0


def avg(rows, col):
    v = []
    for r in rows:
        try:
            v.append(float(r[col]))
        except (ValueError, KeyError):
            pass
    return sum(v) / len(v) if v else 0.0


def cgf(rows, name):
    return [r for r in rows if r.get("cgroup", "").strip() == name]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="1")
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    run = args.run
    root = Path(args.data_root) if args.data_root else REPO
    D = root / f"data/raw/alienware/phase3_asym_run{run}"
    out = Path(args.out_dir) if args.out_dir else root / "reports/asym2"
    label = f"asym2_run{run}"
    print(f"=== 비대칭 v2 추출 (run{run}) ===")
    if not D.exists():
        print("[ERROR] 데이터 없음"); return

    rpict = []
    rp_fp = root / f"data/raw/rpict/asymmetric_run{run}.csv"
    if rp_fp.exists():
        for r in read_rows(rp_fp):
            try:
                rpict.append({"ts": parse_ts(r["timestamp"]), "w": float(r["power1_w"])})
            except (ValueError, KeyError):
                pass
        rpict.sort(key=lambda x: x["ts"])
    else:
        print(f"[WARN] RPICT 없음: {rp_fp}")

    def wall(t0, t1):
        v = [r["w"] for r in rpict if t0 <= r["ts"] <= t1]
        return sum(v) / len(v) if v else 0.0

    def metrics(prefix):
        f = D / f"{prefix}_host.csv"
        if not f.exists():
            return None
        h = stable(read_rows(f))
        if not h:
            return None
        t0, t1 = parse_ts(h[0]["timestamp"]), parse_ts(h[-1]["timestamp"])
        cg_fp = D / f"{prefix}_cgroup.csv"
        cg = stable(read_rows(cg_fp)) if cg_fp.exists() else []
        return {
            "dur": (t1-t0).total_seconds(), "wall": wall(t0, t1),
            "cpu": avg_bounded(h, "rapl_package_w", 0, 500),
            "g0": avg_bounded(h, "gpu0_power_w", 0, 400), "g1": avg_bounded(h, "gpu1_power_w", 0, 400),
            "u0": avg(h, "gpu0_util_pct"), "u1": avg(h, "gpu1_util_pct"),
            "uy": avg(cgf(cg, "yolo.slice"), "cpu_percent"),
            "un": avg(cgf(cg, "nodejs.slice"), "cpu_percent"),
            "cg": cg,
        }

    B = metrics("baseline")
    if not B:
        print("[ERROR] baseline 없음"); return
    cpu_idle, g_idle = B["cpu"], {0: B["g0"], 1: B["g1"], None: 0.0}

    def sysrow(prefix, ptype, conc, wa, wb, ratio, ac, nc, am, nm, m, note_extra=""):
        comp = m["cpu"] + m["g0"] + m["g1"] + 6.4
        if ratio in RATIOS:
            _,_,_,_, acs, ncs = RATIOS[ratio]
            rnote = f"AI=cpuset{acs}/{am}GB | NonAI=cpuset{ncs}/{nm}GB"
        else:
            rnote = note_extra or "-"
        return {
            "run": label, "ratio": ratio, "experiment": prefix, "type": ptype,
            "concurrent_type": conc or "-", "workload_A": wa or "-", "workload_B": wb or "-",
            "ai_cores": ac, "nonai_cores": nc, "ai_mem_GB": am, "nonai_mem_GB": nm,
            "duration_s": f"{m['dur']:.1f}", "wall_power_W": f"{m['wall']:.2f}",
            "cpu_power_W": f"{m['cpu']:.2f}",
            "gpu0_power_W": f"{m['g0']:.2f}", "gpu1_power_W": f"{m['g1']:.2f}",
            "gpu_total_W": f"{m['g0']+m['g1']:.2f}",
            "gpu0_util_pct": f"{m['u0']:.1f}", "gpu1_util_pct": f"{m['u1']:.1f}",
            "memory_power_W": "6.4", "others_W": f"{m['wall']-comp:.2f}",
            "component_sum_W": f"{comp:.2f}",
            "memory_power_note": "calculated:0.2W/GB×32GB",
            "others_note": "wall-(cpu+gpu0+gpu1+memory):PSU_loss+VRM+fans+motherboard",
            "ratio_note": rnote, "gpu_note": note_extra or "-",
        }

    sys_rows, wl_rows, val_rows, ff_rows = [], [], [], []
    sys_rows.append(sysrow("baseline", "idle", None, None, None, "-", "-", "-", "-", "-", B, "idle"))

    # solo refs (디바이스 일치)
    solo_ref = {}
    for prefix, wl, cgname, dev in SOLOS:
        m = metrics(prefix)
        if not m:
            print(f"  [SKIP] {prefix}"); continue
        cpu = m["cpu"] - cpu_idle
        gpu = (m[f"g{dev}"] - g_idle[dev]) if dev is not None else 0.0
        solo_ref[(wl, dev)] = {"total": cpu + gpu + MEM_W_PER_GB*4, "src": prefix}
        ai = dev is not None
        sys_rows.append(sysrow(prefix, "solo", None, wl, None, "1to1",
                               "2" if ai else "-", "-" if ai else "2",
                               "4" if ai else "-", "-" if ai else "4", m,
                               f"Solo: {wl}→GPU{dev}" if dev is not None else f"Solo_CPU: {wl}"))

    # ratio pairs
    for base, conc, wa, wb, devb in PAIRS:
        for ratio, (ac, nc, am, nm, acs, ncs) in RATIOS.items():
            prefix = f"{base}_{ratio}"
            m = metrics(prefix)
            if not m:
                print(f"  [SKIP] {prefix}"); continue
            gnote = (f"AI+AI: {wa}→GPU0, {wb}→GPU1" if conc == "ai_ai"
                     else f"AI+B2: {wa}→GPU0, {wb}→CPU_only")
            sys_rows.append(sysrow(prefix, "concurrent", conc, wa, wb, ratio,
                                   str(ac), str(nc), str(am), str(nm), m, gnote))
            # 검증 (디바이스 일치 solo 기준; mem은 실제 할당 반영)
            su = (m["uy"] + m["un"]) or 1.0
            cpu_act = m["cpu"] - cpu_idle
            for wl, cgname, dev, alloc_mem, util in [
                    (wa, "yolo.slice", 0, am, m["uy"]),
                    (wb, "nodejs.slice", devb, nm, m["un"])]:
                key = (wl, dev)
                if key not in solo_ref:
                    continue
                attr_cpu = cpu_act * util / su
                attr_gpu = (m[f"g{dev}"] - g_idle[dev]) if dev is not None else 0.0
                attr_mem = MEM_W_PER_GB * float(alloc_mem)
                attr = attr_cpu + attr_gpu + attr_mem
                ref = solo_ref[key]["total"]
                val_rows.append({
                    "run": label, "ratio": ratio, "experiment": prefix,
                    "workload": wl, "solo_measured_W": f"{ref:.2f}",
                    "attributed_W": f"{attr:.2f}",
                    "attr_cpu_W": f"{attr_cpu:.2f}", "attr_gpu_W": f"{attr_gpu:.2f}",
                    "attr_mem_W": f"{attr_mem:.2f}",
                    "error_pct": f"{(attr-ref)/ref*100:+.1f}" if ref > 0 else "-",
                    "solo_source": solo_ref[key]["src"],
                })
            # usage rows
            for wl, cgname, dev, alloc_c, alloc_m in [
                    (wa, "yolo.slice", 0, ac, am), (wb, "nodejs.slice", devb, nc, nm)]:
                rows_ = cgf(m["cg"], cgname)
                wl_rows.append({
                    "run": label, "ratio": ratio, "experiment": prefix, "type": "concurrent",
                    "concurrent_type": conc, "workload": wl,
                    "co_workload": wb if wl == wa else wa, "cgroup": cgname,
                    "cpu_util_pct": f"{avg(rows_, 'cpu_percent'):.1f}",
                    "gpu_util_pct": f"{m[f'u{dev}']:.1f}" if dev is not None else "0.0",
                    "gpu_power_W": f"{m[f'g{dev}']:.2f}" if dev is not None else "0.00",
                    "cpu_alloc_cores": str(alloc_c), "gpu_alloc": f"GPU{dev}" if dev is not None else "none",
                    "mem_alloc_GB": str(alloc_m),
                    "mem_used_MB": f"{avg(rows_, 'memory_mb'):.1f}",
                    "duration_s": f"{m['dur']:.1f}",
                })

    # ffmpeg 스케일링 (옵션)
    for lab, cores, mem, cpuset in FFMPEG_SCALE:
        m = metrics(f"ffmpeg_scale_{lab}")
        if not m:
            continue
        iters = 0
        lf = D / f"ffmpeg_scale_{lab}.log"
        if lf.exists():
            iters = open(lf, errors="replace").read().count("[OK]")
        ff_rows.append({
            "run": label, "alloc": lab, "cores": str(cores),
            "cpuset": cpuset, "mem_GB": str(mem),
            "cpu_util_pct": f"{m['un']:.1f}",
            "rapl_W": f"{m['cpu']:.2f}", "rapl_active_W": f"{m['cpu']-cpu_idle:.2f}",
            "wall_W": f"{m['wall']:.2f}", "wall_active_W": f"{m['wall']-B['wall']:.2f}",
            "iters_90s": str(iters),
            "iters_per_core": f"{iters/cores:.1f}",
            "W_per_iter": f"{(m['cpu']-cpu_idle)/iters:.2f}" if iters else "-",
        })
        sys_rows.append(sysrow(f"ffmpeg_scale_{lab}", "solo", None, "FF(ffmpeg_x264)", None,
                               "-", "-", str(cores), "-", str(mem), m,
                               f"ffmpeg alloc-scaling: NonAI=cpuset{cpuset}/{mem}GB"))

    os.makedirs(out, exist_ok=True)
    SYS_COLS = ["run","ratio","experiment","type","concurrent_type","workload_A","workload_B",
                "ai_cores","nonai_cores","ai_mem_GB","nonai_mem_GB","duration_s","wall_power_W",
                "cpu_power_W","gpu0_power_W","gpu1_power_W","gpu_total_W","gpu0_util_pct",
                "gpu1_util_pct","memory_power_W","others_W","component_sum_W",
                "memory_power_note","others_note","ratio_note","gpu_note"]
    WL_COLS = ["run","ratio","experiment","type","concurrent_type","workload","co_workload",
               "cgroup","cpu_util_pct","gpu_util_pct","gpu_power_W","cpu_alloc_cores",
               "gpu_alloc","mem_alloc_GB","mem_used_MB","duration_s"]
    VAL_COLS = ["run","ratio","experiment","workload","solo_measured_W","attributed_W",
                "attr_cpu_W","attr_gpu_W","attr_mem_W","error_pct","solo_source"]
    FF_COLS = ["run","alloc","cores","cpuset","mem_GB","cpu_util_pct","rapl_W",
               "rapl_active_W","wall_W","wall_active_W","iters_90s","iters_per_core","W_per_iter"]

    def wtsv(name, rows, cols):
        with open(out/name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"[출력] {out/name} ({len(rows)} rows)")

    wtsv(f"system_power_asym2_run{run}.tsv", sys_rows, SYS_COLS)
    wtsv(f"workload_usage_asym2_run{run}.tsv", wl_rows, WL_COLS)
    wtsv(f"validation_asym2_run{run}.tsv", val_rows, VAL_COLS)
    if ff_rows:
        wtsv(f"ffmpeg_scaling_run{run}.tsv", ff_rows, FF_COLS)

    # ── 콘솔 요약 ──
    print("\n===== 비율별 Wall Power (demand-bound 불변성) =====")
    print(f"{'pair':<16}" + "".join(f"{r:>9}" for r in RATIOS) + f"{'Δmax%':>8}")
    for base, conc, wa, wb, devb in PAIRS:
        vals = {}
        for r in sys_rows:
            if r["experiment"].startswith(base) and r["type"] == "concurrent":
                vals[r["ratio"]] = float(r["wall_power_W"])
        if len(vals) == 5:
            v = [vals[x] for x in RATIOS]
            print(f"{base:<16}" + "".join(f"{x:>9.1f}" for x in v)
                  + f"{(max(v)-min(v))/min(v)*100:>7.1f}%")

    if ff_rows:
        print("\n===== ffmpeg 할당 스케일링 (allocation-bound 대조군) =====")
        for r in ff_rows:
            print(f"  {r['alloc']}: util {r['cpu_util_pct']:>6}%  RAPL_act {r['rapl_active_W']:>6}W  "
                  f"wall_act {r['wall_active_W']:>6}W  iters {r['iters_90s']:>3} ({r['iters_per_core']}/core)")

    print("\n===== 귀속 검증 =====")
    errs = [abs(float(r["error_pct"])) for r in val_rows if r["error_pct"] != "-"]
    by = {}
    for r in val_rows:
        by.setdefault(r["workload"], []).append(float(r["error_pct"]))
    for wl, v in by.items():
        print(f"  {wl:<20} mean {sum(v)/len(v):+6.1f}%  (n={len(v)})")
    if errs:
        print(f"  전체 평균 |오차| = {sum(errs)/len(errs):.1f}%")


if __name__ == "__main__":
    main()
