#!/usr/bin/env python3
"""fio v2 분석: RPICT + Host 동시 수집 데이터로 순수 Storage 전력 분리"""
import pandas as pd
import numpy as np
import json
from pathlib import Path

BASE = Path(__file__).parent.parent.parent
HOST_DIR = BASE / "data/raw/alienware/phase2.1_fio"
RPICT_FILE = BASE / "data/raw/rpict/rpict_fio_v2.csv"

# v1 데이터 (비교용)
V1_HOST_DIR = BASE / "data/raw/alienware/phase2.0_fio"
V1_RPICT_FILE = BASE / "data/raw/rpict/260210-fio-test-v1.csv"

# Config A idle 참조 (component isolation)
COMP_RPICT = BASE / "data/raw/rpict/rpict_component_A-phase2.csv"


def load_csv(path):
    return pd.read_csv(path, parse_dates=['timestamp'])


def phase_stats(df, label=""):
    """DataFrame의 주요 통계"""
    cols = {}
    if 'power1_w' in df.columns:  # RPICT
        cols['wall_w'] = df['power1_w']
    if 'rapl_package_w' in df.columns:  # Host
        cols['rapl_pkg'] = df['rapl_package_w']
        cols['rapl_core'] = df['rapl_core_w']
        cols['gpu_total'] = df['gpu_power_w']
        if 'gpu0_power_w' in df.columns:
            cols['gpu0'] = df['gpu0_power_w']
        if 'gpu1_power_w' in df.columns:
            cols['gpu1'] = df['gpu1_power_w']
        cols['cpu_pct'] = df['cpu_pct']
        cols['iowait'] = df['iowait_pct']
        freq_cols = [c for c in df.columns if c.endswith('_mhz')]
        if freq_cols:
            cols['avg_mhz'] = df[freq_cols].mean(axis=1)

    result = {}
    for k, v in cols.items():
        result[f'{k}_mean'] = v.mean()
        result[f'{k}_std'] = v.std()
    result['n_samples'] = len(df)
    return result


