# Experiment Plan: VM-level Power Attribution

> 최종 수정: 2026-02-03 (Lab Meeting 피드백 반영)
> 작성자: Team 37 - OptimusPrime

---

## 1. 연구 목표

**핵심 주장**: 클라우드 사업자가 자원 할당량 기준으로 과금하는 현행 방식과 에너지 사용량 기준 과금은 일치하지 않으며, 에너지 기반 과금 모델이 필요하다.

**가설** (2026-02-03 Lab Meeting 반영):

- H1: 동일 자원 할당을 받은 VM_A(AI)와 VM_B(Web)의 에너지 소비는 현저히 다르다
- H2: RAPL+nvidia-smi+cgroup 기반 에너지 귀속 모델이 실측(RPICT)과 높은 일치도를 보인다
- H3: 에너지 기반 과금은 워크로드 특성에 따라 자원 기반 과금과 최대 N배 차이난다

---

## 2. 실험 환경

### 2.1 하드웨어

| 구성요소 | 사양 | 역할 |
|---------|------|------|
| Host Server | Alienware Aurora R12 | VM 실행 및 소프트웨어 측정 |
| CPU | Intel i7-11700KF (8C/16T) | RAPL 에너지 측정 지원 |
| GPU | NVIDIA RTX 3060 12GB | nvidia-smi 전력 측정 |
| RAM | 32GB DDR4 | VM 메모리 할당 |
| Power Meter | RPICT4V3 + Raspberry Pi | 물리적 전력 측정 (Ground Truth) |

### 2.2 소프트웨어

- **OS**: Ubuntu 22.04 LTS
- **Virtualization**: KVM/QEMU + libvirt 8.0.0
- **ML Framework**: PyTorch + CUDA 12.8
- **측정 도구**: RAPL, nvidia-smi, powerstat, perf

### 2.3 네트워크

```
[Alienware: 192.168.0.66] <--LAN--> [Raspberry Pi: 192.168.0.200]
         |
    [virbr0: 192.168.122.1]
         |
    [VM1, VM2, VM3, VM4]
```

---

## 3. 측정 체계 (Three-Layer Architecture)

### Layer 1: Physical Power (Ground Truth)

- **도구**: RPICT4V3 (CT 센서 + AC 어댑터)
- **측정 대상**: 벽면 AC 전력 (시스템 전체)
- **샘플링**: ~1Hz
- **포함 요소**: CPU + GPU + PSU 손실 + 마더보드 + 팬 + 모든 부품

### Layer 2: Component-Level Software

- **CPU/Memory**: Intel RAPL (Package, Core, Uncore, DRAM)
- **GPU**: nvidia-smi power.draw
- **샘플링**: 1-10Hz
- **한계**: 추정값이며, 실제 전력과 차이 있음

### Layer 3: VM Attribution (연구 핵심)

- **입력**: Layer 1 + Layer 2 + VM 리소스 할당 정보
- **출력**: 각 VM별 전력 소비 추정치
- **알고리즘**: Proportional, Shapley, ML-based, Marginal cost

---

## 4. 실험 설계

### Phase 1: Baseline Calibration

| 실험 ID | 시나리오 | 측정 항목 | 목적 |
|---------|---------|----------|------|
| B-01 | Host idle (VM 없음) | RPICT, RAPL, nvidia-smi | 시스템 기본 전력 |
| B-02 | 단일 VM idle | RPICT, RAPL, nvidia-smi | VM 오버헤드 파악 |
| B-03 | 부하별 전력 곡선 | RPICT vs (RAPL + nvidia-smi) | PSU 효율 추정 |

### Phase 2: 컴포넌트별 에너지 분리 (간접 측정)

| 실험 ID | 시나리오 | 측정 | 목적 |
|---------|---------|------|------|
| C-01 | 완전 Idle | RPICT + RAPL + nvidia-smi | E_base + E_mem_idle 분리 |
| C-02 | CPU only stress | RPICT + RAPL | E_cpu 분리, RAPL 검증 |
| C-03 | GPU only stress | RPICT + nvidia-smi | E_gpu 분리 |
| C-04 | IO only stress | RPICT + iostat | E_storage 분리 |
| C-05 | CPU + GPU 동시 | RPICT + RAPL + nvidia-smi | 합산 검증 |

### Phase 3: 워크로드별 에너지 프로파일링

**워크로드** (Lab Meeting 피드백 반영 - 실제 애플리케이션 사용):
- **AI/GPU-heavy**: ResNet-50 v1.5 Inference (MLPerf 표준)
- **전통적/Light**: NGINX + wrk 웹서빙 (CloudSuite 표준)

| 실험 ID | VM 구성 | 워크로드 | 측정 항목 |
|---------|--------|---------|----------|
| W-01 | VM-A solo | ResNet-50 Inference | CPU%, GPU%, E_rapl, E_gpu, E_rpict |
| W-02 | VM-B solo | NGINX + wrk (저부하) | CPU%, GPU%, E_rapl, E_gpu, E_rpict |
| W-03 | VM-A + VM-B 동시 | ResNet-50 + NGINX | E_total, VM별 분배 |

