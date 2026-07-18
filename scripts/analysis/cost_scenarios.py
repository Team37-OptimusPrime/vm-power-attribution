#!/usr/bin/env python3
"""Cost 시나리오 계산 (R2#2 대응) — 실측 데이터 기반 과금 비교

과금 식 (리비전 제안):
  Cost_i = p · ( E_i + α_i · E_baseline )
    E_i        : 귀속 모델이 산출한 워크로드 에너지 (실측)
    E_baseline : 비귀속 잔여 (idle + Others = wall − ΣE_i)
    α_i        : baseline 배분 정책 — equal(1/n) 또는 할당 비례
    p          : 전력 단가 (기본 $0.12/kWh)

시나리오 3종 (모두 실측):
  A. 비대칭 5비율 — 할당 요금 배분 vs 에너지 배분의 괴리 (mispricing factor)
  B. 9종 워크로드 — 동일 할당(동일 요금)에서의 에너지 비용 스펙트럼
  C. ffmpeg 스케일링 — 할당 확대(요금 5×) vs 실제 에너지(2.7×)

Usage: python3 cost_scenarios.py [--data-root PATH] [--price 0.12]
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parents[2]
HOURS_MONTH = 720


def read_tsv(fp):
    with open(fp) as f:
        return list(csv.DictReader(f, delimiter="\t"))


def monthly(p_watt, price):
    return p_watt * HOURS_MONTH / 1000 * price


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--price", type=float, default=0.12, help="$/kWh")
    args = ap.parse_args()
    root = Path(args.data_root) if args.data_root else REPO
    price = args.price
    out = root / "reports/cost"
    out.mkdir(parents=True, exist_ok=True)
    rows_out = []

    # ── 시나리오 A: 비대칭 — 할당 배분 vs 에너지 배분 ──────────────
    val = read_tsv(root / "reports/asym2/validation_asym2_all.tsv")
    sys_rows = read_tsv(root / "reports/asym2/system_power_asym2_all.tsv")
    RATIO_ALLOC = {"1to1": (2, 2), "2to1": (3, 1), "1to2": (1, 3),
                   "5to1": (5, 1), "1to5": (1, 5)}

    # (ratio) → 워크로드별 attributed 평균 (yolo_nodejs 쌍)
    attr = defaultdict(lambda: defaultdict(list))
    for r in val:
        if r["experiment"].startswith("yolo_nodejs"):
            attr[r["ratio"]][r["workload"]].append(float(r["attributed_W"]))
    wall = defaultdict(list)
    for r in sys_rows:
        if r["experiment"].startswith("yolo_nodejs") and r["type"] == "concurrent":
            wall[r["ratio"]].append(float(r["wall_power_W"]))

    print("=" * 100)
    print("시나리오 A — 비대칭 할당 (YOLO+Node.js): 할당 요금 배분 vs 실측 에너지 배분")
    print("=" * 100)
    print(f"{'ratio':<7}{'할당배분(AI:Node)':>18}{'에너지배분(AI:Node)':>20}"
          f"{'AI 과소/과대':>13}{'Node 과소/과대':>15}{'월요금 AI/Node($)':>19}")
    for ratio, (ac, nc) in RATIO_ALLOC.items():
        if ratio not in attr:
            continue
        a = mean(attr[ratio]["A2(YOLO_Medium)"])
        b = mean(attr[ratio]["B2(Node_Heavy)"])
        alloc_a, alloc_b = ac / (ac + nc), nc / (ac + nc)
        en_a, en_b = a / (a + b), b / (a + b)
        w = mean(wall[ratio])
        base = w - a - b
        # 에너지 기반 월요금 (baseline equal split)
        cost_a = monthly(a + base / 2, price)
        cost_b = monthly(b + base / 2, price)
        mis_a, mis_b = alloc_a / en_a, alloc_b / en_b
        print(f"{ratio:<7}{f'{alloc_a*100:.0f}% : {alloc_b*100:.0f}%':>18}"
              f"{f'{en_a*100:.0f}% : {en_b*100:.0f}%':>20}"
              f"{mis_a:>12.2f}×{mis_b:>14.2f}×"
              f"{f'{cost_a:.2f} / {cost_b:.2f}':>19}")
        rows_out.append({"scenario": "A_asym", "case": f"yolo_nodejs_{ratio}",
                         "alloc_share_A": f"{alloc_a:.3f}", "energy_share_A": f"{en_a:.3f}",
                         "mispricing_A": f"{mis_a:.2f}", "mispricing_B": f"{mis_b:.2f}",
                         "monthly_cost_A_usd": f"{cost_a:.2f}",
                         "monthly_cost_B_usd": f"{cost_b:.2f}",
                         "baseline_W": f"{base:.1f}", "note": "baseline equal-split"})

    # ── 시나리오 B: 9종 동일 할당 — 에너지 비용 스펙트럼 ────────────
    p4 = read_tsv(root / "reports/phase4/system_power_phase4_all.tsv")
    solo_wall = defaultdict(list)
    base_wall = []
    for r in p4:
        if r["type"] == "solo":
            solo_wall[r["workload_A"]].append(float(r["wall_power_W"]))
        elif r["type"] == "idle":
            base_wall.append(float(r["wall_power_W"]))
    # 3-way 데이터에서 GPU-AI solo도 합류 (RN/GPT는 phase4에 이미 있음)
    idle_w = mean(base_wall)

    print("\n" + "=" * 100)
    print(f"시나리오 B — 동일 할당(2코어/4GB, 동일 요금)의 에너지 비용 스펙트럼 "
          f"(baseline {idle_w:.0f}W 제외한 유발분)")
    print("=" * 100)
    print(f"{'workload':<26}{'유발전력(W)':>12}{'월 에너지비용($)':>17}{'최저 대비':>10}")
    induced = {wl: mean(v) - idle_w for wl, v in solo_wall.items() if "bursty" not in wl}
    lo = min(induced.values())
    for wl, w in sorted(induced.items(), key=lambda x: -x[1]):
        c = monthly(w, price)
        print(f"{wl:<26}{w:>12.1f}{c:>17.2f}{w/lo:>9.1f}×")
        rows_out.append({"scenario": "B_same_alloc", "case": wl,
                         "induced_W": f"{w:.1f}",
                         "monthly_cost_usd": f"{c:.2f}", "vs_min": f"{w/lo:.1f}",
                         "note": "identical allocation & identical alloc-based bill"})

    # ── 시나리오 C: ffmpeg 스케일링 — 요금 스케일 vs 에너지 스케일 ──
    ff = read_tsv(root / "reports/asym2/ffmpeg_scaling_all.tsv")
    print("\n" + "=" * 100)
    print("시나리오 C — 할당 확대 시: 할당 요금 vs 실측 에너지 (ffmpeg)")
    print("=" * 100)
    print(f"{'할당':<6}{'요금 배율(할당기준)':>18}{'에너지 배율(실측)':>18}{'처리량 배율':>12}{'과대청구':>9}")
    base_row = next(r for r in ff if r["alloc"] == "1c")
    e1 = float(base_row["wall_active_W"]); i1 = int(base_row["iters_90s"])
    for r in ff:
        cores = int(r["cores"])
        e = float(r["wall_active_W"]); it = int(r["iters_90s"])
        over = cores / (e / e1)
        print(f"{r['alloc']:<6}{cores:>17.0f}×{e/e1:>17.1f}×{it/i1:>11.1f}×{over:>8.2f}×")
        rows_out.append({"scenario": "C_scaling", "case": f"ffmpeg_{r['alloc']}",
                         "alloc_cost_ratio": f"{cores:.0f}", "energy_ratio": f"{e/e1:.2f}",
                         "throughput_ratio": f"{it/i1:.2f}",
                         "overcharge_factor": f"{over:.2f}",
                         "note": "alloc-based bill scales with cores; energy does not"})

    # TSV 저장 (스키마 통합: 모든 키의 합집합)
    cols = []
    for r in rows_out:
        for k in r:
            if k not in cols:
                cols.append(k)
    fp = out / "cost_scenarios.tsv"
    with open(fp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", restval="-")
        w.writeheader()
        for r in rows_out:
            w.writerow(r)
    print(f"\n[출력] {fp} ({len(rows_out)} rows)  (전력단가 ${price}/kWh, 월 {HOURS_MONTH}h 기준)")


if __name__ == "__main__":
    main()