def main():
    print("=" * 90)
    print("fio v2 Storage Energy Analysis - RPICT + Host Combined")
    print("=" * 90)

    # ── Load data ──
    rpict = load_csv(RPICT_FILE)
    idle_host = load_csv(HOST_DIR / "idle_baseline_host.csv")
    read_host = load_csv(HOST_DIR / "seq_read_host.csv")
    write_host = load_csv(HOST_DIR / "seq_write_host.csv")

    with open(HOST_DIR / "seq_read_fio.json") as f:
        read_fio = json.load(f)['jobs'][0]
    with open(HOST_DIR / "seq_write_fio.json") as f:
        write_fio = json.load(f)['jobs'][0]

    # ── Timeline analysis ──
    # From host timestamps:
    # idle: 03:18:27 ~ 03:19:26 (60s)
    # seq_read host: 03:20:08 ~ 03:21:18, fio stable: ~03:20:13 ~ 03:21:09
    # seq_write host: 03:21:49 ~ 03:22:58, fio stable: ~03:22:14 ~ 03:22:50

    # Trim host data (10% from each end for idle, manual for fio phases)
    n_idle = len(idle_host)
    trim = int(n_idle * 0.1)
    idle_h = idle_host.iloc[trim:n_idle-trim]

    # seq_read: skip first 3 rows (pre-fio) and last 3 (post-fio)
    read_h = read_host.iloc[3:-3]  # rows where fio is actually running
    # Further filter: only rows with high CPU (fio active)
    read_h_active = read_host[read_host['rapl_package_w'] > 20]  # fio running = high RAPL

    # seq_write: skip GPU spike period + pre/post
    # GPU spike in first ~10 rows, stabilizes after
    write_h_active = write_host[
        (write_host['io_write_kbs'] > 1000000) &  # active IO
        (write_host['gpu_power_w'] < 16)  # after GPU spike settles
    ]

    # RPICT phases (by timestamp ranges)
    # idle: before 03:20:10
    rpict_idle = rpict[rpict['timestamp'] < '2026-02-16T03:20:10']
    # Remove first 3 and last 2 samples
    if len(rpict_idle) > 5:
        rpict_idle = rpict_idle.iloc[3:-2]

    # seq_read: 03:20:13 to 03:21:11
    rpict_read = rpict[
        (rpict['timestamp'] >= '2026-02-16T03:20:13') &
        (rpict['timestamp'] <= '2026-02-16T03:21:12')
    ]

    # seq_write stable: 03:22:12 to 03:22:50
    rpict_write = rpict[
        (rpict['timestamp'] >= '2026-02-16T03:22:12') &
        (rpict['timestamp'] <= '2026-02-16T03:22:51')
    ]

    # cooldown / post-fio: 03:22:54 onwards (for final idle reference)
    rpict_post = rpict[rpict['timestamp'] >= '2026-02-16T03:23:00']

    # ── 1. Idle Baseline ──
    print(f"\n{'='*90}")
    print("1. Idle Baseline (Config A: 2GPU+2DIMM)")
    print(f"{'='*90}")

    idle_s = phase_stats(idle_h)
    rpict_idle_s = phase_stats(rpict_idle)
    rpict_post_s = phase_stats(rpict_post)

    print(f"  [Host] RAPL: {idle_s['rapl_pkg_mean']:.2f}W, GPU: {idle_s['gpu_total_mean']:.2f}W "
          f"(GPU0={idle_s['gpu0_mean']:.2f}, GPU1={idle_s['gpu1_mean']:.2f})")
    print(f"  [Host] CPU%: {idle_s['cpu_pct_mean']:.2f}%, Freq: {idle_s['avg_mhz_mean']:.0f}MHz")
    print(f"  [RPICT] Wall (pre-fio idle): {rpict_idle_s['wall_w_mean']:.2f}W ± {rpict_idle_s['wall_w_std']:.2f} ({rpict_idle_s['n_samples']} samples)")
    print(f"  [RPICT] Wall (post-fio idle): {rpict_post_s['wall_w_mean']:.2f}W ± {rpict_post_s['wall_w_std']:.2f} ({rpict_post_s['n_samples']} samples)")

    # 참고: Component isolation Config A idle
    if COMP_RPICT.exists():
        comp = pd.read_csv(COMP_RPICT)
        n = len(comp)
        t = int(n * 0.1)
        comp = comp.iloc[t:n-t]
        print(f"  [Ref] Config A component isolation idle: {comp['power1_w'].mean():.2f}W")

    # idle wall 기준값 (pre-fio와 post-fio 평균)
    wall_idle = rpict_idle_s['wall_w_mean']
    # post-fio가 더 안정적 (GPU settling), 하지만 pre-fio가 실험 조건과 가까움
    # 둘 다 보여주고 pre-fio 사용
    print(f"\n  → idle wall 기준: {wall_idle:.2f}W (pre-fio)")
    print(f"    (post-fio idle: {rpict_post_s['wall_w_mean']:.2f}W - GPU 안정화 후 더 낮음)")

    # ── 2. Sequential Read ──
    print(f"\n{'='*90}")
    print("2. Sequential Read")
    print(f"{'='*90}")

    read_s = phase_stats(read_h_active)
    rpict_read_s = phase_stats(rpict_read)

    read_bw = read_fio['read']['bw'] / 1024  # MB/s
    read_iops = read_fio['read']['iops']

    d_cpu_read = read_s['rapl_pkg_mean'] - idle_s['rapl_pkg_mean']
    d_gpu_read = read_s['gpu_total_mean'] - idle_s['gpu_total_mean']
    wall_read = rpict_read_s['wall_w_mean']
    d_wall_read = wall_read - wall_idle

    print(f"  [fio] Throughput: {read_bw:.0f} MB/s, IOPS: {read_iops:.0f}")
    print(f"  [fio] sys_cpu: {read_fio['sys_cpu']:.1f}%, usr_cpu: {read_fio['usr_cpu']:.1f}%")
    print(f"")
    print(f"  [Host] RAPL: {read_s['rapl_pkg_mean']:.2f}W  (delta: {d_cpu_read:+.2f}W)")
    print(f"  [Host] GPU:  {read_s['gpu_total_mean']:.2f}W  (delta: {d_gpu_read:+.2f}W)")
    print(f"         GPU0={read_s['gpu0_mean']:.2f}W, GPU1={read_s['gpu1_mean']:.2f}W")
    print(f"  [Host] CPU%: {read_s['cpu_pct_mean']:.1f}%, Freq: {read_s['avg_mhz_mean']:.0f}MHz")
    print(f"")
    print(f"  [RPICT] Wall: {wall_read:.2f}W ± {rpict_read_s['wall_w_std']:.2f} ({rpict_read_s['n_samples']} samples)")
    print(f"  [RPICT] Wall delta: {d_wall_read:+.2f}W")

    # Storage 분리
    stor_read = d_wall_read - d_cpu_read - d_gpu_read
    stor_rate_read = stor_read / read_bw if read_bw > 0 else 0

    print(f"\n  ┌─ Storage Power Isolation (seq_read) ─────────────────┐")
    print(f"  │ Wall delta (RPICT):     {d_wall_read:+8.2f}W                  │")
    print(f"  │ - CPU delta (RAPL):     {d_cpu_read:+8.2f}W                  │")
    print(f"  │ - GPU delta (smi):      {d_gpu_read:+8.2f}W                  │")
    print(f"  │ = Storage + PCIe + PSU: {stor_read:+8.2f}W                  │")
    print(f"  │                                                       │")
    print(f"  │ Throughput:             {read_bw:8.0f} MB/s               │")
    print(f"  │ Storage rate:           {stor_rate_read:8.5f} W per MB/s       │")
    print(f"  └───────────────────────────────────────────────────────┘")

    # ── 3. Sequential Write ──
    print(f"\n{'='*90}")
    print("3. Sequential Write")
    print(f"{'='*90}")

    write_s = phase_stats(write_h_active)
    rpict_write_s = phase_stats(rpict_write)

    write_bw = write_fio['write']['bw'] / 1024  # MB/s
    write_iops = write_fio['write']['iops']

    d_cpu_write = write_s['rapl_pkg_mean'] - idle_s['rapl_pkg_mean']
    d_gpu_write = write_s['gpu_total_mean'] - idle_s['gpu_total_mean']
    wall_write = rpict_write_s['wall_w_mean']
    d_wall_write = wall_write - wall_idle

    print(f"  [fio] Throughput: {write_bw:.0f} MB/s, IOPS: {write_iops:.0f}")
    print(f"  [fio] sys_cpu: {write_fio['sys_cpu']:.1f}%, usr_cpu: {write_fio['usr_cpu']:.1f}%")
    print(f"")
    print(f"  [Host] RAPL: {write_s['rapl_pkg_mean']:.2f}W  (delta: {d_cpu_write:+.2f}W)")
    print(f"  [Host] GPU:  {write_s['gpu_total_mean']:.2f}W  (delta: {d_gpu_write:+.2f}W)")
    print(f"         GPU0={write_s['gpu0_mean']:.2f}W, GPU1={write_s['gpu1_mean']:.2f}W")
    print(f"  [Host] CPU%: {write_s['cpu_pct_mean']:.1f}%, Freq: {write_s['avg_mhz_mean']:.0f}MHz")
    print(f"")
    print(f"  [RPICT] Wall: {wall_write:.2f}W ± {rpict_write_s['wall_w_std']:.2f} ({rpict_write_s['n_samples']} samples)")
    print(f"  [RPICT] Wall delta: {d_wall_write:+.2f}W")

    # GPU 초기 스파이크 주의
    write_spike = write_host[write_host['gpu_power_w'] > 20]
    if len(write_spike) > 0:
        print(f"\n  [NOTE] seq_write 시작 시 GPU 스파이크 발생:")
        print(f"         GPU peak: {write_host['gpu_power_w'].max():.1f}W (GPU0: {write_host['gpu0_power_w'].max():.1f}W)")
        print(f"         → GPU mem 370→405MB 변화, ~10초 후 안정화")
        print(f"         → 안정 구간만 사용하여 분석")

    stor_write = d_wall_write - d_cpu_write - d_gpu_write
    stor_rate_write = stor_write / write_bw if write_bw > 0 else 0

    print(f"\n  ┌─ Storage Power Isolation (seq_write) ────────────────┐")
    print(f"  │ Wall delta (RPICT):     {d_wall_write:+8.2f}W                  │")
    print(f"  │ - CPU delta (RAPL):     {d_cpu_write:+8.2f}W                  │")
    print(f"  │ - GPU delta (smi):      {d_gpu_write:+8.2f}W                  │")
    print(f"  │ = Storage + PCIe + PSU: {stor_write:+8.2f}W                  │")
    print(f"  │                                                       │")
    print(f"  │ Throughput:             {write_bw:8.0f} MB/s               │")
    print(f"  │ Storage rate:           {stor_rate_write:8.5f} W per MB/s       │")
    print(f"  └───────────────────────────────────────────────────────┘")

    # ── 4. 비교 Summary ──
    print(f"\n{'='*90}")
    print("4. Storage Energy Parameters Summary")
    print(f"{'='*90}")

    print(f"\n  {'항목':<20} {'seq_read':<20} {'seq_write':<20} {'단위'}")
    print(f"  {'-'*75}")
    print(f"  {'Throughput':<20} {read_bw:<20.0f} {write_bw:<20.0f} MB/s")
    print(f"  {'Wall idle':<20} {wall_idle:<20.2f} {wall_idle:<20.2f} W")
    print(f"  {'Wall fio':<20} {wall_read:<20.2f} {wall_write:<20.2f} W")
    print(f"  {'dWall':<20} {d_wall_read:<+20.2f} {d_wall_write:<+20.2f} W")
    print(f"  {'dCPU (RAPL)':<20} {d_cpu_read:<+20.2f} {d_cpu_write:<+20.2f} W")
    print(f"  {'dGPU (smi)':<20} {d_gpu_read:<+20.2f} {d_gpu_write:<+20.2f} W")
    print(f"  {'Storage+PCIe+PSU':<20} {stor_read:<+20.2f} {stor_write:<+20.2f} W")
    print(f"  {'Storage rate':<20} {stor_rate_read:<20.5f} {stor_rate_write:<20.5f} W/(MB/s)")

    # ── 5. 데이터시트 비교 ──
    print(f"\n{'='*90}")
    print("5. Samsung 980 NVMe 데이터시트 vs 실측")
    print(f"{'='*90}")
    print(f"  데이터시트 Sequential Read:  ~3.5W @ 3,500 MB/s → 0.00100 W/(MB/s)")
    print(f"  데이터시트 Sequential Write: ~3.9W @ 3,000 MB/s → 0.00130 W/(MB/s)")
    print(f"  실측 seq_read:   {stor_read:.2f}W @ {read_bw:.0f} MB/s → {stor_rate_read:.5f} W/(MB/s)")
    print(f"  실측 seq_write:  {stor_write:.2f}W @ {write_bw:.0f} MB/s → {stor_rate_write:.5f} W/(MB/s)")
    if stor_read > 0:
        ratio_read = stor_read / 3.5
        print(f"\n  seq_read 실측/데이터시트: {ratio_read:.1f}x ({stor_read:.1f}W vs 3.5W)")
        print(f"    → 차이 원인: PCIe 컨트롤러 오버헤드 + PSU 효율 변화 + RAPL 오차")
    if stor_write > 0:
        ratio_write = stor_write / 3.9
        print(f"  seq_write 실측/데이터시트: {ratio_write:.1f}x ({stor_write:.1f}W vs 3.9W)")

    # ── 6. v1 vs v2 비교 ──
    print(f"\n{'='*90}")
    print("6. v1 (이전) vs v2 (현재) 비교 - 교수님 지적 반영 확인")
    print(f"{'='*90}")
    print(f"\n  v1 문제: delta 전체(~46W)를 storage로 귀속 → 대부분 CPU였음")
    print(f"  v2 개선: CPU/GPU delta를 명시적으로 분리")
    print(f"")
    print(f"  {'항목':<25} {'v1 (이전)':<20} {'v2 (현재)':<20} {'비고'}")
    print(f"  {'-'*85}")
    print(f"  {'환경':<25} {'1GPU+?DIMM':<20} {'2GPU+2DIMM':<20} Config A 환경")
    print(f"  {'RPICT 동시수집':<25} {'부분적':<20} {'완전':<20} v2에서 전 구간 커버")
    print(f"  {'seq_read dWall':<25} {'~46W (추정)':<20} {f'{d_wall_read:.1f}W':<20} RPICT 실측")
    print(f"  {'seq_read dCPU':<25} {'~24W (RAPL)':<20} {f'{d_cpu_read:.1f}W':<20} RAPL 차이만")
    print(f"  {'seq_read dGPU':<25} {'~0W':<20} {f'{d_gpu_read:.1f}W':<20} ")
    print(f"  {'seq_read Storage잔여':<25} {'~46W (전부!)':<20} {f'{stor_read:.1f}W':<20} CPU/GPU 분리 후")
    print(f"  {'seq_read Storage rate':<25} {'산출 안됨':<20} {f'{stor_rate_read:.5f}':<20} W/(MB/s)")

    # ── 7. PSU 효율 보정 ──
    print(f"\n{'='*90}")
    print("7. PSU 효율 보정 (참고)")
    print(f"{'='*90}")

    # idle: 47W → ~75% eff → DC 35W
    # read: 89W → ~77% eff → DC 69W
    # 효율 변화분이 delta에 포함됨
    eff_idle = 0.70 + (wall_idle / 1000 * 100 / 10) * 0.12
    eff_read = 0.70 + (wall_read / 1000 * 100 / 10) * 0.12
    eff_write = 0.70 + (wall_write / 1000 * 100 / 10) * 0.12

    dc_idle = wall_idle * eff_idle
    dc_read = wall_read * eff_read
    dc_write = wall_write * eff_write

    psu_loss_delta_read = (wall_read - dc_read) - (wall_idle - dc_idle)
    psu_loss_delta_write = (wall_write - dc_write) - (wall_idle - dc_idle)

    print(f"  Idle:      Wall={wall_idle:.1f}W, est.eff={eff_idle*100:.0f}%, DC={dc_idle:.1f}W, PSU_loss={wall_idle-dc_idle:.1f}W")
    print(f"  seq_read:  Wall={wall_read:.1f}W, est.eff={eff_read*100:.0f}%, DC={dc_read:.1f}W, PSU_loss={wall_read-dc_read:.1f}W")
    print(f"  seq_write: Wall={wall_write:.1f}W, est.eff={eff_write*100:.0f}%, DC={dc_write:.1f}W, PSU_loss={wall_write-dc_write:.1f}W")
    print(f"")
    print(f"  PSU 효율 변화로 인한 추가 손실:")
    print(f"    seq_read:  dPSU_loss = {psu_loss_delta_read:+.1f}W (idle→read 효율 변화)")
    print(f"    seq_write: dPSU_loss = {psu_loss_delta_write:+.1f}W")
    print(f"")
    print(f"  PSU 보정 후 순수 DC-side Storage:")
    stor_read_dc = stor_read - psu_loss_delta_read
    stor_write_dc = stor_write - psu_loss_delta_write
    print(f"    seq_read:  {stor_read:.2f} - {psu_loss_delta_read:.2f} = {stor_read_dc:.2f}W")
    print(f"    seq_write: {stor_write:.2f} - {psu_loss_delta_write:.2f} = {stor_write_dc:.2f}W")

    print(f"\n{'='*90}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()
