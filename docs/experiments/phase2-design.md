# Phase 2 실험 설계: Others 에너지 분해 및 완전한 Attribution 모델

> 작성일: 2026-02-09
> 작성자: Team 37 - OptimusPrime
> 교수님 피드백 (2026-02-06~07) 반영

---

## 1. Phase 2 목표

**핵심 목표**: Idle 상태 Others(22.7W)를 측정값 기반으로 최대한 분리하여 5-component 에너지 분해 모델 완성

### 1.1 에너지 분해 모델 (교수님 수식)

```
Wall Power = CPU + GPU + Memory + Storage + Fixed_Others

여기서:
  CPU     = RAPL 측정값 (직접 측정)
  GPU     = nvidia-smi 측정값 (직접 측정)
  Memory  = DIMM 실험으로 파라미터 도출 (Phase 2.0)
  Storage = fio 실험으로 파라미터 도출 (Phase 2.0)
  Fixed_Others = Wall - CPU - GPU - Memory - Storage (잔여)
```

### 1.2 현재 상태 (Phase 1.6 결과)

```
Others = 22.7W (Idle 기준) → 전체 Wall Power의 62%가 미분해 상태

Others의 예상 구성 (hardware_power_analysis.md 참조):
  DRAM (2 DIMMs)     : 2~4W   (DDR4-3467 Micron, 1-2W/DIMM refresh power)
  NVMe SSD           : 0.1~0.5W (Samsung 980, PS3 idle = 30mW)
  Chipset (B560)     : 3~4W   (TDP 6W, idle ~50-60%)
  Fans (×4)          : 4~8W   (~1-2W per fan)
  VRM/DC-DC          : 2~3W   (전압 변환 손실)
  RGB/Peripherals    : 2~3W   (Alienware RGB, USB, Audio)
  ────────────────────────────
  합계 추정           : 13.5~22.5W  (실측 22.7W와 부합)
```

### 1.3 Phase 2에서 분리 가능한 것 vs 불가능한 것

| 컴포넌트 | 분리 방법 | Phase 2 가능 여부 |
|----------|----------|------------------|
| **DRAM** | DIMM 물리 실험 (32GB→16GB) | **가능** (BIOS 설정) |
| **Storage** | fio 실험 (active vs idle) | **가능** (SW 실험) |
| Chipset | 분리 불가 (항상 켜짐) | Fixed_Others에 포함 |
| Fans | 분리 불가 (온도 연동) | Fixed_Others에 포함 |
| VRM | 분리 불가 (간접 손실) | Fixed_Others에 포함 |
| RGB | 분리 불가 | Fixed_Others에 포함 |

**Phase 2 후 모델**:
```
Wall = CPU + GPU + Memory(측정) + Storage(측정) + Fixed_Others(잔여)
                    ↑ 새로 분리      ↑ 새로 분리      ↑ 크기 축소됨
```

---

## 2. 실험 환경

### 2.1 하드웨어 (Phase 1.5와 동일)

| 구성요소 | 사양 | 비고 |
|---------|------|------|
| Host | Alienware Aurora R12 | |
| CPU | Intel i7-11700KF (8C/16T, 125W TDP) | RAPL 지원 |
| GPU | NVIDIA RTX 3060 12GB | nvidia-smi 전력 측정 |
| RAM | **32GB DDR4-3467** (Micron 16GB × 2, Slot 2/4 사용) | **DIMM 실험 대상** |
| Storage | **Samsung SSD 980 500GB** (NVMe PCIe) | **fio 실험 대상** |
| Chipset | Intel B560 (TDP 6W) | |
| Power Meter | RPICT4V3 + Raspberry Pi | Ground Truth |

### 2.2 측정 도구

| 도구 | 측정 대상 | 출력 |
|------|----------|------|
| RPICT4V3 | Wall Power | W (3초 간격) |
| Intel RAPL | CPU Package/Core/DRAM | W (1초 간격) |
| nvidia-smi | GPU Power, Util%, Temp | W (1초 간격) |
| cgroup v2 | Per-slice CPU%, Memory, IO | (1초 간격) |
| **cpufreq (신규)** | **Per-core CPU Frequency** | **MHz (1초 간격)** |

