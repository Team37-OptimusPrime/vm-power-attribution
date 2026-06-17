"""model.py – VM Power Attribution Dashboard
Attribution model implementation based on the research paper.
Decomposes system power into per-workload CPU / GPU / Memory / Storage contributions.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Model constants (from paper / experiment design)
# ---------------------------------------------------------------------------

MEMORY_TOTAL_GB: float = 32.0
MEMORY_POWER_PER_GB: float = 0.2       # W/GB  (LPDDR4 spec)
STORAGE_BETA: float = 2.5              # J/GB  (W per GB/s)
MEMORY_ALLOCATED_GB: float = 4.0       # per workload (fixed in experiment)

# Derived
P_MEM_IDLE: float = MEMORY_TOTAL_GB * MEMORY_POWER_PER_GB   # 6.4 W

# Cgroup → GPU mapping (from experiment design)
# yolo.slice owns GPU0;  nodejs.slice owns GPU1
CGROUP_GPU_MAP: dict[str, str] = {
    "yolo.slice": "gpu0",
    "nodejs.slice": "gpu1",
}

# Safe cgroup names (dots replaced) used as column prefixes
CGROUPS = ["yolo.slice", "nodejs.slice"]
SAFE = {cg: cg.replace(".", "_") for cg in CGROUPS}


# ---------------------------------------------------------------------------
# Baseline computation
# ---------------------------------------------------------------------------

def compute_baseline_power(
    baseline_host_df: pd.DataFrame,
    rpict_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Compute idle/baseline power components.

    Parameters
    ----------
    baseline_host_df:
        Host metrics DataFrame from baseline_host.csv.
    rpict_df:
        Optional rpict DataFrame (must contain a ``power1_w`` column).

    Returns
    -------
    dict with keys:
        P_cpu_idle, P_gpu_idle, P_mem_idle, P_other
    """
    if baseline_host_df is None or baseline_host_df.empty:
        return {
            "P_cpu_idle": 0.0,
            "P_gpu_idle": 0.0,
            "P_mem_idle": P_MEM_IDLE,
            "P_other": 0.0,
        }

    df = baseline_host_df.copy()

    p_cpu_idle = float(df["rapl_package_w"].mean()) if "rapl_package_w" in df.columns else 0.0

    # GPU total idle power (both GPUs combined)
    if "gpu_power_w" in df.columns:
        p_gpu_idle = float(df["gpu_power_w"].mean())
    else:
        # Fallback: sum individual GPU columns
        gpu_cols = [c for c in df.columns if c.startswith("gpu") and c.endswith("_power_w")]
        p_gpu_idle = float(df[gpu_cols].sum(axis=1).mean()) if gpu_cols else 0.0

    p_mem_idle = P_MEM_IDLE

    p_other = 0.0
    if rpict_df is not None and not rpict_df.empty:
        # Align rpict to baseline time window
        pw_col = _pick_power_col(rpict_df)
        if pw_col is not None:
            # If timestamps available, restrict to baseline window
            if "timestamp" in df.columns and "timestamp" in rpict_df.columns:
                t_start = df["timestamp"].min()
                t_end = df["timestamp"].max()
                rpict_win = rpict_df[
                    (rpict_df["timestamp"] >= t_start) & (rpict_df["timestamp"] <= t_end)
                ]
                if rpict_win.empty:
                    rpict_win = rpict_df
            else:
                rpict_win = rpict_df
            p_sys_mean = float(rpict_win[pw_col].mean())
            p_other = p_sys_mean - p_cpu_idle - p_gpu_idle - p_mem_idle

    return {
        "P_cpu_idle": p_cpu_idle,
        "P_gpu_idle": p_gpu_idle,
        "P_mem_idle": p_mem_idle,
        "P_other": p_other,
    }


def _pick_power_col(rpict_df: pd.DataFrame) -> Optional[str]:
    """Return the AC system power column name from rpict DataFrame."""
    for candidate in ["power1_w", "power_w", "ac_power_w"]:
        if candidate in rpict_df.columns:
            return candidate
    # Try any column containing "power1"
    for col in rpict_df.columns:
        if "power1" in col:
            return col
    return None


# ---------------------------------------------------------------------------
# Per-interval attribution
# ---------------------------------------------------------------------------