### Phase 4: 검증 실험 (핵심 - 교수님 제시)

**방법**: A solo / B solo / A+B 동시 비교

| 실험 ID | 구성 | 목적 |
|---------|------|------|
| V-01 | VM-A만 (ResNet-50) | E(A_solo) 측정 |
| V-02 | VM-B만 (NGINX) | E(B_solo) 측정 |
| V-03 | VM-A + VM-B 동시 | E(A+B) 측정 + 모델로 분배 |
| V-04 | 검증 | E(A_share) ≈ E(A_solo), E(B_share) ≈ E(B_solo) 확인 |

**핵심 그래프** (논문 핵심):
- 자원 기반 과금 (50:50) vs 에너지 기반 과금 (80:20) 비교

### Phase 5: 에너지 기반 과금 모델

에너지 귀속 모델 적용:
```
E(VM_i) = E_cpu(VM_i) + E_gpu(VM_i) + E_mem(VM_i) + E_storage(VM_i)
```

오차 분석: MAE, RMSE, MAPE
자원 과금 vs 에너지 과금 비교 그래프 도출

---

## 5. 데이터 수집 프로토콜

### 5.1 실험 전 체크리스트

- [ ] 시스템 재부팅 후 10분 안정화
- [ ] 불필요한 백그라운드 프로세스 종료
- [ ] 시간 동기화 확인 (NTP/PTP)
- [ ] 저장 공간 확인 (최소 10GB 여유)
- [ ] 모든 측정 스크립트 테스트 실행

### 5.2 데이터 형식

**RPICT 로그** (`data/raw/rpict/`):

```csv
timestamp,node_id,power_w,voltage_v,current_a,power_factor
2026-02-01T10:00:00.000,1,145.2,220.1,0.66,0.99
```

**RAPL 로그** (`data/raw/rapl/`):

```csv
timestamp,package_j,core_j,uncore_j,dram_j,package_w,core_w,uncore_w,dram_w
2026-02-01T10:00:00.000,1234.56,890.12,123.45,234.56,45.2,32.1,5.6,8.9
```

**GPU 로그** (`data/raw/nvidia/`):

```csv
timestamp,gpu_id,power_w,temp_c,util_gpu,util_mem,mem_used_mb
2026-02-01T10:00:00.000,0,85.5,65,78,45,4096
```

**VM 메트릭** (`data/raw/vm_metrics/`):

```csv
timestamp,vm_name,vcpu_count,cpu_percent,mem_used_mb,mem_total_mb
2026-02-01T10:00:00.000,vm1,4,75.2,8192,16384
```

### 5.3 파일 명명 규칙

```
{source}_{experiment_id}_{date}_{time}.csv
예: rpict_M-03_20260201_100000.csv
```

---

## 6. 분석 계획

### 6.1 데이터 전처리

1. 타임스탬프 기준 모든 소스 병합
2. 이상치 제거 (3σ 규칙)
3. 리샘플링 (1Hz 통일)
4. 결측치 보간 (선형)

### 6.2 시각화

- 시계열 전력 그래프 (RPICT vs RAPL+nvidia-smi)
- 박스플롯 (워크로드별 전력 분포)
- 히트맵 (간섭 행렬)
- 산점도 (예측 vs 실제)

### 6.3 통계 분석

- t-test: 단독 vs 동시 실행 전력 차이 유의성
- ANOVA: 워크로드 유형별 전력 차이
- 회귀 분석: 리소스 사용량 → 전력 예측

---

## 7. 예상 결과

1. **간섭 효과 정량화**: CPU 캐시 경합 시 5-15% 추가 전력 예상
2. **귀속 알고리즘 비교**: Shapley value가 가장 공정할 것으로 예상
3. **실용적 제안**: 클라우드 에너지 기반 빌링 모델 제시

---

## 8. 리스크 및 대응

| 리스크 | 영향 | 대응 방안 |
|-------|------|----------|
| RPICT 센서 오류 | 높음 | 백업 측정 (RAPL only) |
| VM 크래시 | 중간 | 자동 재시작 스크립트 |
| 데이터 손실 | 높음 | 실시간 백업 + Git |
| 시간 동기화 오류 | 중간 | PTP 프로토콜 사용 |

---

## 9. 일정

| 주차 | 목표 | 산출물 |
|-----|------|--------|
| 1-2 | 환경 설정 + 베이스라인 | B-01~B-03 데이터 |
| 3-4 | 단일 VM 프로파일링 | S-01~S-05 데이터, 예측 모델 |
| 5-6 | 다중 VM 간섭 실험 | M-01~M-09 데이터 |
| 7-8 | 귀속 알고리즘 개발 | 알고리즘 코드, 검증 결과 |
| 9-10 | 논문 작성 | 초안 완성 |

---

## 변경 이력

| 날짜 | 변경 내용 | 작성자 |
|-----|----------|-------|
| 2026-02-01 | 최초 작성 | Woorim Shin |
| 2026-02-03 | Lab Meeting 피드백 반영: 워크로드 변경(실제 앱), 에너지 모델 구체화, 검증 실험 추가 | Woorim Shin |
