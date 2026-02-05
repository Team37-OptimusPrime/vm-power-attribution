# VM-level Power Attribution in Multi-tenant Environments

> 소주제 2: 여러 VM 동시 실행 시 전력 귀속 연구
> Team 37 - OptimusPrime

## 연구 목표

멀티 테넌트 환경에서 동시 실행되는 VM들의 전력 간섭 효과를 측정하고,
각 VM별 전력 소비량을 공정하게 귀속시키는 알고리즘 개발

**핵심 가설**: 리소스 기반 과금 ≠ 에너지 기반 과금

## 주요 결과 (Phase 1.5)

동일 리소스(2코어, 4GB) 할당 시 전력 소비 비교:

| 워크로드 | Wall Power | Delta |
|----------|-----------|-------|
| YOLO (AI) | 114.5W | +77W |
| Node.js (Non-AI) | 42.0W | +4W |

**결론**: 동일 리소스 할당에도 전력 소비 **2.7배** 차이 (Delta 18.3배)

## Directory Structure

```
vm-power-attribution/
├── README.md                 # 프로젝트 개요
├── CHANGELOG.md              # 버전 히스토리 & 실험 로그
├── requirements.txt          # Python 의존성
│
├── configs/                  # 설정 파일
├── data/raw/                 # 실험 데이터 (git 제외)
│   ├── phase1/
│   ├── phase1.5/
│   └── rpict/
│
├── docs/                     # 문서
│   ├── experiments/          # 실험 설계
│   ├── setup.md              # 설치 가이드
│   └── references.md         # 참고 자료
│
├── reports/                  # 보고서 & 시각화
│   ├── phase1/
│   └── phase1.5/
│
├── scripts/
│   ├── analysis/             # 분석 스크립트
│   ├── measurement/          # 측정 스크립트
│   └── workloads/            # 워크로드 스크립트
│
└── logs/                     # 이슈 트래킹 & 회의록
    ├── ISSUES.md
    └── meetings/
```

## Documentation

| 문서 | 설명 |
|-----|------|
| [CHANGELOG.md](CHANGELOG.md) | 실험 로그 & 변경 이력 |
| [logs/ISSUES.md](logs/ISSUES.md) | 이슈 트래킹 |
| [docs/setup.md](docs/setup.md) | 환경 설정 가이드 |
| [docs/experiments/](docs/experiments/) | 실험 설계 문서 |
| [reports/phase1.5/](reports/phase1.5/) | Phase 1.5 결과 보고서 |

## Quick Start

```bash
# 1. Python 환경 설정
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. 측정 스크립트 실행 (Alienware)
python scripts/measurement/host_logger.py -o data.csv -d 60

# 3. 분석 실행
python scripts/analysis/phase1_5_analysis.py
```

## Hardware

- **Host**: Alienware Aurora R12 (Intel i7-11700F, RTX 3060)
- **Power Meter**: RPICT4V3 + Raspberry Pi
- **Virtualization**: KVM/QEMU + libvirt

## Progress

- [x] Phase 1: Host 레벨 AI vs Non-AI 전력 비교
- [x] Phase 1.5: cgroup 기반 응용별 전력 측정
- [ ] Phase 2: VM 환경 전력 귀속
- [ ] Phase 3: 에너지 기반 과금 모델