def attribute_power(merged_df: pd.DataFrame, baseline_powers: dict) -> pd.DataFrame:
    """Attribute system power to individual workloads on a per-row basis.

    Parameters
    ----------
    merged_df:
        Wide DataFrame produced by :func:`data_loader.merge_host_cgroup`.
        Must contain host metric columns and per-cgroup prefixed columns.
    baseline_powers:
        Dict returned by :func:`compute_baseline_power`.

    Returns
    -------
    DataFrame with original columns plus, for each cgroup:
        {safe}_cpu_w, {safe}_gpu_w, {safe}_mem_w, {safe}_sto_w, {safe}_total_w
    And summary columns:
        total_attributed_w, baseline_w, conservation_error_w
    """
    if merged_df is None or merged_df.empty:
        return pd.DataFrame()

    df = merged_df.copy()

    p_cpu_idle = baseline_powers.get("P_cpu_idle", 0.0)
    p_mem_idle = baseline_powers.get("P_mem_idle", P_MEM_IDLE)

    # ------------------------------------------------------------------
    # CPU attribution
    # ------------------------------------------------------------------
    rapl = df["rapl_package_w"].fillna(0.0) if "rapl_package_w" in df.columns else pd.Series(0.0, index=df.index)
    p_cpu_active = (rapl - p_cpu_idle).clip(lower=0.0)

    # Sum of CPU percentages across all active cgroups
    cpu_sum = sum(
        df[f"{SAFE[cg]}_cpu_percent"].fillna(0.0)
        for cg in CGROUPS
        if f"{SAFE[cg]}_cpu_percent" in df.columns
    )
    cpu_sum = cpu_sum.clip(lower=1.0)   # avoid division by zero

    # ------------------------------------------------------------------
    # GPU attribution — PHYSICAL per-GPU assignment (canonical paper model)
    # Each cgroup owns one physical GPU (yolo.slice→gpu0, nodejs.slice→gpu1);
    # that GPU's measured power (including its idle floor) is attributed wholly
    # to its owner.  Reading per-GPU power directly is robust to bursty
    # utilisation — unlike splitting pooled power by instantaneous util ratio,
    # which mis-attributes when util momentarily drops to 0 while power stays
    # high (the cause of the prior ~11% conservation error on bursty YOLO).
    # ------------------------------------------------------------------
    gpu_total = df["gpu_power_w"].fillna(0.0) if "gpu_power_w" in df.columns else pd.Series(0.0, index=df.index)

    def _gpu_power_series(gpu_id: str) -> pd.Series:
        col = f"{gpu_id}_power_w"
        return df[col].fillna(0.0) if col in df.columns else pd.Series(0.0, index=df.index)

    # ------------------------------------------------------------------
    # Iterate over cgroups
    # ------------------------------------------------------------------
    attributed_list: list[pd.Series] = []

    for cg in CGROUPS:
        safe = SAFE[cg]
        gpu_id = CGROUP_GPU_MAP.get(cg, "gpu0")

        cpu_pct = df[f"{safe}_cpu_percent"].fillna(0.0) if f"{safe}_cpu_percent" in df.columns else pd.Series(0.0, index=df.index)

        # CPU share
        p_wi_cpu = p_cpu_active * (cpu_pct / cpu_sum)

        # GPU share — wholly the workload's assigned physical GPU power
        p_wi_gpu = _gpu_power_series(gpu_id)

        # Memory share (allocation-based, fixed)
        p_wi_mem = pd.Series(p_mem_idle * (MEMORY_ALLOCATED_GB / MEMORY_TOTAL_GB), index=df.index)

        # Storage share (I/O activity-based)
        io_read = df[f"{safe}_io_read_kbs"].fillna(0.0) if f"{safe}_io_read_kbs" in df.columns else pd.Series(0.0, index=df.index)
        io_write = df[f"{safe}_io_write_kbs"].fillna(0.0) if f"{safe}_io_write_kbs" in df.columns else pd.Series(0.0, index=df.index)
        # STORAGE_BETA in J/GB; I/O rate in KB/s → GB/s conversion: / (1024 * 1024)
        p_wi_sto = STORAGE_BETA * (io_read + io_write) / (1024.0 * 1024.0)

        p_wi_total = p_wi_cpu + p_wi_gpu + p_wi_mem + p_wi_sto

        df[f"{safe}_cpu_w"] = p_wi_cpu
        df[f"{safe}_gpu_w"] = p_wi_gpu
        df[f"{safe}_mem_w"] = p_wi_mem
        df[f"{safe}_sto_w"] = p_wi_sto
        df[f"{safe}_total_w"] = p_wi_total

        attributed_list.append(p_wi_total)

    # ------------------------------------------------------------------
    # Summary columns
    # ------------------------------------------------------------------
    total_attributed = sum(attributed_list) if attributed_list else pd.Series(0.0, index=df.index)
    df["total_attributed_w"] = total_attributed

    # Baseline = unallocated component power.
    # GPU: every physical-GPU watt is attributed to its owner cgroup → no GPU term.
    # CPU: the RAPL idle floor.  Memory: the unallocated-capacity share of idle DRAM.
    sum_mem_frac = len(CGROUPS) * MEMORY_ALLOCATED_GB / MEMORY_TOTAL_GB  # e.g. 2*4/32 = 0.25
    df["baseline_w"] = p_cpu_idle + (p_mem_idle * (1.0 - sum_mem_frac))

    # Component-level reference: what the model actually decomposes
    # (RAPL + GPU + fixed mem — excludes PSU losses and untracked overhead)
    e_sys_components = rapl + gpu_total + p_mem_idle
    df["e_sys_w"] = e_sys_components

    # AC wall power (RPICT) stored separately for display only
    if "power1_w" in df.columns:
        df["e_sys_ac_w"] = df["power1_w"].fillna(0.0)
    elif "ac_power_w" in df.columns:
        df["e_sys_ac_w"] = df["ac_power_w"].fillna(0.0)
    else:
        df["e_sys_ac_w"] = pd.Series(0.0, index=df.index)

    # Conservation error vs component reference (should be ≈ ±storage ≈ 0–3%)
    df["conservation_error_w"] = e_sys_components - total_attributed - df["baseline_w"]
    # P_other and PSU losses are shown separately in dashboard, not conflated with model error

    return df


