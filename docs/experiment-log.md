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
| - | - | - | - | - | - | 데이터 수집 전 |

---

## 이슈 트래킹

| ID | 날짜 | 이슈 | 상태 | 해결 방법 |
|----|-----|------|------|----------|
| - | - | - | - | - |
