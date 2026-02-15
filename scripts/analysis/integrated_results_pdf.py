#!/usr/bin/env python3
"""
VM Power Attribution — 전체 실험 결과 통합 PDF
Phase 1.6 + Phase 2.0 (DIMM, fio) 결과를 한 파일로 시각화
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.patches as mpatches
from pathlib import Path

# ── Style ────────────────────────────────────────────────────────────
plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 9,
    'axes.labelsize': 10,
    'axes.titlesize': 11,
    'xtick.labelsize': 8,
    'ytick.labelsize': 8,
    'legend.fontsize': 8,
    'figure.titlesize': 13,
    'axes.linewidth': 0.8,
    'grid.linewidth': 0.4,
    'axes.spines.top': False,
    'axes.spines.right': False,
})

# Colorblind-friendly palette
C = {
    'cpu':    '#2A9D8F',
    'gpu':    '#E9C46A',
    'mem':    '#F4A261',
    'io':     '#E76F51',
    'other':  '#8D99AE',
    'wall':   '#1D3557',
    'yolo':   '#E63946',
    'node':   '#457B9D',
    'idle':   '#A8DADC',
    'conc':   '#9B5DE5',
    'pred':   '#264653',
    'meas':   '#E63946',
}

# ── Data ─────────────────────────────────────────────────────────────
LABELS = ['Idle', 'A1\nYOLO\nNano', 'A2\nYOLO\nMed', 'B1\nNode\nLight', 'B2\nNode\nHeavy',
          'A1+B1', 'A1+B2', 'A2+B1', 'A2+B2']
WALL  = [36.4, 119.2, 147.3,  41.8, 116.8, 120.0, 172.8, 152.1, 201.1]
CPU   = [ 5.3,  32.8,  32.3,   6.9,  57.1,  35.0,  70.6,  34.9,  71.0]
GPU   = [ 8.4,  39.2,  62.6,   8.4,   8.4,  38.7,  37.6,  62.9,  60.1]
OTHER = [w - c - g for w, c, g in zip(WALL, CPU, GPU)]

# Phase 2.0 DIMM
DIMM_RUNS  = [43.4, 43.5, 43.3]
DIMM_CPU   = [5.35, 5.38, 5.31]
DIMM_GPU   = [11.56, 11.66, 11.67]

# Phase 2.0 fio
FIO_LABELS = ['Idle', 'Seq\nRead', 'Seq\nWrite', 'Rand\nRead', 'Rand\nWrite']
FIO_WALL   = [43.4, 88.6, 59.2, 90.8, 89.3]
FIO_DCPU   = [0.0, 25.7, 7.8, 26.8, 26.2]
FIO_DIO    = [0.0, 19.4, 8.0, 20.5, 19.7]
FIO_IOPS   = ['—', '16,805\n(16.4 GB/s)', '2,213\n(2.2 GB/s)', '313K', '291K']
FIO_SSD_SPEC = 3.5  # Samsung 980 datasheet max


def _add_watermark(fig):
    fig.text(0.5, 0.005, 'Team 37 — OptimusPrime  |  Ewha Univ. Capstone 2025-2026  |  VM Power Attribution',
             ha='center', fontsize=7, color='#999999')


# ── PAGE 1 : Phase 1.6 Power Breakdown ──────────────────────────────
def page1_power_breakdown(pdf):
    fig, axes = plt.subplots(2, 1, figsize=(11, 8.5),
                             gridspec_kw={'height_ratios': [3, 1.8], 'hspace': 0.45})
    fig.suptitle('Phase 1.6 — Workload Power Breakdown  (9 Scenarios)',
                 fontweight='bold', y=0.97)

    # ── (a) Stacked bar ──
    ax = axes[0]
    x = np.arange(len(LABELS))
    w = 0.55

    ax.bar(x, CPU, w, label='CPU (RAPL)', color=C['cpu'], edgecolor='white', linewidth=0.5)
    ax.bar(x, GPU, w, bottom=CPU, label='GPU (nvidia-smi)', color=C['gpu'], edgecolor='white', linewidth=0.5)
    ax.bar(x, OTHER, w, bottom=np.array(CPU)+np.array(GPU),
           label='Others (unmetered)', color=C['other'], edgecolor='white', linewidth=0.5)

    # Wall power markers
    ax.scatter(x, WALL, marker='_', s=400, linewidths=2.5, color=C['wall'], zorder=5)
    for i in range(len(LABELS)):
        ax.text(i, WALL[i]+3, f'{WALL[i]}W', ha='center', fontsize=7.5, fontweight='bold', color=C['wall'])

    # Divider between solo and concurrent
    ax.axvline(4.5, color='grey', linestyle=':', linewidth=0.8)
    ax.text(2, 215, 'Solo Workloads', ha='center', fontsize=9, style='italic', color='#555')
    ax.text(6.5, 215, 'Concurrent', ha='center', fontsize=9, style='italic', color='#555')

    ax.set_ylabel('Power (W)')
    ax.set_xticks(x)
    ax.set_xticklabels(LABELS)
    ax.set_ylim(0, 225)
    ax.legend(loc='upper left', framealpha=0.9, ncol=3)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_title('(a) Power Component Stacked Bar', fontweight='bold', loc='left', fontsize=10)

    # ── (b) Others % table ──
    ax2 = axes[1]
    ax2.axis('off')

    col_labels = LABELS
    others_pct = [f'{o/w*100:.1f}%' for o, w in zip(OTHER, WALL)]
    d_wall  = ['—'] + [f'+{w - WALL[0]:.1f}' for w in WALL[1:]]
    d_cpu   = ['—'] + [f'+{c - CPU[0]:.1f}' for c in CPU[1:]]
    d_gpu   = ['—'] + [f'+{g - GPU[0]:.1f}' for g in GPU[1:]]
    d_other = ['—'] + [f'+{o - OTHER[0]:.1f}' for o in OTHER[1:]]

    table_data = [
        ['Wall (W)']     + [f'{v:.1f}' for v in WALL],
        ['CPU (W)']      + [f'{v:.1f}' for v in CPU],
        ['GPU (W)']      + [f'{v:.1f}' for v in GPU],
        ['Others (W)']   + [f'{v:.1f}' for v in OTHER],
        ['Others %']     + others_pct,
        ['dWall']        + d_wall,
        ['dCPU']         + d_cpu,
        ['dGPU']         + d_gpu,
        ['dOthers']      + d_other,
    ]

    table = ax2.table(cellText=table_data,
                      colLabels=[''] + list(LABELS),
                      loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(7.5)
    table.scale(1.0, 1.35)

    # Header styling
    for j in range(len(LABELS)+1):
        cell = table[0, j]
        cell.set_facecolor('#1D3557')
        cell.set_text_props(color='white', fontweight='bold')
    for i in range(1, len(table_data)+1):
        table[i, 0].set_facecolor('#f0f0f0')
        table[i, 0].set_text_props(fontweight='bold')

    ax2.set_title('(b) Full Measurement Table (Phase 1.6)', fontweight='bold', loc='left', fontsize=10,
                  pad=15)

    _add_watermark(fig)
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── PAGE 2 : Others Analysis + Nonlinearity ─────────────────────────
def page2_others_analysis(pdf):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    fig.suptitle('Phase 1.6 — "Others" Energy Analysis', fontweight='bold', y=0.98)

    # ── (a) Others grows with load ──
    ax = axes[0]
    solo_x = [0, 1, 2, 3, 4]
    solo_labels = ['Idle', 'A1', 'A2', 'B1', 'B2']
    solo_others = OTHER[:5]
    solo_wall   = WALL[:5]

    bars = ax.bar(solo_x, solo_others, 0.5, color=[C['idle'], C['yolo'], C['yolo'], C['node'], C['node']],
                  edgecolor='white', linewidth=0.5, alpha=0.85)
    for i, (o, w) in enumerate(zip(solo_others, solo_wall)):
        ax.text(i, o+1.2, f'{o:.1f}W\n({o/w*100:.0f}%)', ha='center', fontsize=8, fontweight='bold')

    ax.axhline(OTHER[0], color='grey', linestyle='--', linewidth=0.8, alpha=0.6)
    ax.text(4.3, OTHER[0]-1, f'Idle baseline\n{OTHER[0]:.1f}W', fontsize=7, color='grey')

    ax.set_ylabel('Others Power (W)')
    ax.set_xticks(solo_x)
    ax.set_xticklabels(solo_labels)
    ax.set_ylim(0, 60)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_title('(a) Others is NOT constant — grows with load', fontweight='bold', loc='left', fontsize=9)

    # ── (b) Concurrent prediction error ──
    ax2 = axes[1]
    conc_labels = ['A1+B1', 'A1+B2', 'A2+B1', 'A2+B2']
    predicted = [
        WALL[1]+WALL[3]-WALL[0],  # A1+B1
        WALL[1]+WALL[4]-WALL[0],  # A1+B2
        WALL[2]+WALL[3]-WALL[0],  # A2+B1
        WALL[2]+WALL[4]-WALL[0],  # A2+B2
    ]
    measured = WALL[5:]
    errors = [(p-m)/m*100 for p, m in zip(predicted, measured)]

    x = np.arange(len(conc_labels))
    w = 0.32
    bars_p = ax2.bar(x - w/2, predicted, w, label='Predicted (Sum−Idle)', color=C['pred'], alpha=0.85)
    bars_m = ax2.bar(x + w/2, measured,  w, label='Measured (Wall)', color=C['meas'], alpha=0.85)

    for i in range(len(conc_labels)):
        err = errors[i]
        color = '#E63946' if abs(err) > 5 else '#2A9D8F'
        ax2.text(i, max(predicted[i], measured[i])+4,
                 f'{err:+.1f}%', ha='center', fontsize=9, fontweight='bold', color=color)

    ax2.set_ylabel('Wall Power (W)')
    ax2.set_xticks(x)
    ax2.set_xticklabels(conc_labels)
    ax2.set_ylim(0, 260)
    ax2.legend(loc='upper left')
    ax2.grid(axis='y', alpha=0.3, linestyle='--')
    ax2.set_title('(b) Superposition Prediction Error', fontweight='bold', loc='left', fontsize=9)

    # Highlight B2 combinations
    for i in [1, 3]:
        ax2.get_xticklabels()[i].set_color(C['meas'])
        ax2.get_xticklabels()[i].set_fontweight('bold')

    # Annotation box
    props = dict(boxstyle='round,pad=0.4', facecolor='#FFF3CD', edgecolor='#E9C46A', alpha=0.95)
    ax2.text(0.97, 0.55, 'B2 combinations:\n−11~13% over-prediction\n-> CPU freq throttling\n   suspected',
             transform=ax2.transAxes, fontsize=8, va='top', ha='right', bbox=props)

    fig.tight_layout(rect=[0, 0.03, 1, 0.93])
    _add_watermark(fig)
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── PAGE 3 : Phase 2.0 — DIMM & fio ────────────────────────────────
def page3_phase2(pdf):
    fig = plt.figure(figsize=(11, 8.5))
    gs = fig.add_gridspec(2, 2, hspace=0.5, wspace=0.35,
                          left=0.07, right=0.95, top=0.88, bottom=0.06)
    fig.suptitle('Phase 2.0 — Decomposing "Others" via Physical Measurement',
                 fontweight='bold', y=0.96)

    # ── (a) DIMM 32GB consistency ──
    ax1 = fig.add_subplot(gs[0, 0])
    runs = [1, 2, 3]
    ax1.errorbar(runs, DIMM_RUNS, yerr=0.1, fmt='o-', color=C['wall'], linewidth=2,
                 markersize=8, capsize=5, label='Wall (RPICT)')
    ax1.errorbar(runs, DIMM_CPU, yerr=0.04, fmt='s-', color=C['cpu'], linewidth=1.5,
                 markersize=6, capsize=4, label='CPU (RAPL)')
    ax1.errorbar(runs, DIMM_GPU, yerr=0.06, fmt='^-', color=C['gpu'], linewidth=1.5,
                 markersize=6, capsize=4, label='GPU')

    ax1.set_xlabel('Run #')
    ax1.set_ylabel('Power (W)')
    ax1.set_xticks(runs)
    ax1.set_ylim(0, 50)
    ax1.legend(loc='center right', fontsize=7)
    ax1.grid(axis='y', alpha=0.3, linestyle='--')
    ax1.set_title('(a) DIMM 32GB — 3-Run Consistency', fontweight='bold', loc='left', fontsize=9)

    props = dict(boxstyle='round,pad=0.3', facecolor='#D4EDDA', edgecolor='#28A745', alpha=0.9)
    ax1.text(0.03, 0.97, f'Wall = {np.mean(DIMM_RUNS):.1f} ± 0.1W\nExcellent repeatability',
             transform=ax1.transAxes, fontsize=8, va='top', bbox=props)

    # ── (b) DIMM decomposition placeholder ──
    ax2 = fig.add_subplot(gs[0, 1])
    cats = ['32GB\n(2 DIMMs)', '16GB\n(1 DIMM)', 'Delta\n(Memory)']
    vals = [43.4, None, None]  # 16GB pending

    ax2.bar([0], [43.4], 0.5, color=C['wall'], alpha=0.85, label='Measured')
    ax2.bar([1], [0], 0.5, color=C['wall'], alpha=0.3)
    ax2.bar([2], [0], 0.5, color=C['mem'], alpha=0.3)

    ax2.text(0, 43.4+1, '43.4W', ha='center', fontsize=9, fontweight='bold')
    ax2.text(1, 2, '[Pending]\n(DIMM removal)', ha='center', fontsize=8, color='#999')
    ax2.text(2, 2, '[Pending]\n= 32GB - 16GB\n(expected ~1-2W)', ha='center', fontsize=8, color='#999')

    ax2.set_ylabel('Wall Power (W)')
    ax2.set_xticks([0, 1, 2])
    ax2.set_xticklabels(cats)
    ax2.set_ylim(0, 55)
    ax2.grid(axis='y', alpha=0.3, linestyle='--')
    ax2.set_title('(b) DIMM Experiment — Memory Isolation', fontweight='bold', loc='left', fontsize=9)

    # ── (c) fio — Stacked delta ──
    ax3 = fig.add_subplot(gs[1, 0])
    fio_x = np.arange(1, 5)  # skip idle
    fio_lbl = ['Seq\nRead', 'Seq\nWrite', 'Rand\nRead', 'Rand\nWrite']
    dcpu = FIO_DCPU[1:]
    dio  = FIO_DIO[1:]
    d_wall_fio = [FIO_WALL[i] - FIO_WALL[0] for i in range(1,5)]

    ax3.bar(fio_x, dcpu, 0.5, label='dCPU (RAPL)', color=C['cpu'], edgecolor='white', linewidth=0.5)
    ax3.bar(fio_x, dio, 0.5, bottom=dcpu, label='IO Subsystem\n(dWall−dCPU)', color=C['io'],
            edgecolor='white', linewidth=0.5)

    for i, (dc, di, dw) in enumerate(zip(dcpu, dio, d_wall_fio)):
        ax3.text(i+1, dw+1.5, f'Δ{dw:.0f}W', ha='center', fontsize=8, fontweight='bold', color=C['wall'])

    # SSD datasheet reference line
    ax3.axhline(FIO_SSD_SPEC, color=C['meas'], linestyle=':', linewidth=1.2, alpha=0.7)
    ax3.text(4.4, FIO_SSD_SPEC+0.5, f'SSD spec\n{FIO_SSD_SPEC}W', fontsize=7, color=C['meas'])

    ax3.set_ylabel('Delta Power from Idle (W)')
    ax3.set_xticks(fio_x)
    ax3.set_xticklabels(fio_lbl)
    ax3.set_ylim(0, 55)
    ax3.legend(loc='upper left', fontsize=7)
    ax3.grid(axis='y', alpha=0.3, linestyle='--')
    ax3.set_title('(c) fio — Storage IO Energy Decomposition', fontweight='bold', loc='left', fontsize=9)

    # ── (d) IO Subsystem vs SSD spec ──
    ax4 = fig.add_subplot(gs[1, 1])
    io_measured = dio
    io_labels = fio_lbl
    ssd_spec = [FIO_SSD_SPEC]*4
    overhead = [m - FIO_SSD_SPEC for m in io_measured]

    bars_spec = ax4.bar(fio_x, ssd_spec, 0.5, label=f'SSD only (spec {FIO_SSD_SPEC}W)',
                        color=C['io'], alpha=0.4, edgecolor='white')
    bars_over = ax4.bar(fio_x, overhead, 0.5, bottom=ssd_spec,
                        label='PCIe + Chipset + DMA\n(IO path overhead)',
                        color=C['io'], alpha=0.85, edgecolor='white', linewidth=0.5)

    for i, m in enumerate(io_measured):
        ratio = m / FIO_SSD_SPEC
        ax4.text(i+1, m+0.8, f'{m:.1f}W\n({ratio:.1f}×)', ha='center', fontsize=8, fontweight='bold')

    ax4.set_ylabel('IO Subsystem Power (W)')
    ax4.set_xticks(fio_x)
    ax4.set_xticklabels(io_labels)
    ax4.set_ylim(0, 28)
    ax4.legend(loc='upper left', fontsize=7)
    ax4.grid(axis='y', alpha=0.3, linestyle='--')
    ax4.set_title('(d) IO Subsystem >> SSD Datasheet', fontweight='bold', loc='left', fontsize=9)

    props = dict(boxstyle='round,pad=0.3', facecolor='#FFF3CD', edgecolor='#E9C46A', alpha=0.95)
    ax4.text(0.97, 0.97, '"Storage energy"\nincludes entire\nIO path, not just SSD',
             transform=ax4.transAxes, fontsize=8, va='top', ha='right', bbox=props)

    _add_watermark(fig)
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── PAGE 4 : Model Evolution + Key Findings ─────────────────────────
def page4_model_summary(pdf):
    fig = plt.figure(figsize=(11, 8.5))
    gs = fig.add_gridspec(2, 2, hspace=0.55, wspace=0.35,
                          left=0.07, right=0.95, top=0.88, bottom=0.06)
    fig.suptitle('Integrated Summary — From 3-Component to 5-Component Model',
                 fontweight='bold', y=0.96)

    # ── (a) Model evolution diagram ──
    ax1 = fig.add_subplot(gs[0, :])
    ax1.axis('off')

    # 3-component model
    y_top = 0.85
    ax1.text(0.18, y_top, '3-Component Model (Phase 1.6)', fontsize=11,
             fontweight='bold', ha='center', transform=ax1.transAxes)
    boxes_3 = [
        (0.02, 0.45, 0.10, 0.25, 'CPU\n(RAPL)', C['cpu']),
        (0.13, 0.45, 0.10, 0.25, 'GPU\n(nvidia)', C['gpu']),
        (0.02, 0.10, 0.21, 0.30, 'Others\n62% of Idle\n35-44% under load\n???', C['other']),
    ]
    for (x, y, w, h, txt, col) in boxes_3:
        rect = plt.Rectangle((x, y), w, h, transform=ax1.transAxes,
                              facecolor=col, alpha=0.7, edgecolor='#333', linewidth=1.2, clip_on=False)
        ax1.add_patch(rect)
        ax1.text(x+w/2, y+h/2, txt, transform=ax1.transAxes, ha='center', va='center',
                 fontsize=8, fontweight='bold')

    # Arrow
    ax1.annotate('', xy=(0.42, 0.45), xytext=(0.30, 0.45),
                 xycoords='axes fraction', textcoords='axes fraction',
                 arrowprops=dict(arrowstyle='->', lw=3, color='#E63946'))
    ax1.text(0.36, 0.55, 'Phase 2.0\nDecompose', transform=ax1.transAxes,
             ha='center', fontsize=9, fontweight='bold', color='#E63946')

    # 5-component model
    ax1.text(0.70, y_top, '5-Component Model (Phase 2.0+)', fontsize=11,
             fontweight='bold', ha='center', transform=ax1.transAxes)
    boxes_5 = [
        (0.45, 0.55, 0.10, 0.20, 'CPU\n(RAPL)', C['cpu']),
        (0.56, 0.55, 0.10, 0.20, 'GPU\n(nvidia)', C['gpu']),
        (0.67, 0.55, 0.10, 0.20, 'Memory\n(DIMM\nexperiment)', C['mem']),
        (0.78, 0.55, 0.10, 0.20, 'Storage\n(fio\nexperiment)', C['io']),
        (0.55, 0.10, 0.24, 0.35, 'Fixed Others\n(Chipset+VRM+Fan)\nSmaller & bounded', C['other']),
    ]
    for (x, y, w, h, txt, col) in boxes_5:
        rect = plt.Rectangle((x, y), w, h, transform=ax1.transAxes,
                              facecolor=col, alpha=0.7, edgecolor='#333', linewidth=1.2, clip_on=False)
        ax1.add_patch(rect)
        ax1.text(x+w/2, y+h/2, txt, transform=ax1.transAxes, ha='center', va='center',
                 fontsize=7.5, fontweight='bold')

    ax1.set_title('(a) Attribution Model Evolution', fontweight='bold', loc='left', fontsize=10)

    # ── (b) Billing inequality demo ──
    ax2 = fig.add_subplot(gs[1, 0])

    vms = ['yolo.slice\n(A2: YOLO Med)', 'nodejs.slice\n(B2: Node Heavy)']
    resource_share = [50, 50]
    # For A2+B2: Wall=201.1, CPU=71.0, GPU=60.1
    # yolo energy: CPU~32.3 + GPU~60.1 = ~92.4  ->  92.4/(92.4+57.1) = 61.8%
    # nodejs energy: CPU~57.1 + GPU~0 = ~57.1    ->  57.1/149.5 = 38.2%
    # But also accounting for Others proportionally:
    # Simple: yolo measured power contribution ≈ A2_solo / (A2_solo + B2_solo) * concurrent
    # A2=147.3, B2=116.8 -> yolo_share = 147.3/(147.3+116.8) = 55.8%, node = 44.2%
    # More precise with component attribution:
    energy_share = [61.8, 38.2]

    x = np.arange(len(vms))
    w = 0.30
    bars1 = ax2.bar(x - w/2, resource_share, w, label='Resource Billing\n(CPU cores)', color=C['node'], alpha=0.7)
    bars2 = ax2.bar(x + w/2, energy_share, w, label='Energy Billing\n(measured)', color=C['meas'], alpha=0.7)

    for bar, val in zip(list(bars1) + list(bars2), resource_share + energy_share):
        ax2.text(bar.get_x()+bar.get_width()/2, val+1.5, f'{val:.0f}%',
                 ha='center', fontsize=10, fontweight='bold')

    ax2.set_ylabel('Cost Share (%)')
    ax2.set_xticks(x)
    ax2.set_xticklabels(vms)
    ax2.set_ylim(0, 80)
    ax2.legend(loc='upper right', fontsize=8)
    ax2.grid(axis='y', alpha=0.3, linestyle='--')
    ax2.set_title('(b) Resource Billing != Energy Billing\n     (A2+B2 concurrent scenario)',
                  fontweight='bold', loc='left', fontsize=9)

    # Annotation
    ax2.annotate('GPU-heavy VM\nunder-billed\nby resource model',
                 xy=(0+w/2, 61.8), xytext=(0.6, 70),
                 fontsize=8, color=C['meas'], fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=C['meas'], lw=1.5))

    # ── (c) fio summary table ──
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.axis('off')

    fio_table_data = [
        ['Idle',       '43.4',  '—',     '—',     '—',    '—'],
        ['Seq Read',   '88.6',  '+45.1', '+25.7', '19.4', '16.4 GB/s'],
        ['Seq Write',  '59.2',  '+15.8', '+7.8',  '8.0',  '2.2 GB/s'],
        ['Rand Read',  '90.8',  '+47.3', '+26.8', '20.5', '313K IOPS'],
        ['Rand Write', '89.3',  '+45.9', '+26.2', '19.7', '291K IOPS'],
    ]
    col_labels = ['Phase', 'Wall\n(W)', 'dWall\n(W)', 'dCPU\n(W)', 'IO Sub.\n(W)', 'Throughput']

    table = ax3.table(cellText=fio_table_data, colLabels=col_labels,
                      loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1.0, 1.6)

    for j in range(len(col_labels)):
        cell = table[0, j]
        cell.set_facecolor('#1D3557')
        cell.set_text_props(color='white', fontweight='bold')
    # Highlight IO subsystem column
    for i in range(1, 6):
        table[i, 4].set_facecolor('#FDEBD0')
        table[i, 4].set_text_props(fontweight='bold')

    ax3.set_title('(c) fio Storage Experiment Results',
                  fontweight='bold', loc='left', fontsize=9, pad=20)

    _add_watermark(fig)
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── PAGE 5 : Key Findings Summary ───────────────────────────────────
def page5_findings(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.axis('off')

    fig.suptitle('Key Findings & Next Steps', fontweight='bold', fontsize=14, y=0.96)

    findings = [
        ("Finding 1", "Others != Constant",
         "Others energy ranges from 22.7W (idle) to 69.9W (A2+B2).\n"
         "It contains both fixed (chipset, VRM, fan) and dynamic\n"
         "(DRAM bandwidth, PCIe traffic, VRM loss) components."),
        ("Finding 2", "IO Subsystem >> SSD Spec",
         "Measured IO path energy: 8-20W vs Samsung 980 spec: 3.5W.\n"
         "The full IO subsystem (PCIe controller, chipset, DMA) consumes\n"
         "2.3-5.9× more than the SSD alone."),
        ("Finding 3", "B2 Nonlinear Throttling",
         "B2-inclusive concurrent scenarios show 11-13% over-prediction.\n"
         "Suspected CPU frequency throttling under high concurrent load.\n"
         "CPU frequency logging added (Phase 2.1b) to validate."),
        ("Finding 4", "Resource != Energy Billing",
         "Same 2-core + 4GB allocation -> 2.7x power difference\n"
         "(YOLO 147W vs Node.js 42W solo). GPU-heavy VMs are\n"
         "systematically under-billed in resource-based models."),
    ]

    y_start = 0.85
    for i, (num, title, detail) in enumerate(findings):
        y = y_start - i * 0.17
        colors = [C['io'], C['meas'], C['conc'], C['wall']]

        # Number badge
        circle = plt.Circle((0.04, y), 0.022, transform=ax.transAxes,
                             color=colors[i], clip_on=False)
        ax.add_patch(circle)
        ax.text(0.04, y, str(i+1), transform=ax.transAxes, ha='center', va='center',
                fontsize=11, fontweight='bold', color='white')

        # Title and detail
        ax.text(0.08, y+0.02, f'{title}', transform=ax.transAxes,
                fontsize=11, fontweight='bold', color=colors[i])
        ax.text(0.08, y-0.03, detail, transform=ax.transAxes,
                fontsize=8.5, color='#333', linespacing=1.3)

    # Next steps box
    y_box = 0.04
    rect = plt.Rectangle((0.03, y_box), 0.94, 0.14, transform=ax.transAxes,
                          facecolor='#E8F4FD', edgecolor='#457B9D', linewidth=1.5, clip_on=False)
    ax.add_patch(rect)
    ax.text(0.05, y_box+0.115, 'Next Steps', transform=ax.transAxes,
            fontsize=10, fontweight='bold', color='#457B9D')
    ax.text(0.05, y_box+0.015, (
        '1. DIMM 16GB measurement (in progress) -> derive Memory_per_DIMM parameter\n'
        '2. Re-insert DIMM + install 2nd GPU -> reboot -> 32GB verification run\n'
        '3. Phase 2.2: Full validation (Solo 4 + Concurrent 4) with cpufreq + io.stat logging\n'
        '4. Build 5-component attribution model:  Wall = CPU + GPU + Memory + Storage + Fixed_Others'
    ), transform=ax.transAxes, fontsize=8.5, color='#333', linespacing=1.4)

    _add_watermark(fig)
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── MAIN ─────────────────────────────────────────────────────────────
def main():
    base = Path(__file__).parent.parent.parent
    out_dir = base / "reports" / "integrated"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "integrated_results_phase1.6_2.0.pdf"

    with PdfPages(pdf_path) as pdf:
        print("Page 1: Phase 1.6 Power Breakdown ...")
        page1_power_breakdown(pdf)
        print("Page 2: Others Analysis ...")
        page2_others_analysis(pdf)
        print("Page 3: Phase 2.0 DIMM & fio ...")
        page3_phase2(pdf)
        print("Page 4: Model Evolution & Summary ...")
        page4_model_summary(pdf)
        print("Page 5: Key Findings ...")
        page5_findings(pdf)

    print(f"\nDone! -> {pdf_path}")


if __name__ == '__main__':
    main()
