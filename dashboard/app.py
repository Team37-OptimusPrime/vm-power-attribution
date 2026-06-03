"""app.py – VM Power Attribution Dashboard (Streamlit)
Visualises per-workload power attribution for Alienware AI workload experiments.
Run with:  streamlit run app.py
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loader import (
    find_run_dirs,
    list_phases,
    load_baseline,
    load_phase,
    load_rpict,
    merge_host_cgroup,
)
from model import attribute_power, compute_baseline_power, summarize_phase

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="VM 전력 귀속 대시보드",
    page_icon="⚡",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DATA_DIR: Path = Path(__file__).parent.parent / "data" / "raw"

PHASE_LABELS: dict[str, str] = {
    "baseline": "Baseline (Idle)",
    "A2_yolo_medium": "YOLO Medium",
    "PT_pytorch_gemm": "PyTorch GEMM",
    "RN_resnet18": "ResNet18",
    "GPT_gpt2": "GPT-2",
    "B2_nodejs_heavy": "Node.js Heavy",
    "A2B2_concurrent": "YOLO + Node.js",
    "PTB2_concurrent": "PyTorch + Node.js",
    "RNB2_concurrent": "ResNet + Node.js",
    "GPTB2_concurrent": "GPT-2 + Node.js",
    "A2PT_concurrent": "YOLO + PyTorch",
    "A2RN_concurrent": "YOLO + ResNet",
    "A2GPT_concurrent": "YOLO + GPT-2",
    "PTRN_concurrent": "PyTorch + ResNet",
    "PTGPT_concurrent": "PyTorch + GPT-2",
    "RNGPT_concurrent": "ResNet + GPT-2",
}

CGROUPS = ["yolo.slice", "nodejs.slice"]
SAFE = {cg: cg.replace(".", "_") for cg in CGROUPS}
CGROUP_LABELS = {
    "yolo.slice": "YOLO (yolo.slice)",
    "nodejs.slice": "Node.js (nodejs.slice)",
}

COMPONENT_COLORS = {
    "cpu": "#4C78A8",   # blue
    "gpu": "#E45756",   # red
    "mem": "#54A24B",   # green
    "sto": "#F58518",   # orange
}

COMPONENT_LABELS = {
    "cpu": "CPU",
    "gpu": "GPU",
    "mem": "메모리",
    "sto": "스토리지",
}


# ---------------------------------------------------------------------------
# Caching helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=5, show_spinner=False)
def cached_find_run_dirs(base: str) -> list[dict]:
    return find_run_dirs(Path(base))


@st.cache_data(ttl=5, show_spinner=False)
def cached_load_baseline(alienware_path: str) -> dict:
    return load_baseline(Path(alienware_path))


@st.cache_data(ttl=5, show_spinner=False)
def cached_load_rpict(rpict_path: Optional[str]) -> Optional[pd.DataFrame]:
    return load_rpict(Path(rpict_path) if rpict_path else None)


@st.cache_data(ttl=5, show_spinner=False)
def cached_load_phase(alienware_path: str, phase_prefix: str) -> dict:
    return load_phase(Path(alienware_path), phase_prefix)


def _phase_label(prefix: str) -> str:
    return PHASE_LABELS.get(prefix, prefix)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> tuple[Optional[dict], list[str], bool, bool, int]:
    """Render sidebar controls.  Returns (selected_run, selected_phases, refreshed, live_mode, interval)."""
    st.sidebar.title("⚡ VM 전력 귀속")
    st.sidebar.markdown("---")

    # ------------------------------------------------------------------
    # Live mode
    # ------------------------------------------------------------------
    live_mode = st.sidebar.toggle("🔴 실시간 모드", value=False, help="실험 진행 중 자동으로 새 데이터를 반영합니다.")
    interval = 5
    if live_mode:
        interval = st.sidebar.slider("갱신 주기 (초)", min_value=2, max_value=30, value=5, step=1)
        st.sidebar.caption(f"⏱ {interval}초마다 자동 갱신")

    refreshed = st.sidebar.button("🔄 새로고침", use_container_width=True)
    if refreshed:
        st.cache_data.clear()

    st.sidebar.subheader("실험 선택")

    runs = cached_find_run_dirs(str(BASE_DATA_DIR))
    if not runs:
        st.sidebar.error(f"데이터 디렉토리를 찾을 수 없습니다:\n{BASE_DATA_DIR}")
        return None, [], refreshed, live_mode, interval

    run_names = [r["run_name"] for r in runs]

    # In live mode: pick run with most recently modified CSV
    if live_mode:
        def _latest_mtime(r: dict) -> float:
            csvs = list(Path(r["alienware_path"]).glob("*.csv"))
            return max((f.stat().st_mtime for f in csvs), default=0.0)
        latest_run = max(runs, key=_latest_mtime)
        default_run_idx = run_names.index(latest_run["run_name"])
    else:
        default_run_idx = len(run_names) - 1

    selected_run_name = st.sidebar.selectbox(
        "실험 런",
        options=run_names,
        index=default_run_idx,
        format_func=lambda x: x,
    )
    selected_run = next(r for r in runs if r["run_name"] == selected_run_name)

    # Show live indicator if a CSV was written in the last 15 s
    if live_mode:
        csvs = list(Path(selected_run["alienware_path"]).glob("*.csv"))
        if csvs:
            age = time.time() - max(f.stat().st_mtime for f in csvs)
            if age < 15:
                st.sidebar.success(f"● 실험 진행 중 (마지막 기록 {age:.0f}초 전)")

    # Phase selector
    alienware_path = selected_run["alienware_path"]
    all_phases = list_phases(alienware_path)

    if not all_phases:
        st.sidebar.warning("해당 런에 Phase 데이터가 없습니다.")
        return selected_run, [], refreshed, live_mode, interval

    phase_label_map = {p: _phase_label(p) for p in all_phases}
    all_labels = list(phase_label_map.values())

    select_all = st.sidebar.checkbox("전체 선택", value=False)

    selected_labels = st.sidebar.multiselect(
        "워크로드(Phase) 선택",
        options=all_labels,
        default=all_labels if select_all else all_labels[:1],
        help="여러 Phase를 선택하면 그룹 막대 차트로 비교합니다.",
    )

    # Reverse mapping label → prefix
    label_to_prefix = {v: k for k, v in phase_label_map.items()}
    selected_phases = all_phases if select_all else [label_to_prefix[lbl] for lbl in selected_labels if lbl in label_to_prefix]

    if selected_run.get("rpict_path") is None:
        st.sidebar.info("ℹ️ RPICT 파일 없음 – AC 전력 측정값 미표시")

    st.sidebar.markdown("---")
    st.sidebar.caption(f"데이터 경로: `{BASE_DATA_DIR}`")

    return selected_run, selected_phases, refreshed, live_mode, interval


# ---------------------------------------------------------------------------
# Tab 1: 시스템 전력 프로파일
# ---------------------------------------------------------------------------

def _add_rpict_to_fig(fig: go.Figure, rpict_df: Optional[pd.DataFrame], t_ref: pd.Timestamp) -> None:
    """Add AC power trace from rpict to *fig*."""
    if rpict_df is None or rpict_df.empty:
        return
    pw_col = None
    for candidate in ["power1_w", "power_w", "ac_power_w"]:
        if candidate in rpict_df.columns:
            pw_col = candidate
            break
    if pw_col is None:
        return
    ts_col = "timestamp" if "timestamp" in rpict_df.columns else rpict_df.columns[0]
    rdf = rpict_df[[ts_col, pw_col]].dropna().copy()
    rdf[ts_col] = pd.to_datetime(rdf[ts_col], errors="coerce")
    rdf = rdf.dropna(subset=[ts_col]).sort_values(ts_col)
    elapsed = (rdf[ts_col] - t_ref).dt.total_seconds()
    fig.add_trace(go.Scatter(
        x=elapsed, y=rdf[pw_col],
        name="AC 전력 (RPICT)",
        line=dict(color="black", dash="dot", width=1.5),
        opacity=0.8,
    ))


def render_tab_system_power(
    selected_run: dict,
    selected_phases: list[str],
    baseline_host_df: Optional[pd.DataFrame],
) -> None:
    st.subheader("시스템 전력 프로파일")

    if not selected_phases:
        st.info("왼쪽 사이드바에서 Phase를 선택하세요.")
        return

    alienware_path = selected_run["alienware_path"]
    rpict_path = selected_run.get("rpict_path")
    rpict_df = cached_load_rpict(str(rpict_path) if rpict_path else None)

    fig = go.Figure()
    color_cycle = ["#4C78A8", "#E45756", "#54A24B", "#F58518", "#B279A2", "#9D755D"]

    phase_boundaries: list[tuple[float, float, str]] = []

    global_t_ref: Optional[pd.Timestamp] = None

    for idx, phase_prefix in enumerate(selected_phases):
        phase_data = cached_load_phase(str(alienware_path), phase_prefix)
        host_df = phase_data.get("host")
        if host_df is None or host_df.empty:
            continue

        host_df = host_df.copy()
        host_df["timestamp"] = pd.to_datetime(host_df["timestamp"], errors="coerce")
        host_df = host_df.sort_values("timestamp").dropna(subset=["timestamp"])

        if host_df.empty:
            continue

        if global_t_ref is None:
            global_t_ref = host_df["timestamp"].iloc[0]

        t_ref = host_df["timestamp"].iloc[0]
        elapsed = (host_df["timestamp"] - global_t_ref).dt.total_seconds()

        col = color_cycle[idx % len(color_cycle)]
        lbl = _phase_label(phase_prefix)

        if "rapl_package_w" in host_df.columns:
            fig.add_trace(go.Scatter(
                x=elapsed, y=host_df["rapl_package_w"].fillna(0),
                name=f"{lbl} – RAPL CPU",
                line=dict(color=col, width=1.5),
            ))
        if "gpu0_power_w" in host_df.columns:
            fig.add_trace(go.Scatter(
                x=elapsed, y=host_df["gpu0_power_w"].fillna(0),
                name=f"{lbl} – GPU0",
                line=dict(color=col, width=1.5, dash="dash"),
            ))
        if "gpu1_power_w" in host_df.columns:
            fig.add_trace(go.Scatter(
                x=elapsed, y=host_df["gpu1_power_w"].fillna(0),
                name=f"{lbl} – GPU1",
                line=dict(color=col, width=1.5, dash="dot"),
            ))

        # Shaded region when single phase selected
        if len(selected_phases) == 1:
            x0 = float(elapsed.iloc[0])
            x1 = float(elapsed.iloc[-1])
            phase_boundaries.append((x0, x1, lbl))

    # Overlay rpict only if valid (mean >= 10W)
    if global_t_ref is not None and rpict_df is not None and not rpict_df.empty:
        _pw = next((c for c in ["power1_w", "power_w", "ac_power_w"] if c in rpict_df.columns), None)
        if _pw and float(rpict_df[_pw].mean()) >= 10.0:
            _add_rpict_to_fig(fig, rpict_df, global_t_ref)

    # Shading
    for x0, x1, lbl in phase_boundaries:
        fig.add_vrect(
            x0=x0, x1=x1,
            fillcolor="LightSalmon", opacity=0.15,
            layer="below", line_width=0,
            annotation_text=lbl,
            annotation_position="top left",
        )

    fig.update_layout(
        title="시스템 전력 시계열",
        xaxis_title="경과 시간 (초)",
        yaxis_title="전력 (W)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=500,
        template="plotly_white",
    )

    st.plotly_chart(fig, use_container_width=True)

    # Baseline reference line annotation
    if baseline_host_df is not None and not baseline_host_df.empty and "rapl_package_w" in baseline_host_df.columns:
        baseline_mean = float(baseline_host_df["rapl_package_w"].mean())
        st.caption(f"기준 CPU 전력 (Baseline): **{baseline_mean:.2f} W**")


# ---------------------------------------------------------------------------
# Tab 2: 워크로드별 에너지 귀속
# ---------------------------------------------------------------------------

def _build_attribution_bar(phase_summaries: dict[str, dict]) -> go.Figure:
    """Build a stacked bar chart from phase summaries."""
    fig = go.Figure()

    components = ["cpu", "gpu", "mem", "sto"]
    first = True

    for cg in CGROUPS:
        safe = SAFE[cg]
        cg_label = CGROUP_LABELS[cg]

        for comp in components:
            col = f"{safe}_{comp}_w"
            values = [phase_summaries[ph].get(col, 0.0) for ph in phase_summaries]
            x_labels = [
                f"{_phase_label(ph)}\n{cg_label}" for ph in phase_summaries
            ]

            fig.add_trace(go.Bar(
                name=f"{COMPONENT_LABELS[comp]} ({cg_label})" if first else COMPONENT_LABELS[comp],
                x=x_labels,
                y=values,
                marker_color=COMPONENT_COLORS[comp],
                legendgroup=comp,
                showlegend=first,
            ))
        first = False

    # Baseline bar
    baseline_values = [phase_summaries[ph].get("baseline_w", 0.0) for ph in phase_summaries]
    # Use the first phase's label for the baseline bar x position is handled separately
    fig.add_trace(go.Bar(
        name="Baseline",
        x=[f"Baseline\n(공통)" for _ in phase_summaries],
        y=baseline_values,
        marker_color="#BAB0AC",
        legendgroup="baseline",
        showlegend=True,
    ))

    fig.update_layout(
        barmode="stack",
        title="워크로드별 평균 전력 귀속 (W)",
        xaxis_title="워크로드 / Phase",
        yaxis_title="평균 전력 (W)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=520,
        template="plotly_white",
    )
    return fig


def _build_grouped_attribution_bar(phase_summaries: dict[str, dict]) -> go.Figure:
    """Grouped bars: X = phase, colour-coded by workload×component."""
    fig = go.Figure()

    phase_list = list(phase_summaries.keys())
    phase_display = [_phase_label(ph) for ph in phase_list]
    components = ["cpu", "gpu", "mem", "sto"]

    for cg in CGROUPS:
        safe = SAFE[cg]
        cg_label = CGROUP_LABELS[cg]
        for comp in components:
            col = f"{safe}_{comp}_w"
            values = [phase_summaries[ph].get(col, 0.0) for ph in phase_list]
            fig.add_trace(go.Bar(
                name=f"{cg_label} – {COMPONENT_LABELS[comp]}",
                x=phase_display,
                y=values,
                marker_color=COMPONENT_COLORS[comp],
                legendgroup=f"{safe}_{comp}",
            ))

    fig.update_layout(
        barmode="group",
        title="Phase별 워크로드 전력 귀속 비교 (W)",
        xaxis_title="Phase",
        yaxis_title="평균 전력 (W)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=520,
        template="plotly_white",
    )
    return fig


def render_tab_attribution(
    selected_run: dict,
    selected_phases: list[str],
    baseline_powers: dict,
) -> None:
    st.subheader("워크로드별 에너지 귀속")

    if not selected_phases:
        st.info("왼쪽 사이드바에서 Phase를 선택하세요.")
        return

    alienware_path = selected_run["alienware_path"]
    phase_summaries: dict[str, dict] = {}

    with st.spinner("귀속 모델 계산 중..."):
        for phase_prefix in selected_phases:
            phase_data = cached_load_phase(str(alienware_path), phase_prefix)
            host_df = phase_data.get("host")
            cgroup_df = phase_data.get("cgroup")

            if host_df is None or host_df.empty:
                st.warning(f"Phase '{phase_prefix}': host 데이터 없음. 건너뜀.")
                continue

            merged = merge_host_cgroup(host_df, cgroup_df)
            attributed = attribute_power(merged, baseline_powers)
            summary = summarize_phase(attributed)
            phase_summaries[phase_prefix] = summary

    if not phase_summaries:
        st.error("귀속 계산에 실패했습니다. 데이터를 확인하세요.")
        return

    if len(phase_summaries) == 1:
        fig = _build_attribution_bar(phase_summaries)
    else:
        fig = _build_grouped_attribution_bar(phase_summaries)

    st.plotly_chart(fig, use_container_width=True)

    # Summary table
    st.markdown("#### 상세 귀속 요약")
    rows = []
    for ph, summary in phase_summaries.items():
        row = {"Phase": _phase_label(ph)}
        for cg in CGROUPS:
            safe = SAFE[cg]
            cg_short = cg.split(".")[0]
            row[f"{cg_short} CPU (W)"] = f"{summary.get(f'{safe}_cpu_w', 0):.2f}"
            row[f"{cg_short} GPU (W)"] = f"{summary.get(f'{safe}_gpu_w', 0):.2f}"
            row[f"{cg_short} 메모리 (W)"] = f"{summary.get(f'{safe}_mem_w', 0):.2f}"
            row[f"{cg_short} 스토리지 (W)"] = f"{summary.get(f'{safe}_sto_w', 0):.2f}"
            row[f"{cg_short} 합계 (W)"] = f"{summary.get(f'{safe}_total_w', 0):.2f}"
        row["Baseline (W)"] = f"{summary.get('baseline_w', 0):.2f}"
        row["총 귀속 (W)"] = f"{summary.get('total_attributed_w', 0):.2f}"
        rows.append(row)

    st.dataframe(pd.DataFrame(rows).set_index("Phase"), use_container_width=True)


# ---------------------------------------------------------------------------
# Tab 3: 보존 검증
# ---------------------------------------------------------------------------

def render_tab_conservation(
    selected_run: dict,
    selected_phases: list[str],
    baseline_powers: dict,
) -> None:
    st.subheader("보존 검증 (Conservation Validation)")
    st.markdown(
        "시스템 측정 전력(RPICT AC, RAPL+GPU)과 귀속 모델 합계를 비교합니다. "
        "오차가 작을수록 모델의 정확도가 높습니다."
    )

    if not selected_phases:
        st.info("왼쪽 사이드바에서 Phase를 선택하세요.")
        return

    alienware_path = selected_run["alienware_path"]
    rpict_path = selected_run.get("rpict_path")
    rpict_df = cached_load_rpict(str(rpict_path) if rpict_path else None)

    # RPICT 유효성 검사: 평균 10W 미만이면 센서 미연결로 간주
    _rpict_valid = False
    if rpict_df is not None and not rpict_df.empty:
        for _c in ["power1_w", "power_w", "ac_power_w"]:
            if _c in rpict_df.columns and float(rpict_df[_c].mean()) >= 10.0:
                _rpict_valid = True
                break
    has_rpict = _rpict_valid
    if rpict_df is not None and not rpict_df.empty and not has_rpict:
        st.warning("⚠️ RPICT 데이터가 10W 미만입니다 — CT 클램프 미연결로 판단하여 AC 측정값을 제외합니다.")
    elif rpict_df is None or rpict_df.empty:
        st.warning("RPICT 파일이 없어 AC 측정값을 표시하지 않습니다.")

    phase_labels: list[str] = []
    model_totals: list[float] = []
    rapl_gpu_totals: list[float] = []
    rpict_totals: list[float] = []
    errors: list[float] = []

    with st.spinner("검증 계산 중..."):
        for phase_prefix in selected_phases:
            phase_data = cached_load_phase(str(alienware_path), phase_prefix)
            host_df = phase_data.get("host")
            cgroup_df = phase_data.get("cgroup")

            if host_df is None or host_df.empty:
                continue

            merged = merge_host_cgroup(host_df, cgroup_df)
            attributed = attribute_power(merged, baseline_powers)
            summary = summarize_phase(attributed)

            model_total = summary.get("total_attributed_w", 0.0) + summary.get("baseline_w", 0.0)
            rapl = summary.get("rapl_package_w", 0.0)
            gpu = summary.get("gpu_power_w", 0.0)
            mem_est = baseline_powers.get("P_mem_idle", 6.4)
            rapl_gpu = rapl + gpu + mem_est

            phase_labels.append(_phase_label(phase_prefix))
            model_totals.append(model_total)
            rapl_gpu_totals.append(rapl_gpu)

            # RPICT average for this phase's time window
            if has_rpict and "timestamp" in host_df.columns:
                host_df_ts = host_df.copy()
                host_df_ts["timestamp"] = pd.to_datetime(host_df_ts["timestamp"], errors="coerce")
                t_start = host_df_ts["timestamp"].min()
                t_end = host_df_ts["timestamp"].max()
                pw_col = None
                for c in ["power1_w", "power_w", "ac_power_w"]:
                    if c in rpict_df.columns:
                        pw_col = c
                        break
                ts_col_r = "timestamp" if "timestamp" in rpict_df.columns else rpict_df.columns[0]
                rdf_win = rpict_df.copy()
                rdf_win[ts_col_r] = pd.to_datetime(rdf_win[ts_col_r], errors="coerce")
                rdf_win = rdf_win[(rdf_win[ts_col_r] >= t_start) & (rdf_win[ts_col_r] <= t_end)]
                if pw_col and not rdf_win.empty:
                    rpict_mean = float(rdf_win[pw_col].mean())
                else:
                    rpict_mean = 0.0
                rpict_totals.append(rpict_mean)
                if rpict_mean > 0:
                    err_pct = abs(model_total - rpict_mean) / rpict_mean * 100.0
                else:
                    err_pct = 0.0
                errors.append(err_pct)
            else:
                rpict_totals.append(0.0)
                errors.append(0.0)

    if not phase_labels:
        st.error("계산할 Phase 데이터가 없습니다.")
        return

    # Bar chart
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="모델 귀속 합계",
        x=phase_labels, y=model_totals,
        marker_color="#4C78A8",
    ))
    fig.add_trace(go.Bar(
        name="RAPL+GPU+메모리 추정",
        x=phase_labels, y=rapl_gpu_totals,
        marker_color="#54A24B",
    ))
    if has_rpict and any(v > 0 for v in rpict_totals):
        fig.add_trace(go.Bar(
            name="AC 실측 (RPICT)",
            x=phase_labels, y=rpict_totals,
            marker_color="#F58518",
        ))

    fig.update_layout(
        barmode="group",
        title="전력 보존 검증: 모델 vs 측정",
        xaxis_title="Phase",
        yaxis_title="평균 전력 (W)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=480,
        template="plotly_white",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Error table
    if has_rpict and any(v > 0 for v in rpict_totals):
        st.markdown("#### 오차율 (모델 vs RPICT)")
        err_data = {
            "Phase": phase_labels,
            "모델 합계 (W)": [f"{v:.2f}" for v in model_totals],
            "RPICT AC (W)": [f"{v:.2f}" for v in rpict_totals],
            "오차율 (%)": [f"{e:.1f}%" for e in errors],
        }
        st.dataframe(pd.DataFrame(err_data).set_index("Phase"), use_container_width=True)

    # Metric tiles for single-phase selection
    if len(phase_labels) == 1:
        col1, col2, col3 = st.columns(3)
        col1.metric("모델 귀속 합계", f"{model_totals[0]:.1f} W")
        col2.metric("RAPL+GPU 추정", f"{rapl_gpu_totals[0]:.1f} W")
        if has_rpict and rpict_totals[0] > 0:
            col3.metric("AC 실측 (RPICT)", f"{rpict_totals[0]:.1f} W", f"오차 {errors[0]:.1f}%")
        else:
            col3.metric("AC 실측 (RPICT)", "N/A")


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main() -> None:
    selected_run, selected_phases, _, live_mode, interval = render_sidebar()

    if selected_run is None:
        st.title("⚡ VM 전력 귀속 대시보드")
        st.error(f"데이터 디렉토리({BASE_DATA_DIR})를 찾을 수 없습니다.")
        st.markdown("실험 데이터가 `data/raw/alienware/` 경로에 있는지 확인하세요.")
        return

    run_name = selected_run["run_name"]
    title_col, status_col = st.columns([4, 1])
    with title_col:
        st.title(f"⚡ VM 전력 귀속 대시보드 — `{run_name}`")
    with status_col:
        if live_mode:
            st.markdown("<br><span style='color:red; font-size:1.1em;'>● LIVE</span>", unsafe_allow_html=True)

    alienware_path = selected_run["alienware_path"]

    # Load baseline once per run
    with st.spinner("Baseline 데이터 로드 중..."):
        baseline_data = cached_load_baseline(str(alienware_path))
    baseline_host_df = baseline_data.get("host")
    rpict_path = selected_run.get("rpict_path")
    rpict_df = cached_load_rpict(str(rpict_path) if rpict_path else None)

    if baseline_host_df is None:
        st.warning("Baseline 데이터(`baseline_host.csv`)를 찾을 수 없습니다. Baseline 전력은 0으로 가정합니다.")

    baseline_powers = compute_baseline_power(baseline_host_df, rpict_df)

    tab1, tab2, tab3 = st.tabs([
        "📈 시스템 전력 프로파일",
        "📊 워크로드별 에너지 귀속",
        "🔍 보존 검증",
    ])

    with tab1:
        render_tab_system_power(selected_run, selected_phases, baseline_host_df)

    with tab2:
        render_tab_attribution(selected_run, selected_phases, baseline_powers)

    with tab3:
        render_tab_conservation(selected_run, selected_phases, baseline_powers)

    # ------------------------------------------------------------------
    # Live mode: sleep then rerun
    # ------------------------------------------------------------------
    if live_mode:
        time.sleep(interval)
        st.cache_data.clear()
        st.rerun()


if __name__ == "__main__":
    main()
