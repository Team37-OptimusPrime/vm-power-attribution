#!/usr/bin/env python3
"""공유 코어 co-schedule 실험 분석 (R2#3) → TSV

같은 cpuset(0-3)을 공유하는 Node.js + ffmpeg에 대해, 이용률 비례 CPU 분할의
오차를 fixed(3.6GHz 고정) / free(DVFS+turbo) 두 조건에서 정량화한다.

  attr_i = (RAPL_cosched − idle) × util_i / Σutil
  err_i  = (attr_i − solo_active_i) / solo_active_i
  sub-additivity gap = Σsolo_active − cosched_active

Usage: python3 extract_cosched_data.py --run 1 [--data-root PATH]
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TRIM_START, TRIM_END = 15, 5


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
    v = []
    for r in rows:
        try:
            x = float(r[col])
            if lo <= x <= hi:
                v.append(x)
        except (ValueError, KeyError):
            pass
    return sum(v) / len(v) if v else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="1")
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    run = args.run
    root = Path(args.data_root) if args.data_root else REPO
    D = root / f"data/raw/alienware/cosched_run{run}"
    out = Path(args.out_dir) if args.out_dir else root / "reports/cosched"
    if not D.exists():
        print(f"[ERROR] 없음: {D}"); return

    rpict = []
    rp = root / f"data/raw/rpict/cosched_run{run}.csv"
    if rp.exists():
        for r in read_rows(rp):
            try:
                rpict.append({"ts": parse_ts(r["timestamp"]), "w": float(r["power1_w"])})
            except (ValueError, KeyError):
                pass
        rpict.sort(key=lambda x: x["ts"])

    def metrics(prefix):
        f = D / f"{prefix}_host.csv"
        if not f.exists():
            return None
        h = stable(read_rows(f))
        if not h:
            return None
        t0, t1 = parse_ts(h[0]["timestamp"]), parse_ts(h[-1]["timestamp"])
        wall = 0.0
        v = [r["w"] for r in rpict if t0 <= r["ts"] <= t1]
        if v:
            wall = sum(v) / len(v)
        cgfp = D / f"{prefix}_cgroup.csv"
        cg = stable(read_rows(cgfp)) if cgfp.exists() else []
        def cgu(name):
            rows = [r for r in cg if r.get("cgroup", "").strip() == name]
            return avg_bounded(rows, "cpu_percent", 0, 2000)
        return {
            "cpu": avg_bounded(h, "rapl_package_w", 0, 500),
            "wall": wall,
            "mhz": avg_bounded(h, "cpu0_mhz", 0, 6000),
            "uff": cgu("yolo.slice"), "un": cgu("nodejs.slice"),
        }

    def iters(logname):
        f = D / logname
        return open(f, errors="replace").read().count("[OK]") if f.exists() else 0

    rows_out = []
    print(f"=== cosched run{run} ===")
    for cond in ["fixed", "free"]:
        B = metrics(f"baseline_{cond}")
        SF = metrics(f"solo_ffmpeg_{cond}")
        SN = metrics(f"solo_node_{cond}")
        C = metrics(f"cosched_{cond}")
        if not all([B, SF, SN, C]):
            print(f"  [SKIP] {cond}: phase 누락"); continue
        idle = B["cpu"]
        ref_ff, ref_n = SF["cpu"] - idle, SN["cpu"] - idle
        cact = C["cpu"] - idle
        su = (C["uff"] + C["un"]) or 1.0
        att_ff = cact * C["uff"] / su
        att_n = cact * C["un"] / su
        gap = (ref_ff + ref_n) - cact
        it_solo = iters(f"solo_{cond}_ffmpeg.log")
        it_cos = iters(f"cosched_{cond}_ffmpeg.log")
        for wl, ref, att, us, uc, its, itc in [
                ("ffmpeg", ref_ff, att_ff, SF["uff"], C["uff"], it_solo, it_cos),
                ("nodejs", ref_n, att_n, SN["un"], C["un"], "-", "-")]:
            rows_out.append({
                "run": f"cosched_run{run}", "condition": cond, "workload": wl,
                "solo_cpu_active_W": f"{ref:.2f}", "attributed_W": f"{att:.2f}",
                "error_pct": f"{(att-ref)/ref*100:+.1f}",
                "util_solo": f"{us:.1f}", "util_cosched": f"{uc:.1f}",
                "cosched_cpu_active_W": f"{cact:.2f}",
                "subadd_gap_W": f"{gap:.2f}",
                "cpu_mhz_cosched": f"{C['mhz']:.0f}",
                "iters_solo": str(its), "iters_cosched": str(itc),
                "wall_solo_W": f"{(SF if wl=='ffmpeg' else SN)['wall']:.1f}",
                "wall_cosched_W": f"{C['wall']:.1f}",
            })
        print(f"  [{cond}] idle {idle:.1f}W | solo ff {ref_ff:.1f} / node {ref_n:.1f} "
              f"| cosched {cact:.1f} (gap {gap:.1f}W = {gap/(ref_ff+ref_n)*100:.0f}%)")
        print(f"    ffmpeg: attr {att_ff:.1f} vs solo {ref_ff:.1f} → {(att_ff-ref_ff)/ref_ff*100:+.1f}%  "
              f"(util {SF['uff']:.0f}→{C['uff']:.0f}%, iters {it_solo}→{it_cos})")
        print(f"    nodejs: attr {att_n:.1f} vs solo {ref_n:.1f} → {(att_n-ref_n)/ref_n*100:+.1f}%  "
              f"(util {SN['un']:.0f}→{C['un']:.0f}%)")

    os.makedirs(out, exist_ok=True)
    cols = ["run","condition","workload","solo_cpu_active_W","attributed_W","error_pct",
            "util_solo","util_cosched","cosched_cpu_active_W","subadd_gap_W",
            "cpu_mhz_cosched","iters_solo","iters_cosched","wall_solo_W","wall_cosched_W"]
    fp = out / f"cosched_analysis_run{run}.tsv"
    with open(fp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t")
        w.writeheader()
        for r in rows_out:
            w.writerow(r)
    print(f"[출력] {fp} ({len(rows_out)} rows)")


if __name__ == "__main__":
    main()
