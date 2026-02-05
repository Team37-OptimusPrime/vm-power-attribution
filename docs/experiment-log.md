# Experiment Log

> 실험 수행 일지 - 날짜별 상세 기록

---

## 2026-02-01 (Day 1)

### 오늘의 목표
- [x] 프로젝트 초기 설정
- [x] 문서화 체계 구축
- [ ] 측정 스크립트 작성 시작
- [ ] RPICT 시스템 설정

### 진행 상황

#### 1. 환경 확인 (완료)
원격 서버 (Alienware) 상태 확인:
- KVM/QEMU: 설치됨
- libvirt: 8.0.0
- RAPL: `/sys/class/powercap/intel-rapl/` 접근 가능
- nvidia-smi: CUDA 12.8, Driver 570.211.01

```bash
# 추가 도구 설치 완료
sudo apt install linux-tools-common linux-tools-generic powerstat -y
```

#### 2. 문서화 체계 구축 (완료)
생성된 문서:
- `docs/experiment-plan.md`: 실험 설계 문서
- `docs/experiment-log.md`: 실험 일지 (본 문서)
- `docs/setup.md`: 환경 설정 가이드 (예정)

#### 3. Task 정의 (완료)
```
#1 [pending] RPICT 시스템 Raspberry Pi 설정
#2 [pending] Host 데이터 수집 스크립트 작성
#3 [pending] Ubuntu VM 생성 및 네트워크 설정
#4 [pending] Idle 상태 베이스라인 전력 측정 (blocked by #1,2,3)
#5 [pending] VM 워크로드 스크립트 작성
#6 [pending] 다중 VM 간섭 실험 수행 (blocked by #4,5)
#7 [pending] 전력 귀속 알고리즘 구현 (blocked by #6)
#8 [in_progress] 문서화 체계 구축
```

### 다음 단계
1. `scripts/measurement/` 에 RAPL, nvidia-smi 수집 스크립트 작성
2. RPICT 시스템 물리적 배선 및 Raspberry Pi 설정
3. 첫 번째 VM 생성

### 메모
- RPICT 하드웨어 도착 여부 확인 필요
- Raspberry Pi에 고정 IP 192.168.0.200 설정 필요
- Intel I350-T2 NIC는 PTP 지원하므로 정밀 시간 동기화 가능

---

## 2026-02-02 (Day 2)

### 오늘의 목표
- [x] RPICT 시스템 Raspberry Pi 설정
- [x] Host 데이터 수집 스크립트 작성
- [x] 첫 번째 CPU 스트레스 테스트 및 전력 측정

### 진행 상황

#### 1. RPICT 시스템 설정 (완료)

**Raspberry Pi 환경**:
- IP: 192.168.0.3 (추후 192.168.0.200으로 변경 예정)
- RPICT4V3 펌웨어: V5.3.0 AVR_DB32
- Baud rate: 38400 (자동 감지)

**설치 과정**:
```bash
# lechacal 공식 패키지 설치
wget lechacal.com/RPICT/tools/lcl-rpict-package_latest.deb
sudo dpkg -i lcl-rpict-package_latest.deb

# 데이터 읽기 테스트
lcl-run
```

**RPICT 출력 형식** (lcl-run):
```
NodeID Power1 Power2 Power3 I1 I2 I3 I4 Vrms PF1 PF2
11     -50.14 0.00   0.00   0.32 0.00 0.00 0.00 242.0 0.27 0.30
```
- Power1: Alienware 전력 (음수 = CT 방향, 절대값 사용)
- Vrms: 전압 (~242V, 정상)
- I1: 전류 (A)

**이슈 해결**:
- 시리얼 출력 깨짐 → `lcl-reset-rpict.py`로 해결
- CT 센서가 Alienware 전원 케이블에 연결됨 확인

#### 2. Host 측정 스크립트 작성 (완료)

**생성된 스크립트**:
- `scripts/measurement/host_logger.py`: RAPL + nvidia-smi + CPU 사용률 로깅
- `scripts/measurement/rpict_logger.py`: RPICT 데이터 타임스탬프 로깅

**host_logger.py 기능**:
- RAPL 에너지 카운터 읽기 (package, core, dram)
- nvidia-smi GPU 전력/온도/사용률
- CPU 사용률 (/proc/stat 기반)
- 1초 간격 CSV 출력

#### 3. CPU 스트레스 테스트 (실험 ID: T-01)

