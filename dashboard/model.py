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
    p_gpu_idle = baseline_powers.get("P_gpu_idle", 0.0)
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
    # GPU attribution
    # ------------------------------------------------------------------
    gpu_total = df["gpu_power_w"].fillna(0.0) if "gpu_power_w" in df.columns else pd.Series(0.0, index=df.index)
    p_gpu_act = (gpu_total - p_gpu_idle).clip(lower=0.0)

    # Number of active GPUs (util > 0) – used for idle GPU sharing
    def _gpu_util_series(gpu_id: str) -> pd.Series:
        col = f"{gpu_id}_util_pct"
        return df[col].fillna(0.0) if col in df.columns else pd.Series(0.0, index=df.index)

    gpu0_util = _gpu_util_series("gpu0")
    gpu1_util = _gpu_util_series("gpu1")
    n_active_gpus = ((gpu0_util > 0).astype(float) + (gpu1_util > 0).astype(float)).clip(lower=1.0)

    # GPU utilisation sum across assigned cgroups
    gpu_util_sum = (gpu0_util + gpu1_util).clip(lower=1.0)

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

        # GPU share
        # Idle portion: proportional allocation among active GPUs
        uses_gpu = (_gpu_util_series(gpu_id) > 0).astype(float)
        a_i = uses_gpu / n_active_gpus

        # Active portion: proportional to the workload's assigned GPU utilisation
        gpu_util_i = _gpu_util_series(gpu_id)
        p_wi_gpu = p_gpu_idle * a_i + p_gpu_act * (gpu_util_i / gpu_util_sum)

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

    # Baseline = unallocated portions of CPU idle + GPU idle + mem idle + P_other
    # GPU idle already partially attributed to workloads via a_i; only the remainder stays in baseline
    sum_ai = pd.Series(0.0, index=df.index)
    for cg in CGROUPS:
        gpu_id = CGROUP_GPU_MAP.get(cg, "gpu0")
        uses_gpu = (
            (df[f"{gpu_id}_util_pct"].fillna(0.0) if f"{gpu_id}_util_pct" in df.columns else pd.Series(0.0, index=df.index))
            > 0
        ).astype(float)
        sum_ai += uses_gpu / n_active_gpus

    sum_mem_frac = len(CGROUPS) * MEMORY_ALLOCATED_GB / MEMORY_TOTAL_GB  # e.g. 2*4/32 = 0.25

    p_other = baseline_powers.get("P_other", 0.0)
    df["baseline_w"] = (
        p_cpu_idle
        + (p_gpu_idle * (1.0 - sum_ai)).clip(lower=0.0)
        + (p_mem_idle * (1.0 - sum_mem_frac))
        + p_other
    )

    # Conservation error relative to AC measurement (rpict)
    # If rpict column present in merged_df, use it; otherwise use RAPL+GPU as proxy
    if "power1_w" in df.columns:
        e_sys = df["power1_w"].fillna(0.0)
    elif "ac_power_w" in df.columns:
        e_sys = df["ac_power_w"].fillna(0.0)
    else:
        # Proxy: RAPL + GPU total + mem idle estimate
        e_sys = rapl + gpu_total + p_mem_idle

    df["e_sys_w"] = e_sys
    df["conservation_error_w"] = e_sys - total_attributed - df["baseline_w"]

    return df


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

    # System component means for time-series tab
    for col in ["rapl_package_w", "gpu_power_w", "gpu0_power_w", "gpu1_power_w"]:
        result[col] = float(attributed_df[col].mean()) if col in attributed_df.columns else 0.0

    return result
