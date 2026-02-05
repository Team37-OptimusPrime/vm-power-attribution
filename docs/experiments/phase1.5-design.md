# Phase 1.5 실험 설계: cgroup 기반 응용별 리소스 분리 측정

> 교수님 요구사항 완전 충족을 위한 보완 실험

---

## 1. 실험 목적

Phase 1에서 누락된 항목을 보완하여 **cgroup v2 기반 응용별 리소스 분리 측정** 수행:

1. 동일한 CPU/메모리 자원 할당 하에서 AI vs Non-AI 전력 차이 정량화
2. 동시 실행 시 응용별 CPU/IO 사용량 개별 측정
3. vmstat 수준의 IO 측정 데이터 확보

---

## 2. 실험 환경

### 2.1 하드웨어
- **Host**: Alienware (Intel i7-11700KF 8C/16T, 32GB RAM, RTX 3070)
- **전력 측정**: RPICT4V3 (벽면), RAPL (CPU), nvidia-smi (GPU)

### 2.2 cgroup v2 리소스 할당

| 응용 | CPU 코어 | CPU 쿼터 | 메모리 | 비고 |
|-----|---------|----------|--------|------|
| YOLO (yolo.slice) | 0-1 (2코어) | 200% | 4GB | AI 워크로드 |
| Node.js (nodejs.slice) | 2-3 (2코어) | 200% | 4GB | Non-AI 워크로드 |

### 2.3 측정 항목

| 카테고리 | 측정 항목 | 소스 | 단위 |
|---------|----------|------|------|
| 전력 | 벽면 전력 | RPICT | W |
| 전력 | CPU 패키지 전력 | RAPL | W |
| 전력 | GPU 전력 | nvidia-smi | W |
| CPU | 전체 사용률 | /proc/stat | % |
| CPU | 응용별 사용률 | cgroup cpu.stat | μs |
| 메모리 | 응용별 사용량 | cgroup memory.current | bytes |
| IO | 응용별 read/write | cgroup io.stat | bytes |
| IO | 시스템 전체 | /proc/diskstats | KB/s |
| GPU | 사용률 | nvidia-smi | % |
| GPU | 메모리 사용량 | nvidia-smi | MB |

---

## 3. 실험 단계

### Phase 0: Baseline (30초)
- 워크로드 없음, Idle 상태
- 모든 메트릭 측정

### Phase 1: YOLO Solo (60초)
- yolo.slice cgroup에서 YOLO 실행
- Node.js 미실행

### Phase 2: Node.js Solo (60초)
- nodejs.slice cgroup에서 Node.js + curl 부하 실행
- YOLO 미실행

### Phase 3: Concurrent (60초)
- 두 응용 동시 실행 (각자의 cgroup에서)
- 응용별 리소스 사용량 개별 측정

### Phase 4: Cooldown (30초)
- 모든 워크로드 종료
- 시스템 안정화

---

## 4. cgroup v2 설정

### 4.1 cgroup 구조
```
/sys/fs/cgroup/
├── yolo.slice/
│   ├── cgroup.controllers    # cpu memory io
│   ├── cpu.max               # 200000 100000 (200%)
│   ├── cpuset.cpus           # 0-1
│   ├── memory.max            # 4294967296 (4GB)
│   ├── cpu.stat              # 사용량 통계
│   ├── memory.current        # 현재 메모리
│   └── io.stat               # IO 통계
└── nodejs.slice/
    ├── (동일 구조)
    └── cpuset.cpus           # 2-3
```

