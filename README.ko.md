[English](README.md) | **한국어**

# 공유 자원 환경에서의 AI 워크로드 에너지 비용 모델

연구 트랙 졸업과제 결과물 — 논문 **"An Energy Cost Model for AI Workloads under
Shared Resource Environments"** (신우림, 김지윤, 강시연, 조경운, 반효경 · 이화여자대학교)
의 소스코드 · 실험 데이터 · 결과물

> **37팀 — OptimusPrime** · 연구 트랙

---

## 1. 프로젝트 개요

- 현행 클라우드/엣지 과금은 **할당 자원**(vCPU·메모리·GPU) 기준이며, 실제 **소비
  전력**을 반영하지 못함
- AI 워크로드가 운영비의 큰 비중을 차지하면서 할당 기반 과금은 점점 부정확·불공정해짐
- 근본 난점: 전체 시스템 전력은 벽면 콘센트에서 정확히 측정 가능하나, 자원이 공유되면
  **개별 워크로드의 전력은 직접 분리·측정할 수 없음**
- 제안: **추가 계측 장치 없이**, 상용 플랫폼에 이미 존재하는 지표(Intel RAPL, NVIDIA
  NVML, cgroup v2 통계, 벽면 전력계)만으로 워크로드별 에너지를 귀속하는 **에너지 비용
  모델**

### 핵심 아이디어 — 자원 특성별 분해

- 측정된 전체 시스템 에너지를 idle **기준선(baseline)** + 자원별 성분으로 나누고,
  각 성분은 물리적 거동에 가장 잘 맞는 원리로 귀속

| 성분 | 측정원 | 귀속 원리 |
|------|--------|-----------|
| **CPU**     | Intel RAPL 패키지 에너지 | idle 차감 후 이용률(cgroup CPU%) 비례 |
| **GPU**     | NVIDIA NVML / `nvidia-smi` | 하이브리드: 활동분(이용률) + 할당분(기준선) |
| **메모리**  | DDR 데이터시트 + DIMM 실험 | 할당 용량 기준(정적 전력 지배적) |
| **스토리지**| `fio` 캘리브레이션 | I/O 볼륨(read/write 바이트) 기준 |
| **기타**    | 잔차 | 플랫폼 기준선(PSU·팬·VRM·칩셋) |

- 에너지 보존 성립: `E_sys = E_baseline + Σ E_workload_i`

### 주요 실험 결과

- **동일 자원 할당**(워크로드당 2 vCPU + 4GB)에도 측정 에너지가 AI와 Node.js 사이
  **4.7~11배**, AI끼리도 최대 **2.4배** 차이 → 할당 기반 과금과 정면 배치
- AI 워크로드는 **GPU 지배적**(워크로드 유발 전력의 74~93%), Node.js는 **CPU 지배적**
  (약 94%)
- 동시 실행 데이터로부터 단독 실행 전력을 **약 5% 오차**(비대칭 AI+AI 평균 3.7%) 내로
  재현

---

## 2. 저장소 구조

```
vm-power-attribution/
├── README.md / README.ko.md   # 영문 / 국문 문서
├── CHANGELOG.md               # 실험·버전 이력
├── requirements.txt           # Python 의존성 (분석 + 측정)
│
├── scripts/
│   ├── measurement/           # 데이터 수집 (측정 장비에서 실행)
│   │   ├── host_logger.py      # Intel RAPL(CPU) + nvidia-smi(GPU) 호스트 지표
│   │   ├── cgroup_logger.py    # 워크로드별 cgroup v2 CPU/메모리/I/O 통계
│   │   └── rpict_logger.py     # RPICT4V3 벽면 AC 전력 (라즈베리파이에서 실행)
│   ├── workloads/             # 워크로드 + 실험 오케스트레이션
│   │   ├── gpt2_inference.py   # GPT-2 추론 (AI)
│   │   ├── resnet18_inference.py # ResNet-18 추론 (AI)
│   │   ├── pytorch_gemm.py     # PyTorch GEMM (보조 AI)
│   │   ├── ffmpeg_encode.py    # ffmpeg 트랜스코딩 (보조)
│   │   ├── server*.js          # Node.js 웹 서비스 (전통형) — light/heavy
│   │   ├── setup_cgroups.sh    # yolo.slice / nodejs.slice cgroup 생성
│   │   └── run_*.sh            # 실험 실행 스크립트 (§6 참고)
│   └── analysis/              # 데이터 추출·모델링·그림 생성 (어디서든 실행 가능)
│
├── analysis/                  # 독립 검증 / 런 간 비교
│
├── legacy/                    # 논문 이전 탐색용 스크립트 (데이터 미포함, legacy/README.md 참고)
│
├── dashboard/                 # 인터랙티브 데모 (Streamlit)
│   ├── app.py                  # 대시보드 UI
│   ├── model.py                # 에너지 모델 레퍼런스 구현
│   └── data_loader.py
│
├── data/raw/                  # 원시 실험 측정값 (§5)
│   ├── alienware/             #   호스트 + cgroup CSV, GPU slice 로그, config.txt
│   └── rpict/                 #   RPICT4V3 벽면 전력 CSV
│
├── reports/                   # 가공 결과: TSV 요약, 그림, PDF
│   ├── phase2/                #   component / DIMM / fio 캘리브레이션 결과
│   ├── phase3/                #   최종 다중 워크로드 결과 (그림 3~8 출처)
│   ├── phase3_run2/
│   └── integrated/            #   통합 결과 PDF
│
└── docs/                      # 상세 문서
    ├── setup.md               # 전체 하드웨어 + 소프트웨어 셋업 가이드
    ├── hardware_power_analysis.md
    ├── troubleshooting.md
    ├── references.md
    └── experiments/           # phase별 실험 설계 노트
```