**설정**:
- 워크로드: `stress-ng --cpu 0 --timeout 30s` (3회 반복)
- 측정 시간: 약 3분 (idle → stress → idle 반복)
- 동시 로깅: Host (host_logger.py) + RPICT (lcl-run)

**결과 데이터 파일**:
- `data/raw/host_stress_test.csv` (157 records)
- `data/raw/rpict_gpu_test.csv` (52 records)

**측정 결과**:

| 상태 | RPICT 실측 (W) | RAPL Package (W) | 차이 (W) | 비고 |
|------|---------------|------------------|----------|------|
| Idle | 31-35 | 2-3 | ~30 | PSU+마더보드+기타 |
| CPU 100% | 218-230 | 125-130 | ~95 | PSU 효율 ~57% |

**분석**:
1. **RPICT vs RAPL 상관관계 확인**: CPU 부하 증가 시 둘 다 비례 증가
2. **PSU 효율 추정**:
   - CPU 부하 증가분: RAPL ~123W, RPICT ~193W
   - 효율: 123/193 ≈ 64% (예상보다 낮음, 추가 분석 필요)
3. **GPU는 idle 유지**: stress-ng --gpu 미지원으로 GPU 부하 테스트 별도 필요

**타임스탬프 동기화 이슈**:
- Host: 전체 ISO 타임스탬프 (2026-02-02T00:29:30.651)
- RPICT: 시간만 (00:29:28)
- → 추후 NTP 동기화 및 날짜 포함 필요

### 다음 단계
1. RPICT 로깅에 날짜 포함
2. GPU 부하 테스트 (glmark2 또는 PyTorch)
3. VM 생성 및 베이스라인 측정
4. 라즈베리파이 고정 IP 변경 (192.168.0.200)

### 메모
- stress-ng은 GPU 옵션 미지원 (버전 문제)
- gpu-burn은 CUDA/GCC 버전 호환 문제로 컴파일 실패
- glmark2 또는 PyTorch로 GPU 부하 테스트 예정
- RPICT 측정값과 RAPL 측정값 차이가 생각보다 큼 (PSU 효율 + 기타 부품)

---

## 2026-02-05 (Day 5)

### 오늘의 목표
- [x] Phase 1 실험 환경 구축 (YOLO vs Node.js)
- [x] Host에서 가설 검증 실험 수행
- [x] 실험 결과 시각화

### 진행 상황

#### 1. 랩미팅 피드백 반영 (2/3 미팅 기반)

**핵심 방향 재설정**:
- "자원 기반 과금 ≠ 에너지 기반 과금" 가설 검증
- 마이크로벤치마크(stress-ng) 대신 실제 워크로드 사용
- Host에서 먼저 검증 → VM으로 확장

**선정 워크로드**:
- AI 워크로드: YOLOv8 Nano (부지도교수님 제안)
- Non-AI 워크로드: Node.js Express + curl 부하

#### 2. 실험 환경 구축

**Alienware 설정**:
```bash
# YOLO 환경
python3 -m venv yolo_venv
pip install ultralytics

# Node.js 환경
npm install express

# RAPL 권한 수정
sudo chmod o+r /sys/class/powercap/intel-rapl/*/energy_uj
sudo chmod o+r /sys/class/powercap/intel-rapl/*/*/energy_uj
```

**자동화 스크립트 작성**:
- `scripts/workloads/run_experiment.sh`: 4단계 자동 실험
- `scripts/workloads/server.js`: Express 서버

#### 3. Phase 1 실험 수행 (실험 ID: P1-01)

**설정**:
- 플랫폼: Host (VM 분리 없음)
- 측정: RAPL (CPU) + nvidia-smi (GPU) + RPICT (벽면 전력)
- 각 phase 60초, 1초 간격 샘플링

**실험 단계**:
| Phase | 워크로드 | 시간 |
|-------|---------|------|
| 0 | Baseline (Idle) | 30s |
| 1 | YOLO Solo | 60s |
| 2 | Node.js Solo | 60s |
| 3 | YOLO + Node.js | 60s |

**측정 결과**:

| Phase | CPU % | CPU Power (W) | GPU Power (W) | Total (W) |
|-------|-------|---------------|---------------|-----------|
| Idle | 4.0 | 5.1 ± 0.8 | 8.5 ± 0.6 | 13.5 |
| **YOLO (AI)** | 7.3 | **29.2 ± 8.3** | **36.2 ± 11.2** | **65.4** |
| **Node.js** | 4.0 | 5.6 ± 1.2 | 8.4 ± 0.5 | 14.0 |
| Concurrent | 7.4 | 29.3 ± 8.1 | 36.7 ± 11.3 | 66.0 |