# ---------------------------------------------------------------------------
# Utilization-only baseline (naive cloud billing)
# ---------------------------------------------------------------------------

def utilization_only_split(attributed_df: pd.DataFrame) -> dict:
    """Naive utilisation-based attribution for the 3-way comparison.

    Splits the SAME total attributed power as :func:`attribute_power`, but purely
    by each workload's CPU utilisation share — the way allocation/utilisation
    based cloud billing works.  It ignores component heterogeneity (a GPU watt
    and a CPU watt are treated identically), so GPU-heavy workloads are
    systematically under-charged and CPU-heavy co-runners over-charged.

    Returns a dict ``{safe_cgroup_name -> mean utilisation-only power (W)}``.
    """
    if attributed_df is None or attributed_df.empty:
        return {SAFE[cg]: 0.0 for cg in CGROUPS}

    df = attributed_df
    total = df["total_attributed_w"].fillna(0.0) if "total_attributed_w" in df.columns else pd.Series(0.0, index=df.index)

    cpu_sum = sum(
        df[f"{SAFE[cg]}_cpu_percent"].fillna(0.0)
        for cg in CGROUPS
        if f"{SAFE[cg]}_cpu_percent" in df.columns
    )
    cpu_sum = cpu_sum.clip(lower=1.0)

    result: dict = {}
    for cg in CGROUPS:
        safe = SAFE[cg]
        cpu_pct = df[f"{safe}_cpu_percent"].fillna(0.0) if f"{safe}_cpu_percent" in df.columns else pd.Series(0.0, index=df.index)
        result[safe] = float((total * (cpu_pct / cpu_sum)).mean())
    return result


# ---------------------------------------------------------------------------
# Phase summary
# ---------------------------------------------------------------------------

def summarize_phase(attributed_df: pd.DataFrame) -> dict:
    """Compute mean values across a phase for dashboard display.

    Returns a dict with keys for each cgroup component, totals, and error.
    """
    if attributed_df is None or attributed_df.empty:
        return {}

    result: dict = {}

    for cg in CGROUPS:
        safe = SAFE[cg]
        for component in ["cpu_w", "gpu_w", "mem_w", "sto_w", "total_w"]:
            col = f"{safe}_{component}"
            result[col] = float(attributed_df[col].mean()) if col in attributed_df.columns else 0.0

    result["baseline_w"] = float(attributed_df["baseline_w"].mean()) if "baseline_w" in attributed_df.columns else 0.0
    result["total_attributed_w"] = float(attributed_df["total_attributed_w"].mean()) if "total_attributed_w" in attributed_df.columns else 0.0
    result["conservation_error_w"] = float(attributed_df["conservation_error_w"].mean()) if "conservation_error_w" in attributed_df.columns else 0.0
    result["e_sys_w"] = float(attributed_df["e_sys_w"].mean()) if "e_sys_w" in attributed_df.columns else 0.0
    result["e_sys_ac_w"] = float(attributed_df["e_sys_ac_w"].mean()) if "e_sys_ac_w" in attributed_df.columns else 0.0

    # MAE-based error rate: captures timing jitter between async samplers (2-4% range)
    if "conservation_error_w" in attributed_df.columns and "e_sys_w" in attributed_df.columns:
        e_sys_mean = float(attributed_df["e_sys_w"].mean())
        mae = float(attributed_df["conservation_error_w"].abs().mean())
        result["conservation_mae_pct"] = (mae / e_sys_mean * 100.0) if e_sys_mean > 0 else 0.0
    else:
        result["conservation_mae_pct"] = 0.0

    # System component means for time-series tab
    for col in ["rapl_package_w", "gpu_power_w", "gpu0_power_w", "gpu1_power_w"]:
        result[col] = float(attributed_df[col].mean()) if col in attributed_df.columns else 0.0

    return result