---

## 3. 하드웨어 및 측정 구성

- 측정 실험은 아래 물리 장비가 필요함
- **분석과 데모는 장비 불필요** — 커밋된 데이터만으로 동작 (§4, §7)

| 항목 | 사양 |
|------|------|
| 호스트 | Alienware Aurora R12 |
| CPU  | Intel Core i7-11700KF (8C/16T, 125W TDP) |
| GPU  | NVIDIA GeForce RTX 3060 (170W TDP), 듀얼 GPU |
| 메모리 | 32GB DDR4-3467 |
| 스토리지 | Samsung SSD 980 500GB NVMe |
| 전력계 | RPICT4V3 + SCT-006 CT 센서 + AC/AC 어댑터, 라즈베리파이 4 (시리얼 `/dev/ttyAMA0`) |

- 측정원: **CPU** = Intel RAPL(`/sys/class/powercap/intel-rapl`) · **GPU** = NVIDIA
  NVML(`nvidia-smi`) · **벽면 전력** = RPICT4V3 AC 클램프 · **워크로드별** = cgroup
  v2(`/sys/fs/cgroup`)
- 장비 구축 전 과정(OS, KVM/QEMU, NVIDIA 드라이버/CUDA, RAPL 권한, RPICT 배선,
  NTP/PTP 시간 동기화)은 **[`docs/setup.md`](docs/setup.md)** 참고

---

## 4. 설치

### 4.1 요구 사항

- Python **3.10 이상** (3.14에서 개발)
- 분석·데모만 할 경우: Python 환경만 있으면 충분
- 측정까지 할 경우: KVM/QEMU, NVIDIA 드라이버 + CUDA, RAPL 접근 권한이 갖춰진
  Ubuntu 22.04 호스트 필요 (`docs/setup.md` 참고)

### 4.2 환경 구성

