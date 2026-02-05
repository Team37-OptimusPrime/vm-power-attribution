# VM Energy Attribution Model

> 최종 수정: 2026-02-03 <br>
> 작성자: Woorim Shin <br>
> 근거: 2026-02-03 Lab Meeting (반효경 교수님 피드백 반영)

---

## 1. 문제 정의

### 1.1 현행 과금 방식 (Resource-based)

클라우드 사업자는 VM에 **할당된 자원량** 기준으로 과금한다:

```
Cost_resource(VM_i) = f(vCPU수, Memory크기, GPU할당, Storage크기)
```

### 1.2 제안 과금 방식 (Energy-based)

실제 **에너지 소비량** 기준 과금은 자원 기반 과금과 일치하지 않는다:

```
Cost_energy(VM_i) ≠ Cost_resource(VM_i)
```

**논문의 핵심 주장**: 이 차이를 실측으로 보이고, 에너지 기반 과금 방식을 제시한다.

---

## 2. 전체 시스템 에너지 모델

### 2.1 전체 에너지 분해

```
E_wall = E_base + E_cpu + E_gpu + E_mem + E_storage + E_psu_loss

where:
  E_wall     = RPICT로 측정한 벽면 전력 (Ground Truth)
  E_base     = OS 베이스라인 에너지 (데몬, 커널 등)
  E_cpu      = CPU 에너지 (RAPL 측정)
  E_gpu      = GPU 에너지 (nvidia-smi 측정)
  E_mem      = DRAM 에너지 (간접 측정/데이터시트)
  E_storage  = Storage 에너지 (IO량 기반 계산)
  E_psu_loss = PSU 변환 손실 + VRM + 팬 등
```

### 2.2 PSU 효율 모델

```
E_wall = E_internal / η(load)

where η(load) = PSU 효율 (부하에 따라 변동, 일반적으로 80-90%)
E_internal = E_base + E_cpu + E_gpu + E_mem + E_storage
```

---

## 3. 리소스별 에너지 특성 (교수님 피드백 반영)

### 3.1 CPU 에너지

**특성**: 이용률(utilization)에 비례

```
E_cpu ∝ CPU_utilization
```

**측정**: Intel RAPL (Package domain)

**VM 분리**:

```
E_cpu(VM_i) = (cpu_util_i / Σ cpu_util_all) × E_cpu_rapl

where cpu_util_i = cgroup에서 측정한 VM_i의 CPU 이용률
```

- cgroup v2 (`/sys/fs/cgroup/`) 또는 libvirt API로 VM별 CPU time 획득 가능
- **핵심**: 할당된 vCPU 수가 아니라 **실제 사용률**이 에너지 결정

### 3.2 GPU 에너지

**특성**: 코어(연산) + 메모리(상수) 혼합 모델

```
E_gpu = E_gpu_core + E_gpu_mem

where:
  E_gpu_core ∝ GPU_core_utilization  (연산량에 비례)
  E_gpu_mem  ∝ GPU_mem_allocated     (할당량에 비례, 상수)
```

**측정**: nvidia-smi (전체 어댑터 전력)

**VM 분리** (실험 환경):

- 방법 A: GPU 2장 → 각 VM에 물리적으로 분리 할당 (PCI passthrough)
- 방법 B: 프로세스별 nvidia-smi 활용 (MPS 환경)
- 논문에서는: "클라우드에서는 vGPU로 분리 가능" 언급 + 실험에서는 방법 A/B 사용

```
E_gpu(VM_i) = E_gpu_mem(VM_i) + (gpu_util_i / Σ gpu_util_all) × E_gpu_core_total

where:
  E_gpu_mem(VM_i) = (gpu_mem_alloc_i / gpu_mem_total) × E_gpu_mem_total
  gpu_util_i = VM_i의 GPU 코어 이용률
```

### 3.3 DRAM 에너지

**특성**: 할당량에 비례 (이용량 아님!)

```
E_mem = E_mem_idle + E_mem_active

where:
  E_mem_idle   >> E_mem_active  (DRAM 리프레시가 지배적)
  E_mem_active ≈ 0              (R/W 에너지 무시 가능)
```

따라서:

```
E_mem ≈ E_mem_idle ∝ DRAM_size_allocated
```

**VM 분리**:

```
E_mem(VM_i) = (mem_alloc_i / mem_total) × E_mem_total
```

**측정 방법**:

1. 데이터시트 기반: Samsung DDR4 사양서에서 idle power 확인
2. 간접 측정: 시스템 idle 시 E_wall - E_cpu_rapl - E_gpu_smi ≈ E_mem + E_base
3. 검증: 아무것도 안 돌리고 측정 → CPU/GPU 에너지 빼기

