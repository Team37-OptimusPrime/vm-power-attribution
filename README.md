**English** | [한국어](README.ko.md)

# An Energy Cost Model for AI Workloads under Shared Resource Environments

Source code, experiment data, and results for the research-track capstone
project **"An Energy Cost Model for AI Workloads under Shared Resource
Environments"** (W. Shin, J. Kim, S. Kang, K. Cho, H. Bahn — Ewha University).

> **Team 37 — OptimusPrime** · Research track (연구 트랙)

---

## 1. Project Overview

Modern cloud/edge platforms charge tenants by **allocated resources** (vCPU,
memory, GPU type), not by the **energy actually consumed**. As AI workloads come
to dominate operational cost, this allocation-based pricing becomes inaccurate
and unfair. The core difficulty is that, while *total* system energy can be
measured at the wall socket, the energy of an *individual* workload cannot be
measured directly once CPU/GPU/memory/storage are shared among co-located
workloads.

This project formulates and empirically validates an **energy cost model** that
attributes per-workload energy from system-level measurements **without any
extra instrumentation**, using only metrics already available on commodity
platforms (Intel RAPL, NVIDIA NVML, cgroup v2 statistics, and a wall-socket
power meter).

### Key idea — resource-aware decomposition

Total measured system energy is split into an idle **baseline** plus
resource-specific components, each attributed by the principle that best matches
its physical behavior:

| Component | Measurement source | Attribution principle |
|-----------|-------------------|-----------------------|
| **CPU**     | Intel RAPL package energy | utilization (cgroup CPU%) after idle subtraction |
| **GPU**     | NVIDIA NVML / `nvidia-smi` | hybrid: activity by utilization + allocation baseline |
| **Memory**  | LPDDR/DDR datasheet + DIMM test | allocation (capacity), static-power dominated |
| **Storage** | `fio` calibration | I/O volume (read/write bytes) |
| **Others**  | residual | platform baseline (PSU, fans, VRM, chipset) |

The model preserves energy conservation: `E_sys = E_baseline + Σ E_workload_i`.

### Main empirical findings

- Under **identical resource allocation** (2 vCPU + 4 GB each), measured
  per-workload energy differs by **4.7×–11×** between AI and Node.js workloads,
  and up to **2.4×** even between two AI workloads — directly contradicting
  allocation-based pricing.
- AI workloads are **GPU-dominant** (GPU = 74–93 % of workload-induced power);
  Node.js is **CPU-dominant** (CPU ≈ 94 %).
- The attribution model reproduces isolated-execution power from concurrent
  runs within **~5 % error** (avg 3.7 % in asymmetric AI+AI pairs).

---

## 2. Repository Structure

```
vm-power-attribution/
├── README.md                  # this file
├── CHANGELOG.md               # experiment & version history
├── requirements.txt           # Python dependencies (analysis + measurement)
│
├── scripts/
│   ├── measurement/           # data collection (run on the test rig)
│   │   ├── host_logger.py      # Intel RAPL (CPU) + nvidia-smi (GPU) host metrics
│   │   ├── cgroup_logger.py    # per-workload cgroup v2 CPU / memory / I/O stats
│   │   └── rpict_logger.py     # RPICT4V3 wall-socket AC power (runs on Raspberry Pi)
│   ├── workloads/             # workloads + experiment orchestration
│   │   ├── gpt2_inference.py   # GPT-2 inference (AI)
│   │   ├── resnet18_inference.py # ResNet-18 inference (AI)
│   │   ├── pytorch_gemm.py     # PyTorch GEMM (supplementary AI)
│   │   ├── ffmpeg_encode.py    # ffmpeg transcode (supplementary)
│   │   ├── server*.js          # Node.js web service (traditional) — light/heavy
│   │   ├── setup_cgroups.sh    # create yolo.slice / nodejs.slice cgroups
│   │   └── run_*.sh            # experiment runners (see §6)
│   └── analysis/              # data extraction, modeling, figures (run anywhere)
│
├── analysis/                  # standalone verification / cross-run comparison
│
├── legacy/                    # exploratory pre-paper scripts (data not shipped; see legacy/README.md)
│
├── dashboard/                 # interactive demo (Streamlit) of the model
│   ├── app.py                  # dashboard UI
│   ├── model.py                # reference implementation of the energy model
│   └── data_loader.py
│
├── data/raw/                  # raw experiment measurements (see §5)
│   ├── alienware/             #   host + cgroup CSVs, per-GPU slice logs, config.txt
│   └── rpict/                 #   RPICT4V3 wall-power CSVs
│
├── reports/                   # derived results: TSV summaries, figures, PDFs
│   ├── phase2/                #   component / DIMM / fio calibration results
│   ├── phase3/                #   final multi-workload results (Fig. 3–8 source)
│   ├── phase3_run2/
│   └── integrated/            #   integrated results PDF
│
└── docs/                      # detailed documentation
    ├── setup.md               # full hardware + software setup guide (test rig)
    ├── hardware_power_analysis.md
    ├── troubleshooting.md
    ├── references.md
    └── experiments/           # per-phase experiment design notes
```