### 2.3 측정 인프라 보완 (Phase 2.1)

Phase 1.6에서 발견된 문제점 해결:

| 문제 | 원인 | 해결 방안 |
|------|------|----------|
| cgroup IO = 0.0 | io.stat 미활성화 | `+io` controller 활성화 + io.cost 설정 |
| CPU frequency 미수집 | host_logger에 미포함 | `/sys/devices/system/cpu/cpuN/cpufreq/scaling_cur_freq` 수집 추가 |
| RAPL DRAM = 0.0 | Rocket Lake 아키텍처 제한 | DIMM 물리 실험으로 대체 |

---

## 3. 실험 단계

### Phase 2.0a: DIMM 물리 실험 (Memory 에너지 파라미터)

**목적**: DRAM 에너지 파라미터 (W/DIMM 또는 W/GB) 실측

**원리**:
```
실험1) 32GB (2 DIMM) idle → Wall₁
실험2) 16GB (1 DIMM) idle → Wall₂   (BIOS에서 1개 DIMM 비활성화)

Memory_per_DIMM = Wall₁ - Wall₂
Memory_per_GB = (Wall₁ - Wall₂) / 16

조건: CPU, GPU, SSD, Fan 등은 모두 동일해야 함
     → 같은 Idle 상태에서 DIMM 수만 다르게
```

**주의사항**:
- 반드시 **BIOS에서** DIMM 비활성화 (물리 제거 또는 BIOS 설정)
- OS 레벨에서 `memory hotplug`로 비활성화하면 refresh power가 계속 소모됨
- 실험 전/후 다른 조건 동일한지 확인 (팬 속도, 온도 등)

**절차**:
1. 32GB (현재 상태) idle 측정 (5분, 안정화 후)
2. 시스템 종료
3. BIOS 진입 → DIMM 1개 비활성화 (또는 물리적 제거)
4. 부팅 → 16GB 확인
5. 16GB idle 측정 (5분, 안정화 후)
6. (선택) DIMM 복구 후 32GB 재측정 (재현성 확인)

**측정 항목**:
- Wall Power (RPICT) - 5분 평균
- CPU Power (RAPL) - 동일해야 함
- GPU Power (nvidia-smi) - 동일해야 함
- 온도 (lm-sensors) - 유사해야 함
- 팬 속도 - 유사해야 함

**예상 결과**:
```
DDR4 DIMM idle power: 1~2W per DIMM (데이터시트 기반)
→ Wall₁ - Wall₂ ≈ 1~2W
→ Memory_per_GB ≈ 0.06~0.13 W/GB
```

### Phase 2.0b: fio Storage 실험 (Storage 에너지 파라미터)

**목적**: Storage IO당 에너지 파라미터 (W 또는 W/(MB/s)) 실측

**원리**:
```
실험1) Idle → Wall_idle (Storage IO 없음)
실험2) fio sequential read → Wall_read
실험3) fio sequential write → Wall_write

Storage_read_power  = Wall_read - Wall_idle - dCPU_fio
Storage_write_power = Wall_write - Wall_idle - dCPU_fio

여기서 dCPU_fio = fio 실행 시 추가 CPU 에너지 (RAPL로 측정)
```

**fio 설정**:
```bash
# Sequential Read (Direct IO, 시스템 캐시 우회)
fio --name=seq_read --ioengine=libaio --direct=1 \
    --rw=read --bs=1M --iodepth=32 \
    --size=4G --numjobs=1 --runtime=60 \
    --filename=/tmp/fio_test

# Sequential Write
fio --name=seq_write --ioengine=libaio --direct=1 \
    --rw=write --bs=1M --iodepth=32 \
    --size=4G --numjobs=1 --runtime=60 \
    --filename=/tmp/fio_test

# Random Read (4KB, 실제 워크로드 패턴)
fio --name=rand_read --ioengine=libaio --direct=1 \
    --rw=randread --bs=4k --iodepth=32 \
    --size=1G --numjobs=1 --runtime=60 \
    --filename=/tmp/fio_test

# Random Write
fio --name=rand_write --ioengine=libaio --direct=1 \
    --rw=randwrite --bs=4k --iodepth=32 \
    --size=1G --numjobs=1 --runtime=60 \
    --filename=/tmp/fio_test
```