### 4.2 설정 명령어
```bash
# cgroup 생성
sudo mkdir -p /sys/fs/cgroup/yolo.slice
sudo mkdir -p /sys/fs/cgroup/nodejs.slice

# 컨트롤러 활성화
echo "+cpu +memory +io +cpuset" | sudo tee /sys/fs/cgroup/cgroup.subtree_control

# YOLO cgroup 설정
echo "0-1" | sudo tee /sys/fs/cgroup/yolo.slice/cpuset.cpus
echo "200000 100000" | sudo tee /sys/fs/cgroup/yolo.slice/cpu.max
echo "4294967296" | sudo tee /sys/fs/cgroup/yolo.slice/memory.max

# Node.js cgroup 설정
echo "2-3" | sudo tee /sys/fs/cgroup/nodejs.slice/cpuset.cpus
echo "200000 100000" | sudo tee /sys/fs/cgroup/nodejs.slice/cpu.max
echo "4294967296" | sudo tee /sys/fs/cgroup/nodejs.slice/memory.max
```

### 4.3 프로세스를 cgroup에 할당
```bash
# 현재 쉘의 PID를 cgroup에 할당
echo $$ | sudo tee /sys/fs/cgroup/yolo.slice/cgroup.procs

# 또는 cgexec 사용 (libcgroup 필요)
sudo cgexec -g cpu,memory,io:yolo.slice python3 yolo_inference.py
```

---

## 5. 측정 스크립트 구조

### 5.1 파일 구성
```
scripts/
├── measurement/
│   ├── host_logger.py          # 기존 (RAPL, nvidia-smi, CPU%)
│   ├── cgroup_logger.py        # 신규: cgroup별 리소스 측정
│   └── rpict_logger.py         # 기존 (벽면 전력)
├── workloads/
│   ├── setup_cgroups.sh        # 신규: cgroup 생성/설정
│   ├── run_experiment_v3.sh    # 신규: Phase 1.5 실험 스크립트
│   └── ...
```

### 5.2 출력 CSV 형식

**cgroup_logger.py 출력:**
```csv
timestamp,cgroup,cpu_usage_us,memory_bytes,io_read_bytes,io_write_bytes
2026-02-06T10:00:00.000,yolo.slice,1234567,2147483648,1048576,524288
2026-02-06T10:00:00.000,nodejs.slice,567890,1073741824,524288,262144
```

---

## 6. 예상 결과

### 6.1 Solo 실행 비교
| 메트릭 | YOLO (예상) | Node.js (예상) | 비율 |
|-------|------------|----------------|------|
| CPU 전력 | 25-35W | 8-12W | ~3x |
| GPU 전력 | 30-50W | 8-10W | ~4x |
| 총 전력 | 55-85W | 16-22W | ~3.5x |
| cgroup CPU 사용률 | 180-200% | 50-100% | ~2x |

### 6.2 Concurrent 실행 시
- 각 응용이 자신의 cgroup 제한 내에서 실행
- 전체 전력 = YOLO 전력 + Node.js 전력 + 오버헤드
- 오버헤드가 10% 이내면 정상 (간섭 최소화 확인)

---

## 7. 성공 기준

1. **cgroup 분리 작동 확인**: 각 응용이 지정된 코어에서만 실행
2. **응용별 측정 가능**: cgroup 통계로 개별 리소스 사용량 추출
3. **전력 차이 재확인**: Phase 1과 유사한 비율 (3-5배 차이)
4. **동시 실행 오버헤드 확인**: 단독 실행 대비 1.5배 미만 성능 저하

---

## 8. 실험 체크리스트

### 사전 준비
- [ ] Alienware cgroup v2 활성화 확인
- [ ] setup_cgroups.sh 실행 및 설정 확인
- [ ] cgroup_logger.py 테스트
- [ ] RPICT 라즈베리파이 NTP 동기화
- [ ] 디스크 여유 공간 확인 (>10GB)

### 실험 실행
- [ ] tmux 세션에서 실행 (SSH 끊김 방지)
- [ ] RPICT 로깅 동시 시작
- [ ] run_experiment_v3.sh 실행
- [ ] 중간 로그 확인

### 사후 처리
- [ ] 데이터 파일 검증 (gap 없음)
- [ ] 타임스탬프 정렬
- [ ] 분석 스크립트 실행
- [ ] 결과 시각화

---

## 변경 이력

| 날짜 | 변경 내용 | 작성자 |
|-----|----------|-------|
| 2026-02-06 | 최초 작성 | Claude |