```bash
git clone https://github.com/Team37-OptimusPrime/vm-power-attribution.git
cd vm-power-attribution

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

- `requirements.txt` 설치 패키지: `numpy`, `pandas`, `matplotlib`, `seaborn`,
  `scikit-learn`, `scipy`, `psutil`, `pynvml`, `pyserial`, `libvirt-python`,
  `PyYAML`, `tabulate`
- `libvirt-python`은 측정 호스트에서만 필요 — 분석·그림 생성에는 불필요

### 4.3 데모 의존성 (선택)

```bash
pip install -r dashboard/requirements.txt   # streamlit, plotly, pandas, numpy, watchdog
```

> **빌드 참고:** Python + Shell + Node.js 프로젝트로 별도 컴파일 단계 없음.
> "빌드"는 위와 같이 가상환경 생성 + 의존성 설치를 의미함. Node.js 워크로드
> (`server*.js`)는 Node.js 18 이상에서 동작.

---

## 5. 데이터 설명

- 논문 재현에 필요한 측정값 전부를 `data/raw/`(약 6MB), 가공 결과를 `reports/`(약 7MB)에
  포함

**`data/raw/alienware/<run>/`** — 실험 런별 디렉토리, 구성:
- `*_host.csv` — 호스트 지표: RAPL CPU 전력, GPU 전력(`nvidia-smi`), 타임스탬프
- `*_cgroup.csv` — 워크로드별 cgroup v2 CPU%·메모리·I/O 바이트
- `*_gpu*.slice.log` — 워크로드 slice별 GPU 전력 로그
- `baseline_host.csv` / `baseline_cgroup.csv` — idle 기준선 측정
- `config.txt` — 런 설명 (워크로드·할당·지속시간)

**`data/raw/rpict/`** — RPICT4V3 벽면 AC 전력 CSV(`power1_w`, 전류, 전압, 타임스탬프),
실험별 1개

포함된 실험 런:

| 그룹 | 디렉토리 | 목적(논문) |
|------|----------|------------|
| Component | `phase2.0_component/` | 시스템 전력을 CPU/GPU/메모리/기타로 분해 |
| 메모리 | `phase2.0_dimm/` | DIMM 전력 실험 (메모리 ≈ 0.2 W/GB 검증) |
| 스토리지 | `phase2.0_fio/`, `phase2.1_fio/` | `fio` 캘리브레이션 → 스토리지 계수 **2.5 J/GB** |
| 최종 | `phase3_integrated_*`, `phase3_fixed*`, `phase3_nopt_run4–6` | YOLO/GPT2/ResNet/Node.js 단독+동시 (그림 3~7) |
| 검증 | `phase3_asym_run1/` | AI+AI 비대칭 조합 (그림 8 검증) |

> 논문 이전 탐색용 런(phase1, 1.5, 1.6, 2.2)은 로컬에만 보관하고 제출물에서는
> 제외(`.gitignore`) — 논문을 뒷받침하는 데이터로 저장소를 집중시키기 위함

- **워크로드(공개 모델/데이터셋):** YOLO(Ultralytics), GPT-2(Hugging Face/OpenAI),
  ResNet-18(torchvision), Node.js 웹 서비스
- 모델은 워크로드 스크립트가 최초 실행 시 자동 다운로드 — 독점 데이터 미사용

---

## 6. 실험 실행 (측정 장비에서)

- 측정에는 §3 하드웨어 필요
- 오케스트레이션 스크립트가 Alienware 호스트에서 워크로드를 실행하면서 호스트/cgroup
  지표는 로컬에, RPICT 전력은 SSH로 라즈베리파이에 원격 기록

```bash
# 1. 최초 1회: 워크로드용 cgroup 생성
sudo ./scripts/workloads/setup_cgroups.sh

# 2. 통합 phase-3 실험 실행 (호스트 + 원격 RPICT)
sudo -E ./scripts/workloads/run_integrated_experiment.sh \
      --experiment phase3 --rpict-host <pi-ip> --rpict-user <pi-user>

#    변형:
#    --experiment phase3_nopt   # PyTorch GEMM 제외
#    --experiment asymmetric    # AI+AI 비대칭 조합
#    --skip-rpict               # 호스트만 (벽면 전력 미기록)
```

개별 로거 직접 실행:

```bash
sudo python3 scripts/measurement/host_logger.py -o host.csv -d 60      # RAPL+GPU, 60초
python3 scripts/measurement/cgroup_logger.py -c yolo.slice nodejs.slice -o cg.csv -d 60
python3 scripts/measurement/rpict_logger.py  -o rpict.csv               # 라즈베리파이에서
```

캘리브레이션 실행: `run_component_isolation.sh`, `run_dimm_experiment.sh`,
`run_fio_experiment.sh`

---

## 7. 논문 재현 (분석만 — 하드웨어 불필요)

- 깨끗하게 clone한 뒤 가상환경을 활성화하면, 커밋된 데이터로 결과 재생성 가능
- 모든 스크립트가 자기 위치 기준으로 저장소 루트를 찾으므로 clone 위치와 무관하게 동작

```bash
# 런별 요약 추출 (시스템 전력 + 워크로드 사용량) → reports/phase3/*.tsv
python3 scripts/analysis/extract_phase3_data.py --run run3
python3 scripts/analysis/extract_phase3_data.py --run run4 --no-pt

# 스토리지 캘리브레이션 → 스토리지 에너지 계수 (2.5 J/GB)
python3 scripts/analysis/fio_v2_analysis.py

# 성분 분해 (CPU/GPU/메모리/기타 기준선)
python3 scripts/analysis/component_isolation_analysis.py

# 시계열 전력 프로파일 (논문 그림 3)
python3 scripts/analysis/plot_timeseries_power.py --run run3