---

## 3. Hardware and Measurement Setup

The measurement experiments require the physical test rig described below.
**Analysis and the demo do not** — they run on any machine from the committed
data (see §4, §7).

| Item | Specification |
|------|---------------|
| Host | Alienware Aurora R12 |
| CPU  | Intel Core i7-11700KF (8C/16T, 125 W TDP) |
| GPU  | NVIDIA GeForce RTX 3060 (170 W TDP), dual-GPU |
| RAM  | 32 GB DDR4-3467 |
| Storage | Samsung SSD 980 500 GB NVMe |
| Power meter | RPICT4V3 + SCT-006 CT sensor + AC/AC adapter, on a Raspberry Pi 4 (serial `/dev/ttyAMA0`) |

Measurement sources: **CPU** = Intel RAPL (`/sys/class/powercap/intel-rapl`);
**GPU** = NVIDIA NVML via `nvidia-smi`; **wall power** = RPICT4V3 AC clamp;
**per-workload** = cgroup v2 (`/sys/fs/cgroup`).

Full rig build (OS, KVM/QEMU, NVIDIA driver/CUDA, RAPL permissions, RPICT wiring,
NTP/PTP time sync) is documented in **[`docs/setup.md`](docs/setup.md)**.

---

## 4. Installation

### 4.1 Requirements

- Python **3.10+** (developed on 3.14)
- For analysis & demo only: a working Python is sufficient.
- For measurement: Ubuntu 22.04 host with KVM/QEMU, NVIDIA driver + CUDA, and
  RAPL access (see `docs/setup.md`).

### 4.2 Set up the environment

```bash
git clone https://github.com/Team37-OptimusPrime/vm-power-attribution.git
cd vm-power-attribution

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` installs: `numpy`, `pandas`, `matplotlib`, `seaborn`,
`scikit-learn`, `scipy`, `psutil`, `pynvml`, `pyserial`, `libvirt-python`,
`PyYAML`, `tabulate`. (`libvirt-python` is only needed on the measurement host;
analysis/figures work without it.)

### 4.3 Demo dependencies (optional)

```bash
pip install -r dashboard/requirements.txt   # streamlit, plotly, pandas, numpy, watchdog
```

> **Build note:** this is a Python + shell + Node.js project; there is no
> compilation step. "Building" means creating the virtual environment and
> installing dependencies as above. The Node.js workload (`server*.js`) runs on
> any Node.js ≥ 18 runtime.

---

## 5. Data Description

All measurements needed to reproduce the paper are committed under `data/raw/`
(~6 MB) with derived results under `reports/` (~7 MB).