**핵심 발견**:
- YOLO(AI)는 Node.js(Non-AI) 대비 **4.7배** 더 많은 전력 소비
- CPU: 5.2배 (29.2W vs 5.6W)
- GPU: 4.3배 (36.2W vs 8.4W)
- **동일 리소스 할당 시에도 에너지 소비는 크게 다름** → 가설 검증 성공

#### 4. 시각화 (완료)

생성된 그래프:
- `docs/figures/phase1/power_comparison.png`: 전력 비교 바 차트
- `docs/figures/phase1/timeseries.png`: 시계열 그래프
- `docs/figures/phase1/energy_attribution.png`: 에너지 귀속 파이 차트
- `docs/figures/phase1/key_finding.png`: 핵심 발견 그래프 (논문용)

### 이슈 및 해결

| ID | 이슈 | 상태 | 해결 |
|----|-----|------|------|
| I-04 | RAPL 권한 문제 (0.00W) | 해결 | chmod o+r 권한 부여 |
| I-05 | lcl-run Python subprocess 실패 | 해결 | shell=True 사용 |
| I-06 | vm-power-exp / vm-power-attribution 폴더 이원화 | 해결 | git repo로 통일 |

### 다음 단계
1. VM 분리 환경 구축 (KVM)
2. cgroup v2 기반 프로세스별 리소스 측정
3. 교수님께 중간 결과 이메일 보고
4. 논문 구조 초안 작성

### 메모
- VM 분리 없이 Host에서도 핵심 가설 검증 완료
- RAPL core/dram은 0W로 표시됨 (i7-11700KF 특성? 추가 조사 필요)
- Node.js는 curl 부하에도 GPU를 거의 사용하지 않음 (예상대로)
- YOLO는 짧은 비디오 반복 추론으로 GPU 사용률 변동 큼 (30-50W)

---

## Template: 새 실험 기록용

```markdown
## YYYY-MM-DD (Day N)

### 오늘의 목표
- [ ] 목표 1
- [ ] 목표 2

### 진행 상황

#### 1. 작업 제목
내용 설명

```bash
# 실행한 명령어
```

결과:
- 항목 1
- 항목 2

#### 2. 실험 수행 (실험 ID: X-XX)

**설정**:
- VM 구성:
- 워크로드:
- 측정 시간:

**결과**:
| 메트릭 | 값 |
|-------|-----|
| RPICT 평균 전력 | XX W |
| RAPL 평균 전력 | XX W |
| GPU 평균 전력 | XX W |

**분석**:
관찰 내용...

**문제점**:
발생한 이슈...

**해결**:
해결 방법...

### 다음 단계
1. 할 일 1
2. 할 일 2

### 메모
추가 노트...
```

---

## 실험 결과 요약 테이블

| 날짜 | 실험 ID | 시나리오 | RPICT (W) | RAPL (W) | GPU (W) | 비고 |
|-----|---------|---------|-----------|----------|---------|------|
| 2026-02-02 | T-01 | Host idle (no VM) | 31-35 | 2-3 | 6.5 | 베이스라인 |
| 2026-02-02 | T-01 | CPU stress (stress-ng) | 218-230 | 125-130 | 6.5 | CPU 풀로드 |
| 2026-02-05 | P1-01 | YOLO solo (Host) | ~100-140 | 29.2 | 36.2 | AI 워크로드 |
| 2026-02-05 | P1-01 | Node.js solo (Host) | ~35-40 | 5.6 | 8.4 | Non-AI 워크로드 |
| 2026-02-05 | P1-01 | YOLO + Node.js (Host) | ~100-140 | 29.3 | 36.7 | 동시 실행 |

---

## 이슈 트래킹

| ID | 날짜 | 이슈 | 상태 | 해결 방법 |
|----|-----|------|------|----------|
| I-01 | 2026-02-02 | lcl-run 출력 깨짐 | 해결 | lcl-reset-rpict.py 실행 |
| I-02 | 2026-02-02 | RPICT baud rate 혼동 (9600 vs 38400) | 해결 | lcl-run이 자동 감지 |
| I-03 | 2026-02-02 | gpu-burn 컴파일 실패 | 미해결 | CUDA/GCC 버전 불일치, 대안 사용 |