# AI+AI 비대칭 조합 — 모델 귀속 및 검증 (논문 그림 8)
python3 scripts/analysis/extract_phase3_asym_data.py

# 통합 결과 PDF (종합 그림) → reports/integrated/
python3 scripts/analysis/integrated_results_pdf.py
```

### 논문 그림 → 출처 매핑

| 논문 | 결과 | 스크립트 / 데이터 |
|------|------|-------------------|
| 그림 3 | 시계열 전력 (idle/단독/동시) | `plot_timeseries_power.py` · `data/raw/.../phase3_*`, `rpict/` |
| 그림 4 | 워크로드별 시스템 전력 | `extract_phase3_data.py` → `reports/phase3/system_power_*.tsv` |
| 그림 5 | 워크로드 유발 전력 (기준선 차감) | `extract_phase3_data.py` · `dashboard/model.py` |
| 그림 6 | 동시 실행 시스템 전력 | `extract_phase3_data.py` → `reports/phase3/*` |
| 그림 7 | 워크로드별 귀속 (동시 실행) | `extract_phase3_data.py` · `dashboard/model.py` |
| 그림 8 | 검증: 모델 vs 실측 | `extract_phase3_asym_data.py`, `analysis/compare_phase3_runs.py` |
| §IV-A | 스토리지 계수 2.5 J/GB | `fio_v2_analysis.py` · `phase2.0_fio`, `phase2.1_fio` |
| §IV-A | 메모리 0.2 W/GB | LPDDR4 데이터시트; `dimm_analysis.py`(`phase2.0_dimm`, 부분) |

> 에너지 모델 레퍼런스 구현은 `dashboard/model.py` — 상수 `MEMORY_POWER_PER_GB =
> 0.2 W/GB`, `STORAGE_BETA = 2.5 J/GB`가 §IV-A와 일치

---

## 8. 데모 (인터랙티브 대시보드)

- Streamlit 대시보드로 임의의 커밋된 런에 대해 워크로드별 CPU/GPU/메모리/스토리지
  귀속을 시각화 (`dashboard/model.py` 모델 적용)

```bash
pip install -r dashboard/requirements.txt
cd dashboard
streamlit run app.py          # http://localhost:8501 열림
```

---

## 9. 테스트 / 검증

```bash
# phase-3 런의 귀속 일관성 및 에너지 보존 검증
python3 analysis/verify_phase3.py
python3 analysis/compare_phase3_runs.py     # 반복 런 간 일관성
```

- 원시 데이터에서 시스템/워크로드 전력을 재유도하고, 귀속된 에너지가 측정 시스템
  에너지를 복원하는지(보존) 확인 — 논문의 약 5% 정확도 근거가 이 방식으로 성립

---

## 10. 사용 오픈소스

- **분석/런타임:** NumPy, pandas, Matplotlib, seaborn, SciPy, scikit-learn,
  psutil, [pynvml](https://github.com/gpuopenanalytics/pynvml)(NVIDIA NVML),
  pySerial, libvirt-python, PyYAML, tabulate
- **데모:** Streamlit, Plotly
- **워크로드:** [Ultralytics YOLO](https://github.com/ultralytics/yolov5),
  GPT-2(OpenAI / Hugging Face Transformers), ResNet-18(torchvision / PyTorch),
  [Node.js](https://nodejs.org), [fio](https://fio.readthedocs.io)
- **측정 기반:** Intel RAPL(Linux `powercap`),
  [NVIDIA NVML / nvidia-smi](https://developer.nvidia.com/system-management-interface),
  Linux cgroup v2, RPICT4V3 펌웨어, KVM/QEMU + libvirt

---

## 11. 문서

| 문서 | 내용 |
|------|------|
| [`docs/setup.md`](docs/setup.md) | 측정 장비 하드웨어 + 소프트웨어 셋업 전 과정 |
| [`docs/hardware_power_analysis.md`](docs/hardware_power_analysis.md) | 전력 측정 분석 노트 |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | 자주 발생하는 문제 및 해결 |
| [`docs/experiments/`](docs/experiments/) | phase별 실험 설계 |
| [`docs/references.md`](docs/references.md) | 관련 연구 및 참고 자료 |
| [`CHANGELOG.md`](CHANGELOG.md) | 실험 로그 및 변경 이력 |

---

## 12. 저자

신우림, 김지윤, 강시연, 조경운, 반효경 — 이화여자대학교 컴퓨터공학과