**절차**:
1. Idle baseline 측정 (60초)
2. fio sequential read (60초) + 전력 측정
3. Cooldown (30초)
4. fio sequential write (60초) + 전력 측정
5. Cooldown (30초)
6. fio random read (60초) + 전력 측정
7. Cooldown (30초)
8. fio random write (60초) + 전력 측정

**측정 항목**:
- Wall Power (RPICT)
- CPU Power (RAPL) - fio CPU 오버헤드 보정용
- GPU Power (nvidia-smi) - 변화 없어야 함
- fio throughput (MB/s) 및 IOPS
- IO latency

**예상 결과**:
```
Samsung 980 NVMe (데이터시트 기반):
  Idle: ~30mW
  Sequential Read (3,500 MB/s): ~3.5W
  Sequential Write (3,000 MB/s): ~3.9W
  Random Read: ~3.5W
  Random Write: ~3.9W

→ Storage_power ≈ 3~4W (active)
→ Storage_per_MBs ≈ 0.001 W/(MB/s)
```

### Phase 2.1: 측정 인프라 보완

#### 2.1a: cgroup io.stat 활성화

**문제**: Phase 1.6 cgroup 데이터에서 io_read_kbs, io_write_kbs가 전부 0.0

**원인 분석**:
1. cgroup v2 `+io` controller가 subtree_control에 미등록
2. io.cost 또는 io.max 정책 미설정 시 io.stat 미집계

**해결**:
```bash
# 1. io controller 활성화
echo "+io" | sudo tee /sys/fs/cgroup/cgroup.subtree_control

# 2. 블록 디바이스 확인
lsblk -d -o NAME,MAJ:MIN
# nvme0n1 259:0

# 3. io.cost.qos 또는 io.max 설정 (io accounting 활성화)
# io.cost.qos 설정 시 io.stat이 집계됨
echo "259:0 enable=1" | sudo tee /sys/fs/cgroup/yolo.slice/io.cost.qos
echo "259:0 enable=1" | sudo tee /sys/fs/cgroup/nodejs.slice/io.cost.qos

# 4. 확인
cat /sys/fs/cgroup/yolo.slice/io.stat
```

**검증**: 워크로드 실행 후 io.stat에 rbytes/wbytes 값이 기록되는지 확인

#### 2.1b: CPU Frequency 수집 추가

**목적**: B2 concurrent 조합에서 관찰된 ~12-14% error의 원인 규명 (frequency throttling)

**수집 방법**: host_logger.py에 추가
```python
# Per-core frequency (MHz)
for cpu_id in range(8):
    path = f"/sys/devices/system/cpu/cpu{cpu_id}/cpufreq/scaling_cur_freq"
    freq_khz = int(open(path).read().strip())
    freq_mhz = freq_khz / 1000
```

**출력 CSV 컬럼 추가**:
```
...,cpu0_freq_mhz,cpu1_freq_mhz,cpu2_freq_mhz,...,cpu7_freq_mhz
```

**기대 효과**:
- B2 solo: CPU 2-3이 높은 frequency (4.7GHz boost)
- A2+B2 concurrent: CPU 2-3의 frequency가 낮아질 수 있음 (thermal throttling)
- 이 데이터로 비선형 효과 설명 가능

### Phase 2.2: 완전한 Attribution 모델 검증 실험

**Phase 2.0, 2.1의 파라미터를 적용한 최종 검증**

#### 2.2a: 5-Component 분해

Phase 2.0에서 도출한 파라미터로 모든 Phase를 재분석:

```
각 Phase에 대해:
  CPU_energy      = RAPL 측정값 (직접)
  GPU_energy      = nvidia-smi 측정값 (직접)
  Memory_energy   = DIMM_per_GB × allocated_GB
  Storage_energy  = Storage_param × IO_throughput
  Fixed_Others    = Wall - CPU - GPU - Memory - Storage

검증: Fixed_Others가 모든 Phase에서 일정한 값(~15-18W)이면 모델 성공
```

