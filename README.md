# VM-level Power Attribution in Multi-tenant Environments

> 소주제 2: 여러 VM 동시 실행 시 전력 귀속 연구  
> Team 37 - OptimusPrime

## 연구 목표
멀티 테넌트 환경에서 동시 실행되는 VM들의 전력 간섭 효과를 측정하고,  
각 VM별 전력 소비량을 공정하게 귀속시키는 알고리즘 개발

## Directory Structure
```
vm-power-attribution/
├── docs/              # 실험 계획, 미팅 노트
├── scripts/           # 측정 및 워크로드 스크립트
├── data/              # 실험 데이터 (git 추적 X)
├── analysis/          # 데이터 분석 및 시각화
└── configs/           # VM 및 실험 설정
```

## Documentation

| 문서 | 설명 |
|-----|------|
| [docs/setup.md](docs/setup.md) | 환경 설정 가이드 |
| [docs/experiment-plan.md](docs/experiment-plan.md) | 실험 설계 문서 |
| [docs/experiment-log.md](docs/experiment-log.md) | 실험 수행 일지 |
| [docs/references.md](docs/references.md) | 참고 문헌 |
| [docs/troubleshooting.md](docs/troubleshooting.md) | 문제 해결 가이드 |

## Quick Start

```bash
# 1. Python 환경 설정
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. 상세 설정은 docs/setup.md 참조
```

## Hardware

- **Host**: Alienware Aurora R12 (i7-11700KF, RTX 3060)
- **Power Meter**: RPICT4V3 + Raspberry Pi
- **Virtualization**: KVM/QEMU + libvirt
