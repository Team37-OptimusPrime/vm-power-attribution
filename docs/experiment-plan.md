# Experiment Plan: VM-level Power Attribution

> 최종 수정: 2026-02-01
> 작성자: Team 37 - OptimusPrime

---

## 1. 연구 목표

**핵심 질문**: 다중 VM이 동시 실행될 때 발생하는 전력 간섭 효과를 측정하고, 각 VM에 공정하게 전력을 귀속시키는 알고리즘을 개발한다.

**가설**:
- H1: P_total(VM_A + VM_B) ≠ P_A(solo) + P_B(solo) (간섭으로 인한 비선형성 존재)
- H2: 간섭 효과는 워크로드 유형(CPU-bound vs GPU-bound)에 따라 다름
- H3: Shapley value 기반 귀속이 단순 비례 배분보다 공정함

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

### Phase 2: Single VM Profiling

| 실험 ID | 워크로드 | 리소스 | 측정 시간 |
|---------|---------|--------|----------|
| S-01 | CPU stress (stress-ng) | 2/4/6/8 cores | 각 5분 |
| S-02 | GPU stress (gpu-burn) | 25/50/75/100% | 각 5분 |
| S-03 | ResNet18 training | 기본 설정 | 10 epochs |
| S-04 | ResNet50 training | 기본 설정 | 10 epochs |
| S-05 | Inference batch | batch=1,8,32,64 | 각 1000회 |

### Phase 3: Multi-VM Interference (핵심 실험)

| 실험 ID | VM 구성 | 워크로드 조합 | 측정 항목 |
|---------|--------|--------------|----------|
| M-01 | VM-A solo | CPU stress | P_A |
| M-02 | VM-B solo | CPU stress | P_B |
| M-03 | VM-A + VM-B | CPU stress 동시 | P_total, 간섭 분석 |
| M-04 | VM-A solo | GPU training | P_A |
| M-05 | VM-B solo | GPU training | P_B |
| M-06 | VM-A + VM-B | GPU training 동시 | P_total, GPU 경합 |
| M-07 | VM-A + VM-B | CPU + GPU 혼합 | 이종 워크로드 간섭 |
| M-08 | 3 VMs | 다양한 조합 | 확장성 테스트 |
| M-09 | 4 VMs | 다양한 조합 | 최대 부하 테스트 |

**핵심 분석**:
- 간섭 계수 = (P_total - P_idle) / (P_A_solo + P_B_solo - 2*P_idle)
- 1.0 = 간섭 없음, >1.0 = 추가 전력 소모, <1.0 = 효율 개선

### Phase 4: Attribution Algorithm Validation

각 알고리즘에 대해:
1. Multi-VM 실험 데이터에 적용
2. 단일 VM 측정값과 비교 (Ground Truth)
3. 오차 분석 (MAE, RMSE, MAPE)

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
| 2026-02-01 | 최초 작성 | Team 37 |