#### 2.2b: Attribution 모델 (Concurrent → 개별 워크로드 귀속)

```
Concurrent 실행 시 A, B 각각의 에너지 귀속:

  CPU_A = (CPU_total - CPU_idle) × (A_cgroup_cpu% / (A_cgroup_cpu% + B_cgroup_cpu%))
  CPU_B = (CPU_total - CPU_idle) × (B_cgroup_cpu% / (A_cgroup_cpu% + B_cgroup_cpu%))

  GPU_A = GPU_total - GPU_idle  (YOLO만 GPU 사용)
  GPU_B = 0

  Mem_A = Mem_per_GB × A_allocated_GB
  Mem_B = Mem_per_GB × B_allocated_GB

  Storage_A = Storage_param × A_IO_throughput
  Storage_B = Storage_param × B_IO_throughput

  Idle_shared = (CPU_idle + GPU_idle + Fixed_Others) / n_workloads
    또는 가중 분배

  Total_A = CPU_A + GPU_A + Mem_A + Storage_A + Idle_shared
  Total_B = CPU_B + GPU_B + Mem_B + Storage_B + Idle_shared
```

#### 2.2c: Solo vs Concurrent 재검증

**검증 기준**:
```
성공: |Attributed_A - Solo_A| / Solo_A < 10% (모든 조합에서)
```

| 조합 | Phase 1.6 Error | Phase 2.2 목표 |
|------|----------------|----------------|
| A1+B1 | +0.03% | < 5% |
| A1+B2 | **-12.6%** | < 10% (비선형 효과 보정 후) |
| A2+B1 | +1.4% | < 5% |
| A2+B2 | **-10.5%** | < 10% (비선형 효과 보정 후) |

#### 2.2d: B2 비선형 효과 분석

**관찰된 현상**: B2(Node.js Heavy) 포함 조합에서 ~12-14% under-prediction

**가설**:
1. **CPU Frequency Scaling**: B2가 3.5코어 사용 시 thermal throttling → per-core frequency 감소
2. **L3 Cache Contention**: YOLO(코어 0-1)와 Node.js(코어 2-3)가 L3 캐시 공유
3. **Memory Bandwidth Contention**: 32GB 단일 채널에서 bandwidth 경쟁

**검증 데이터**:
- CPU frequency 로그 (Phase 2.1b에서 추가)
- Intel PCM 캐시 miss 데이터 (선택)
- 메모리 bandwidth (Intel PCM)

---

## 4. 실험 일정

| 단계 | 작업 | 소요 시간 | 선행 조건 |
|------|------|----------|----------|
| 2.1a | cgroup io.stat 활성화 | 30분 | - |
| 2.1b | host_logger에 cpufreq 추가 | 30분 | - |
| 2.0a | DIMM 물리 실험 | 1~2시간 | BIOS 접근 (시스템 재부팅) |
| 2.0b | fio Storage 실험 | 1시간 | 2.1a, 2.1b 완료 |
| 2.2 | 최종 검증 실험 (4 solo + 4 concurrent) | 1~2시간 | 2.0a, 2.0b, 2.1 모두 완료 |
| 분석 | 5-component 모델 적용 + 그래프 생성 | 2~3시간 | 2.2 완료 |

**총 예상 시간: 1~2일**

---

## 5. 파일 구조 (예정)

