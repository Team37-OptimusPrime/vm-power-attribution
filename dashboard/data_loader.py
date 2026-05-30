"""data_loader.py – VM Power Attribution Dashboard
Data discovery and loading utilities for Alienware experiment runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CGROUP_NAMES = ["yolo.slice", "nodejs.slice"]


# ---------------------------------------------------------------------------
# Run discovery
# ---------------------------------------------------------------------------

def find_run_dirs(base_data_dir: Path) -> list[dict]:
    """Return a list of run descriptor dicts sorted by run name.

    Each dict has:
        run_name       – directory name (e.g. "phase3_fixed_run3")
        alienware_path – absolute Path to the alienware run directory
        rpict_path     – absolute Path to an rpict CSV (or None)
    """
    alienware_root = base_data_dir / "alienware"
    rpict_root = base_data_dir / "rpict"

    if not alienware_root.exists():
        return []

    runs: list[dict] = []

    for candidate in sorted(alienware_root.iterdir()):
        if not candidate.is_dir():
            continue
        # A valid run directory must contain at least one *_host.csv
        host_files = list(candidate.glob("*_host.csv"))
        if not host_files:
            continue

        run_name = candidate.name
        rpict_path = _find_rpict(base_data_dir, rpict_root, run_name)

        runs.append(
            {
                "run_name": run_name,
                "alienware_path": candidate,
                "rpict_path": rpict_path,
            }
        )

    return runs


def _find_rpict(base_data_dir: Path, rpict_root: Path, run_name: str) -> Optional[Path]:
    """Try multiple strategies to locate an rpict CSV for *run_name*."""
    # Strategy 1: integrated run – data/raw/run_info_{RUN_ID}.json
    for info_file in base_data_dir.glob("run_info_*.json"):
        try:
            with info_file.open() as fh:
                info = json.load(fh)
            if info.get("run_name") == run_name or info.get("alienware_dir", "").endswith(run_name):
                rpict_rel = info.get("rpict_path")
                if rpict_rel:
                    p = Path(rpict_rel)
                    if not p.is_absolute():
                        p = base_data_dir / p
                    if p.exists():
                        return p
        except Exception:
            continue

    # Strategy 2: data/raw/rpict/{run_name}/rpict.csv
    candidate = rpict_root / run_name / "rpict.csv"
    if candidate.exists():
        return candidate

    # Strategy 3: data/raw/rpict/{run_name}.csv  (flat naming)
    candidate = rpict_root / f"{run_name}.csv"
    if candidate.exists():
        return candidate

    # Strategy 4: heuristic – strip directory prefix (e.g. phase3_fixed_run3 → phase3_run3)
    parts = run_name.split("_")
    for skip in range(1, len(parts)):
        guessed = "_".join(parts[:1] + parts[skip:])
        candidate = rpict_root / f"{guessed}.csv"
        if candidate.exists():
            return candidate

    return None


# ---------------------------------------------------------------------------
# Phase listing
# ---------------------------------------------------------------------------

def list_phases(alienware_dir: Path) -> list[str]:
    """Return sorted list of phase prefixes (excluding 'baseline').

    A phase prefix is derived from *_host.csv filenames.
    """
    prefixes: list[str] = []
    for f in sorted(alienware_dir.glob("*_host.csv")):
        prefix = f.stem.replace("_host", "")
        if prefix == "baseline":
            continue
        prefixes.append(prefix)
    return prefixes


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _read_csv_safe(path: Path) -> Optional[pd.DataFrame]:
    """Read a CSV, returning None if the file does not exist or is malformed."""
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        return df
    except Exception:
        return None


def load_phase(alienware_dir: Path, phase_prefix: str) -> dict:
    """Load host and cgroup CSVs for a given phase prefix.

    Returns a dict::

        {
            "host":   DataFrame or None,
            "cgroup": DataFrame or None,
        }
    """
    host_path = alienware_dir / f"{phase_prefix}_host.csv"
    cgroup_path = alienware_dir / f"{phase_prefix}_cgroup.csv"
    return {
        "host": _read_csv_safe(host_path),
        "cgroup": _read_csv_safe(cgroup_path),
    }


def load_baseline(alienware_dir: Path) -> dict:
    """Load baseline host and cgroup CSVs.

    Returns the same dict shape as :func:`load_phase`.
    """
    return {
        "host": _read_csv_safe(alienware_dir / "baseline_host.csv"),
        "cgroup": _read_csv_safe(alienware_dir / "baseline_cgroup.csv"),
    }


def load_rpict(rpict_path: Optional[Path]) -> Optional[pd.DataFrame]:
    """Load an rpict CSV.  Returns None when *rpict_path* is None or missing."""
    if rpict_path is None:
        return None
    df = _read_csv_safe(rpict_path)
    if df is None:
        return None
    # Normalise column names – some older files may use slightly different names
    df.columns = [c.strip().lower() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# Merging host + cgroup
# ---------------------------------------------------------------------------

def merge_host_cgroup(host_df: pd.DataFrame, cgroup_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Merge a host DataFrame with a cgroup DataFrame on nearest timestamp.

    The cgroup CSV has one row per cgroup per timestamp.  This function pivots
    the cgroup data wide (one row per timestamp, columns prefixed by cgroup name)
    and then merge-asof aligns with the host rows.

    Returns a wide DataFrame with all host columns plus per-cgroup columns:
        {cgroup_name}_cpu_percent
        {cgroup_name}_memory_mb
        {cgroup_name}_io_read_kbs
        {cgroup_name}_io_write_kbs
    """
    if host_df is None or host_df.empty:
        return pd.DataFrame()

    # Ensure host timestamps are datetime and sorted
    hdf = host_df.copy()
    hdf["timestamp"] = pd.to_datetime(hdf["timestamp"], errors="coerce")
    hdf = hdf.sort_values("timestamp").reset_index(drop=True)

    if cgroup_df is None or cgroup_df.empty:
        # Return host with zero-filled cgroup columns
        for cg in CGROUP_NAMES:
            safe = cg.replace(".", "_")
            for col in ["cpu_percent", "memory_mb", "io_read_kbs", "io_write_kbs"]:
                hdf[f"{safe}_{col}"] = 0.0
        return hdf

    cdf = cgroup_df.copy()
    cdf["timestamp"] = pd.to_datetime(cdf["timestamp"], errors="coerce")
    cdf = cdf.sort_values("timestamp").reset_index(drop=True)

    # Pivot cgroup data wide: one timestamp block → multiple cgroup rows → one wide row
    cgroup_col = "cgroup" if "cgroup" in cdf.columns else cdf.columns[1]
    metric_cols = ["cpu_percent", "memory_mb", "io_read_kbs", "io_write_kbs"]
    available_metrics = [c for c in metric_cols if c in cdf.columns]

    # Build a per-cgroup time-series and merge_asof each one into hdf
    merged = hdf.copy()
    for cg in CGROUP_NAMES:
        safe = cg.replace(".", "_")
        sub = cdf[cdf[cgroup_col] == cg][["timestamp"] + available_metrics].copy()
        sub = sub.sort_values("timestamp").reset_index(drop=True)

        if sub.empty:
            for col in available_metrics:
                merged[f"{safe}_{col}"] = 0.0
            continue

        # Rename columns
        sub = sub.rename(columns={c: f"{safe}_{c}" for c in available_metrics})

        merged = pd.merge_asof(
            merged,
            sub,
            on="timestamp",
            direction="nearest",
            tolerance=pd.Timedelta("5s"),
        )
        # Fill NaNs introduced by merge
        for col in available_metrics:
            col_name = f"{safe}_{col}"
            if col_name in merged.columns:
                merged[col_name] = merged[col_name].fillna(0.0)

    # Add missing cgroup columns with zeros if not present
    for cg in CGROUP_NAMES:
        safe = cg.replace(".", "_")
        for col in metric_cols:
            col_name = f"{safe}_{col}"
            if col_name not in merged.columns:
                merged[col_name] = 0.0

    return merged