**`data/raw/alienware/<run>/`** — one directory per experiment run, containing:
- `*_host.csv` — host metrics: RAPL CPU package power, GPU power (`nvidia-smi`), timestamps
- `*_cgroup.csv` — per-workload cgroup v2 CPU%, memory, I/O bytes
- `*_gpu*.slice.log` — per-GPU power logs per workload slice
- `baseline_host.csv` / `baseline_cgroup.csv` — idle baseline measurement
- `config.txt` — run description (workloads, allocations, durations)

**`data/raw/rpict/`** — RPICT4V3 wall-socket AC power CSVs (`power1_w`, current,
voltage, timestamp), one per experiment.

Experiment runs included:

| Group | Directories | Purpose (paper) |
|-------|-------------|-----------------|
| Component | `phase2.0_component/` | decompose system power into CPU/GPU/mem/other |
| Memory | `phase2.0_dimm/` | DIMM power test (memory ≈ 0.2 W/GB validation) |
| Storage | `phase2.0_fio/`, `phase2.1_fio/` | `fio` calibration → storage coeff **2.5 J/GB** |
| Final | `phase3_integrated_*`, `phase3_fixed*`, `phase3_nopt_run4–6` | YOLO/GPT2/ResNet/Node.js isolated + concurrent (Fig. 3–7) |
| Validation | `phase3_asym_run1/` | AI+AI asymmetric pairs (Fig. 8 validation) |

> Exploratory pre-paper runs (phase1, phase1.5, phase1.6, phase2.2) are kept in
> the authors' working tree but excluded from the deliverable (see `.gitignore`)
> to keep the repository focused on data that backs the paper.

**Workloads (open datasets/models):** YOLO (Ultralytics), GPT-2 (Hugging Face /
OpenAI), ResNet-18 (torchvision), Node.js web service. Models are downloaded on
first run by the workload scripts; no proprietary data is used.

---

## 6. Running the Experiments (on the test rig)

Measurement requires the hardware in §3. The orchestration script runs the
workloads on the Alienware host while logging host/cgroup metrics locally and
RPICT power remotely on the Raspberry Pi over SSH.

```bash
# 1. one-time: create cgroups for the workloads
sudo ./scripts/workloads/setup_cgroups.sh

# 2. run the integrated phase-3 experiment (host + remote RPICT)
sudo -E ./scripts/workloads/run_integrated_experiment.sh \
      --experiment phase3 --rpict-host <pi-ip> --rpict-user <pi-user>

#    variants:
#    --experiment phase3_nopt   # without PyTorch GEMM
#    --experiment asymmetric    # AI+AI asymmetric pairs
#    --skip-rpict               # host-only (no wall-power logging)
```

Individual loggers can also be run directly:

```bash
sudo python3 scripts/measurement/host_logger.py -o host.csv -d 60      # RAPL+GPU, 60 s
python3 scripts/measurement/cgroup_logger.py -c yolo.slice nodejs.slice -o cg.csv -d 60
python3 scripts/measurement/rpict_logger.py  -o rpict.csv               # on the Raspberry Pi
```

Calibration runs: `run_component_isolation.sh`, `run_dimm_experiment.sh`,
`run_fio_experiment.sh`.

---

## 7. Reproducing the Paper (analysis only — no hardware needed)

From a clean clone with the venv activated, the committed data regenerates the
results. Scripts resolve the repository root from their own location, so they
work regardless of where the repo is cloned.

```bash
# Extract per-run summaries (system power + workload usage) → reports/phase3/*.tsv
python3 scripts/analysis/extract_phase3_data.py --run run3
python3 scripts/analysis/extract_phase3_data.py --run run4 --no-pt

# Storage calibration  → storage energy coefficient (2.5 J/GB)
python3 scripts/analysis/fio_v2_analysis.py

# Component decomposition (CPU/GPU/memory/other baseline)
python3 scripts/analysis/component_isolation_analysis.py

# Time-series power profile (paper Fig. 3)
python3 scripts/analysis/plot_timeseries_power.py --run run3

# AI+AI asymmetric pairs — model attribution & validation (paper Fig. 8)
python3 scripts/analysis/extract_phase3_asym_data.py

# Integrated results PDF (combined figures) → reports/integrated/
python3 scripts/analysis/integrated_results_pdf.py
```

