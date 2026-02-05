# Phase 1.5 실험 결과 보고

**Date**: 2026-02-06 <br>
**Subject**: VM Power Attribution 연구 - Phase 1.5 실험 결과

---

## 요약

cgroup v2 기반 리소스 분리 실험을 완료하였음

**핵심 결과**: 동일한 리소스(2코어, 4GB RAM)를 할당받은 두 워크로드가 **2.7배~18배** 다른 전력을 소비함을 확인하였습니다.

| 워크로드 | 할당 리소스 | 벽면 전력 | Idle 대비 증가 |
|----------|------------|----------|---------------|
| YOLO (AI) | 2코어, 4GB | **114.5W** | +76.7W |
| Node.js (Non-AI) | 2코어, 4GB | **42.0W** | +4.2W |

이 결과는 **"리소스 기반 과금 ≠ 에너지 기반 과금"** 가설을 입증합니다.

---

## 요구사항 충족 현황

| 요구사항 | 상태 | 비고 |
|---------|------|------|
| 동일 CPU/메모리 할당 | ✅ 완료 | cgroup v2로 2코어, 4GB 동일 할당 |
| Total Power 측정 | ✅ 완료 | RPICT CT 센서 (벽면 전력) |
| CPU Power 측정 | ✅ 완료 | Intel RAPL |
| GPU Power 측정 | ✅ 완료 | nvidia-smi |
| cgroup 분리 | ✅ 완료 | yolo.slice, nodejs.slice |
| vmstat 스타일 IO 측정 | ✅ 완료 | cgroup io.stat 기반 측정 |
| 동시 실행 실험 | ✅ 완료 | Concurrent phase 포함 |

---

## 실험 구성

### 하드웨어

- **Host**: Alienware Aurora R12 (Intel i7-11700F, 32GB RAM)
- **GPU**: NVIDIA RTX 3060
- **전력 측정**: RPICT4V3 CT 센서 (Raspberry Pi 연결)

### cgroup 설정

```
yolo.slice:
  - cpuset.cpus: 0-1 (2코어)
  - cpu.max: 200000/100000 (200%)
  - memory.max: 4GB

nodejs.slice:
  - cpuset.cpus: 2-3 (2코어)
  - cpu.max: 200000/100000 (200%)
  - memory.max: 4GB
```

### 워크로드

- **AI**: YOLOv8 Nano 객체 탐지 (GPU 가속)
- **Non-AI**: Node.js Express + curl 부하 생성

---

## 주요 결과

### 1. 전력 비교 (첨부: power_comparison.png)

| Phase | Wall Power | CPU (RAPL) | GPU |
|-------|-----------|------------|-----|
| Idle | 37.8W | 5.5W | 8.4W |
| YOLO Solo | **114.5W** | 31.9W | 37.4W |
| Node.js Solo | **42.0W** | 7.5W | 8.4W |
| Concurrent | 115.7W | 31.8W | 36.2W |

### 2. 핵심 발견 (첨부: resource_vs_energy_key_finding.png)

**동일 리소스 할당 → 전혀 다른 전력 소비**

- YOLO: 114W (Idle 대비 +77W)
- Node.js: 42W (Idle 대비 +4W)
- **전력 비율: 2.7x (델타 비율: 18.3x)**

### 3. cgroup 추적 성공 (첨부: cgroup_tracking.png)

| Phase | YOLO CPU | Node.js CPU |
|-------|----------|-------------|
| YOLO Solo | 95.6% | 0% |
| Node.js Solo | 0% | 17.4% |
| Concurrent | 91.0% | 13.7% |

---

## 결론 및 의의

### 1. 가설 입증

리소스 할당량(CPU 코어, 메모리)은 에너지 소비를 예측하지 못합니다.
동일한 리소스를 할당받아도 워크로드 특성에 따라 전력 소비가 크게 달라집니다.

### 2. GPU가 핵심 차별 요소

- YOLO: GPU 38-42% 활용 → 30-51W
- Node.js: GPU 5-7% (idle) → ~8W
- GPU만으로 약 40W 차이 발생

### 3. 현행 클라우드 과금의 불공정성

현재 리소스 기반 과금 모델에서는 에너지 효율적인 워크로드(Node.js)가
에너지 집약적 워크로드(YOLO)의 전력 비용을 보조하는 구조입니다.

---

## 향후 계획

1. **Phase 2**: VM 환경에서 동일 실험 재현
2. **에너지 과금 모델 설계**: 측정 데이터 기반 공정한 과금 알고리즘 개발
3. **논문 초안 작성**: 실험 결과 기반 학술 논문 준비

---

## 첨부 파일

1. `power_comparison.png` - 전력 비교 그래프
2. `resource_vs_energy_key_finding.png` - 핵심 발견 시각화
3. `cgroup_tracking.png` - cgroup 추적 결과
4. `wall_power_timeline.png` - 실험 타임라인
5. `energy_breakdown.png` - 전력 구성 요소 분석
6. `billing_comparison.png` - 과금 모델 비교
7. `phase1.5_report.md` - 상세 실험 보고서