**교수님 코멘트**: "메모리를 많이 썼네 적게 썼네는 중요한 게 아니고, 많이 받았으면 많이 에너지가 나오는 거다"

### 3.4 Storage 에너지

**특성**: IO량에 비례 (메모리와 정반대)

```
E_storage = E_storage_active ∝ IO_volume

where:
  E_storage_idle ≈ 0  (Non-volatile, 안 쓰면 에너지 안 듦)
```

**VM 분리**:

```
E_storage(VM_i) = (io_volume_i / Σ io_volume_all) × E_storage_total
```

**측정**:

- IO량: cgroup blkio 또는 `/proc/diskstats`로 VM별 측정 가능
- 단위 에너지: SSD/HDD 데이터시트에서 read/write 당 에너지
- 간접 측정: IO만 집중적으로 발생시키고 E_wall 변화 관찰

---

## 4. VM별 최종 에너지 귀속 모델

```
E(VM_i) = E_cpu(VM_i) + E_gpu(VM_i) + E_mem(VM_i) + E_storage(VM_i)

where:
  E_cpu(VM_i)     = (cpu_util_i / Σ cpu_util) × E_cpu_rapl
  E_gpu(VM_i)     = (gpu_mem_i/gpu_mem_total)×E_gpu_mem + (gpu_util_i/Σ gpu_util)×E_gpu_core
  E_mem(VM_i)     = (mem_alloc_i / mem_total) × E_mem_total
  E_storage(VM_i) = (io_vol_i / Σ io_vol) × E_storage_total

그리고:
  E_base = OS 베이스라인 (과금 불가, 사업자 부담)
  E_psu_loss = PSU 효율 손실 (과금 불가 또는 비례 분배)

검증:
  Σ E(VM_i) + E_base ≈ E_wall × η(load)
```

---

## 5. 과금 비교 프레임워크

### 5.1 Resource-based vs Energy-based

```
VM_A: 4 vCPU, 16GB RAM, 1 GPU share  →  Cost_resource = X
VM_B: 4 vCPU, 16GB RAM, 1 GPU share  →  Cost_resource = X  (동일)

하지만:
  VM_A runs AI training (GPU 100%)    →  Cost_energy = 3X
  VM_B runs web server (GPU idle)     →  Cost_energy = 0.5X

→ 동일 자원이지만 에너지 비용은 6배 차이!
```

### 5.2 핵심 그래프 (교수님 강조)

"리소스는 동등하게 나눴는데, 에너지 관점에서는 비용이 확 나더라"

```
| Metric          | VM_A (AI)  | VM_B (Web) |
|-----------------|------------|------------|
| Resource Cost   | 50%        | 50%        |
| Energy Cost     | ~80%       | ~20%       |
| Gap             | +30%p      | -30%p      |
```

---

## 6. 측정 가능성 정리

| 항목 | 측정 가능? | 방법 | VM 분리 가능? |
|------|-----------|------|-------------|
| 전체 전력 | O | RPICT (벽면) | N/A |
| CPU 에너지 | O | RAPL | O (cgroup) |
| GPU 에너지 | O | nvidia-smi | △ (물리 분리 or 프로세스별) |
| DRAM 에너지 | △ | 간접 (전체-CPU-GPU) | O (할당량 비율) |
| Storage 에너지 | △ | 데이터시트 + IO량 | O (cgroup blkio) |
| 네트워크 | X | 무시 가능 | - |
| PSU 손실 | △ | E_wall - E_internal | N/A |

---

## 7. 검증 전략

### 7.1 단일 분리 검증

```
실험 1: 아무것도 안 돌림         → E_base + E_mem_idle
실험 2: CPU만 stress             → E_base + E_cpu + E_mem_idle
실험 3: GPU만 stress             → E_base + E_gpu + E_mem_idle
실험 4: IO만 stress              → E_base + E_storage + E_mem_idle

→ 각 컴포넌트 에너지 분리 가능
```

### 7.2 교차 검증 (교수님 제시)

```
실험 A: VM_A만 돌림              → E(A_solo)
실험 B: VM_B만 돌림              → E(B_solo)
실험 C: VM_A + VM_B 동시         → E(A+B)

검증: 우리 모델로 E(A+B)에서 분배한 E(A_share), E(B_share)가
      E(A_solo), E(B_solo)와 유사한가?
```

---

## 변경 이력

| 날짜 | 변경 내용 | 근거 |
|-----|----------|------|
| 2026-02-03 | 최초 작성 | Lab Meeting 피드백 반영 |
