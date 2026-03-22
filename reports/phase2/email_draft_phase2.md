# Phase 2 실험 결과 보고 (메일 초안)

**제목**: Phase 2 컴포넌트 분리 + Storage 에너지 실험 결과

---

교수님, 안녕하세요.

지난 회의(2/10) 피드백을 반영하여 Phase 2 실험을 재진행하였습니다.
결과를 정리하여 보고드립니다.

---

## 1. 컴포넌트 물리 분리 실험 (Phase 2.0)

GPU와 DIMM을 물리적으로 탈착하며 4가지 구성(A~D)의 idle 전력을 측정하였습니다.
각 구성별 3회 반복하여 재현성을 확인하였습니다.

| Config | 구성 | Wall (RPICT) | CPU (RAPL) | GPU (nvidia-smi) | Others |
|---|---|---|---|---|---|
| A | 2GPU + 2DIMM | 44.5W | 3.5W | 12.7W | 28.3W |
| B | 2GPU + 1DIMM | 44.8W | 3.6W | 13.6W | 27.7W |
| C | 1GPU + 1DIMM | 31.4W | 2.7W | 7.3W | 21.4W |
| D | 1GPU + 2DIMM | 30.8W | 2.6W | 7.0W | 21.2W |

> [첨부: fig1_config_comparison.pdf — Config별 idle 전력 stacked bar]

### 교차검증 (Cross-Validation)

두 개의 독립 경로로 각 컴포넌트의 순수 영향을 분리하였습니다.

- **GPU 1장의 wall 영향**: 경로1(B-C) = 13.4W, 경로2(A-D) = 13.8W → **평균 13.6W/card** (편차 0.3W, 경로간 일관)
- **GPU hidden overhead**: nvidia-smi가 보고하지 않는 PCIe+VRM+팬 전력 = **7.6W/card** (GPU wall 13.6W - sensor delta 6.0W)
- **Memory (DIMM 1장)**: 경로1(A-B) = +0.7W, 경로2(D-C) = -0.2W → **평균 0.25W/DIMM** (idle 기여 미미)
- **가산성 검증 (Superposition)**: Config A 예측(C + GPU + MEM) = 45.2W vs 측정 44.5W → **오차 0.7W (1.6%)**
- **Closure test (A-B-D+C)**: +0.34W ≈ 0 → 컴포넌트가 가산적으로 분리됨

> [첨부: fig2_cross_validation.pdf — GPU 분리 + Superposition 검증]

### Others 분해 결과

센서만으로는 Others가 63.7%(28.3W)이었으나, 물리분리 + 추정을 통해 89%를 분해하였습니다.

| 컴포넌트 | 전력 | 비율 | 방법 |
|---|---|---|---|
| CPU (RAPL) | 3.5W | 7.9% | 직접측정 |
| GPU chip × 2 (nvidia-smi) | 12.7W | 28.5% | 직접측정 |
| GPU hidden × 2 (PCIe+VRM+팬) | 15.2W | 34.2% | 물리분리 |
| Memory (2 DIMM) | 0.3W | 0.6% | 물리분리 |
| PSU 변환손실 (~22%) | 9.8W | 22.0% | 효율곡선 추정 |
| **Chipset+Fan+기타 (잔여)** | **3.1W** | **6.9%** | **잔여** |

- **Others의 가장 큰 원인은 GPU hidden overhead** (전체의 34%, 이전 Others의 54%)
- 회의에서 지적해 주신 "숨겨진 GPU가 기본 전력을 소모"하는 문제가 수치적으로 확인되었습니다.

> [첨부: fig3_others_decomposition.pdf — Before/After 비교 파이차트]
> [첨부: fig5_power_breakdown.pdf — 전력 분해 요약 (수평 stacked bar)]

---

## 2. fio Storage 에너지 실험 (Phase 2.1)

회의에서 지적해 주신 "fio delta 46W에 CPU 전력이 대부분 포함되어 있다"는 문제를 해결하였습니다.

### 실험 환경
- SSD: Samsung 980 500GB (PCIe 3.0 x4)
- fio: bs=1M, iodepth=32, direct=1, 60s
- CPU: no_turbo=1, governor=powersave, max 3600MHz (컴포넌트 분리 실험과 동일)

### Storage Energy Attribution

`Storage = dWall(RPICT) - dCPU(RAPL) - dGPU(nvidia-smi)`

| 항목 | seq_write (2266 MB/s) | seq_read (3002 MB/s) |
|---|---|---|
| dWall (RPICT) | +12.2W | +16.7W |
| dCPU (RAPL) | +6.9W | +8.6W |
| dGPU | ~0W | ~0W |
| **순수 Storage (AC)** | **5.6W** | **8.3W** |
| **순수 Storage (DC @78%)** | **4.3W** | **6.5W** |
| Storage rate | 0.0025 W/(MB/s) | 0.0028 W/(MB/s) |

- Samsung 980 데이터시트 active power 3.9W 대비, 측정 DC 4.3~6.5W → PCIe 컨트롤러 오버헤드 포함
- 이전 v1에서 46W 전체를 storage로 귀속한 오류를 수정하여, CPU delta를 분리한 결과입니다.
- disk_util 99.9%, IOPS/throughput이 SSD 스펙과 일치하여 실험 유효성을 확인하였습니다.

> [첨부: fig4_fio_storage.pdf — Wall Power Timeline + Storage Attribution]

### 최종 Storage Energy Parameter

실제 워크로드에 적용할 rate를 도출하였습니다.

- **Storage rate (AC)**: 0.0025 ~ 0.0028 W/(MB/s)
- **Storage rate (DC)**: 0.0019 ~ 0.0022 W/(MB/s)
- 적용 방법: `워크로드 Storage 에너지 = rate × 해당 워크로드의 IO throughput`

---

## 3. 다음 단계: 동시실행 실험

위 실험으로 모든 컴포넌트의 에너지 파라미터가 준비되었습니다.

| 컴포넌트 | 분배 기준 | 파라미터 출처 |
|---|---|---|
| CPU | 이용률 비례 | RAPL (cgroup별 이용률) |
| GPU 코어 | 이용률 비례 | nvidia-smi (프로세스별) |
| GPU 메모리 | 할당 비례 | nvidia-smi allocated |
| Memory | 할당 비례 | cgroup mem 할당량 |
| Storage | IO량 비례 | rate × cgroup io.stat |

회의에서 말씀하신 **"A solo → B solo → A+B 동시실행 → 분배 비율 일치 검증"** 실험을 다음으로 진행하겠습니다.

---

첨부 파일:
1. fig1_config_comparison.pdf — Config A~D 전력 비교
2. fig2_cross_validation.pdf — GPU 분리 + Superposition 검증
3. fig3_others_decomposition.pdf — Others 분해 Before/After
4. fig4_fio_storage.pdf — fio Timeline + Storage Attribution
5. fig5_power_breakdown.pdf — 전력 분해 요약
6. phase2_component_isolation_summary.csv — 전체 수치 데이터

감사합니다.
신우림 드림
