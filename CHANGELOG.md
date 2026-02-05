# Changelog & Experiment Log

프로젝트 변경 이력 및 실험 기록

---

## [Phase 1.5] - 2026-02-06

### 실험: cgroup 기반 응용별 전력 측정

**실험 ID**: P1.5-02 (test2)

**설정**:
- cgroup v2로 YOLO/Node.js 분리 (각 2코어, 4GB)
- RPICT CT 센서로 벽면 전력 측정
- Intel RAPL + nvidia-smi로 내부 전력 측정

**결과**:
| Phase | Wall Power | RAPL | GPU |
|-------|-----------|------|-----|
| Idle | 37.8W | 5.5W | 8.4W |
| YOLO Solo | **114.5W** | 31.9W | 37.4W |
| Node.js Solo | **42.0W** | 7.5W | 8.4W |
| Concurrent | 115.7W | 31.8W | 36.2W |

**핵심 발견**:
- 동일 리소스(2코어, 4GB) 할당 → 전력 2.7배 차이
- Delta 기준: 18.3배 차이 (YOLO +77W vs Node.js +4W)
- 가설 입증: "리소스 기반 과금 ≠ 에너지 기반 과금"

**해결된 이슈**:
- ISSUE-001: YOLO cgroup 미할당 → systemd-run으로 해결

---

## [Phase 1] - 2026-02-05

### 실험: Host 레벨 AI vs Non-AI 전력 비교

**실험 ID**: P1-01

**설정**:
- Host 직접 실행 (VM 분리 없음)
- YOLO: YOLOv8 Nano 객체 탐지
- Node.js: Express + curl 부하

**결과**:
| Phase | CPU Power | GPU Power | Total |
|-------|-----------|-----------|-------|
| Idle | 5.1W | 8.5W | 13.5W |
| YOLO | 29.2W | 36.2W | 65.4W |
| Node.js | 5.6W | 8.4W | 14.0W |

**핵심 발견**:
- YOLO는 Node.js 대비 4.7배 전력 소비
- GPU가 핵심 차별 요소 (4.3배 차이)

---

## [Infrastructure] - 2026-02-02

### RPICT 시스템 설정

- Raspberry Pi에 RPICT4V3 CT 센서 연결
- lcl-run으로 실시간 전력 모니터링
- 데이터 형식: NodeID, Power1~3, I1~4, Vrms, PF1~2

### Host 측정 스크립트 작성

- `host_logger.py`: RAPL + nvidia-smi + CPU 사용률
- `rpict_logger.py`: RPICT 타임스탬프 로깅

### 첫 번째 테스트 (T-01)

- stress-ng CPU 스트레스 테스트
- Idle: 31-35W, CPU 100%: 218-230W

---

## [Project Setup] - 2026-02-01

### 초기 설정

- 프로젝트 구조 생성
- 문서화 체계 구축
- 원격 서버 (Alienware) 환경 확인:
  - KVM/QEMU, libvirt 8.0.0
  - CUDA 12.8, nvidia-smi
  - Intel RAPL 접근 가능

---

## 실험 결과 요약

| 날짜 | 실험 ID | 시나리오 | Wall (W) | RAPL (W) | GPU (W) |
|-----|---------|---------|----------|----------|---------|
| 02-02 | T-01 | Idle | 31-35 | 2-3 | 6.5 |
| 02-02 | T-01 | CPU stress | 218-230 | 125-130 | 6.5 |
| 02-05 | P1-01 | YOLO solo | 100-140 | 29.2 | 36.2 |
| 02-05 | P1-01 | Node.js solo | 35-40 | 5.6 | 8.4 |
| 02-06 | P1.5-02 | YOLO solo (cgroup) | 114.5 | 31.9 | 37.4 |
| 02-06 | P1.5-02 | Node.js solo (cgroup) | 42.0 | 7.5 | 8.4 |
| 02-06 | P1.5-02 | Concurrent (cgroup) | 115.7 | 31.8 | 36.2 |