### Paper figure → source mapping

| Paper | Result | Script / data |
|-------|--------|---------------|
| Fig. 3 | Time-series power (idle/single/concurrent) | `plot_timeseries_power.py` · `data/raw/.../phase3_*`, `rpict/` |
| Fig. 4 | System-level power per workload | `extract_phase3_data.py` → `reports/phase3/system_power_*.tsv` |
| Fig. 5 | Workload-induced power (baseline subtracted) | `extract_phase3_data.py` · `dashboard/model.py` |
| Fig. 6 | Concurrent system-level power | `extract_phase3_data.py` → `reports/phase3/*` |
| Fig. 7 | Per-workload attribution (concurrent) | `extract_phase3_data.py` · `dashboard/model.py` |
| Fig. 8 | Validation: model vs measured | `extract_phase3_asym_data.py`, `analysis/compare_phase3_runs.py` |
| §IV-A | Storage coeff 2.5 J/GB | `fio_v2_analysis.py` · `phase2.0_fio`, `phase2.1_fio` |
| §IV-A | Memory 0.2 W/GB | LPDDR4 datasheet; `dimm_analysis.py` (`phase2.0_dimm`, partial) |

> The reference implementation of the attribution model (CPU/GPU/memory/storage
> decomposition + conservation) is `dashboard/model.py`, with constants
> `MEMORY_POWER_PER_GB = 0.2 W/GB` and `STORAGE_BETA = 2.5 J/GB` matching §IV-A.

---

## 8. Demo (Interactive Dashboard)

A Streamlit dashboard visualizes per-workload CPU/GPU/memory/storage attribution
for any committed run, applying the model in `dashboard/model.py`.

```bash
pip install -r dashboard/requirements.txt
cd dashboard
streamlit run app.py          # opens http://localhost:8501
```

---

## 9. Testing / Verifying

```bash
# verify attribution consistency and energy conservation for phase-3 runs
python3 analysis/verify_phase3.py
python3 analysis/compare_phase3_runs.py     # cross-run consistency of repeats
```

These re-derive system/workload power from raw data and check that attributed
energy reconstructs the measured system energy (conservation), which is how the
paper's ~5 % accuracy bound is established.

---

## 10. Open Source Used

- **Analysis/runtime:** NumPy, pandas, Matplotlib, seaborn, SciPy, scikit-learn,
  psutil, [pynvml](https://github.com/gpuopenanalytics/pynvml) (NVIDIA NVML),
  pySerial, libvirt-python, PyYAML, tabulate
- **Demo:** Streamlit, Plotly
- **Workloads:** [Ultralytics YOLO](https://github.com/ultralytics/yolov5),
  GPT-2 (OpenAI / Hugging Face Transformers), ResNet-18 (torchvision / PyTorch),
  [Node.js](https://nodejs.org), [fio](https://fio.readthedocs.io)
- **Measurement substrate:** Intel RAPL (Linux `powercap`),
  [NVIDIA NVML / nvidia-smi](https://developer.nvidia.com/system-management-interface),
  Linux cgroup v2, RPICT4V3 firmware, KVM/QEMU + libvirt

---

## 11. Documentation

| Document | Contents |
|----------|----------|
| [`docs/setup.md`](docs/setup.md) | Full hardware + software setup of the test rig |
| [`docs/hardware_power_analysis.md`](docs/hardware_power_analysis.md) | Power-measurement analysis notes |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | Common issues & fixes |
| [`docs/experiments/`](docs/experiments/) | Per-phase experiment design |
| [`docs/references.md`](docs/references.md) | Related work & references |
| [`CHANGELOG.md`](CHANGELOG.md) | Experiment log & change history |

---

## 12. Authors

Woorim Shin, Jiyoon Kim, Siyeon Kang, Kyungwoon Cho, Hyokyung Bahn
— Department of Computer Science and Engineering, Ewha Womans University.