```
data/raw/
├── alienware/
│   ├── phase1.6_test2/         # 기존 데이터 (유지)
│   ├── phase2.0_dimm/          # DIMM 실험 데이터
│   │   ├── 32gb_idle_host.csv
│   │   ├── 16gb_idle_host.csv
│   │   └── dimm_comparison.csv
│   ├── phase2.0_fio/           # fio 실험 데이터
│   │   ├── idle_host.csv
│   │   ├── seq_read_host.csv
│   │   ├── seq_write_host.csv
│   │   ├── rand_read_host.csv
│   │   ├── rand_write_host.csv
│   │   └── fio_results.json
│   └── phase2.2_validation/    # 최종 검증 실험 (인프라 보완 후)
│       ├── *_host.csv          # cpufreq 컬럼 추가
│       └── *_cgroup.csv        # io.stat 데이터 포함

scripts/
├── measurement/
│   ├── host_logger.py          # cpufreq 수집 추가 (Phase 2.1b)
│   └── cgroup_logger.py        # io.stat 정상 동작 확인 (Phase 2.1a)
├── workloads/
│   ├── setup_cgroups.sh        # io controller 활성화 추가 (Phase 2.1a)
│   ├── run_dimm_experiment.sh  # DIMM 실험 스크립트 (Phase 2.0a)
│   ├── run_fio_experiment.sh   # fio 실험 스크립트 (Phase 2.0b)
│   └── run_experiment_phase2.sh # 최종 검증 스크립트 (Phase 2.2)
└── analysis/
    ├── dimm_analysis.py        # DIMM 실험 분석
    ├── fio_analysis.py         # fio 실험 분석
    └── attribution_model_v2.py # 5-component attribution 모델

reports/phase2/
├── parameters/                 # 도출된 에너지 파라미터
│   └── energy_parameters.json
├── figures/                    # 차트
└── validation/                 # 검증 결과
```

---

## 6. 성공 기준

### 6.1 DIMM 실험
- [ ] 32GB vs 16GB Wall Power 차이가 유의미 (>0.5W)
- [ ] CPU/GPU 전력은 두 실험에서 동일 (차이 <0.5W)
- [ ] W/GB 파라미터 도출 가능

### 6.2 fio 실험
- [ ] Active vs Idle Storage 전력 차이 관찰
- [ ] Sequential/Random Read/Write 각각의 에너지 파라미터 도출
- [ ] CPU 오버헤드 (RAPL) 보정 후 순수 Storage 전력 분리 가능

### 6.3 인프라 보완
- [ ] cgroup io.stat에 rbytes/wbytes 정상 기록
- [ ] host_logger에 per-core frequency 기록
- [ ] 기존 Phase 1.6 실험 재현 가능 (동일 스크립트 + 보완된 로거)

### 6.4 최종 모델 검증
- [ ] Fixed_Others가 모든 Phase에서 일정 (표준편차 <2W)
- [ ] 모든 4개 concurrent 조합에서 attribution error < 10%
- [ ] B2 비선형 효과를 frequency 데이터로 설명 가능

---

## 7. Phase 1.6 → Phase 2 데이터 연속성

### 7.1 기존 데이터 활용
Phase 1.6 데이터는 그대로 유지하며, Phase 2.0에서 도출한 파라미터를 Phase 1.6 데이터에도 소급 적용:

```
Phase 1.6 데이터에 Phase 2.0 파라미터 적용:
  Memory_energy = DIMM_param × allocated_GB
  Storage_energy = 0 (Phase 1.6에서는 IO 데이터 없음 → 추정 불가)
  Fixed_Others = Others(22.7W) - Memory_energy - Storage_energy(≈0)
```

### 7.2 Phase 2.2에서 새로 측정하는 이유
- cgroup IO가 정상 동작하는 상태에서 재측정 필요
- CPU frequency 데이터 필요
- 재현성 확인

---

## 8. 리스크 및 대안

| 리스크 | 영향 | 대안 |
|-------|------|------|
| BIOS에서 DIMM 비활성화 불가 | Memory 파라미터 미도출 | DDR4 데이터시트 값 사용 (1~2W/DIMM) |
| DIMM 실험 결과 차이가 미미 (<0.3W) | 통계적 유의성 부족 | 데이터시트 + 실험 결합, 반복 측정 |
| fio 실행 시 CPU 부하가 커서 Storage 분리 어려움 | Storage 에너지 과대 추정 | RAPL로 CPU 부하 보정, `--cpus_allowed` 옵션으로 특정 코어 제한 |
| cgroup io.stat 여전히 0 | IO 귀속 불가 | `/proc/[pid]/io` 프로세스별 IO 수집으로 대체 |
| B2 비선형 효과 설명 불가 | 모델 정확도 한계 | "비선형 보정 계수" 도입 (경험적) |

---

## 변경 이력

| 날짜 | 변경 내용 | 작성자 |
|-----|----------|-------|
| 2026-02-09 | Phase 2 설계 최초 작성 | Claude + 팀원 |
