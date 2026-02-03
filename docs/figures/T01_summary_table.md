# T-01 Experiment Summary

**Experiment**: CPU Stress Test (stress-ng --cpu 0 --timeout 30s × 3)

**Date**: 2026-02-02

## Results

| State             | RAPL Package (W)   | RAPL Core (W)   | GPU (W)     | RPICT Wall (W)   | CPU Usage (%)   | Samples   |
|:------------------|:-------------------|:----------------|:------------|:-----------------|:----------------|:----------|
| Idle              | 2.99 ± 0.99        | 0.64 ± 0.87     | 6.81 ± 0.25 | 32.89 ± 1.64     | 0.3             | 70 / 21   |
| CPU 100%          | 127.05 ± 2.17      | 122.70 ± 2.13   | 6.77 ± 0.15 | 224.04 ± 5.23    | 100.0           | 83 / 29   |
| Δ (Stress - Idle) | +124.06            | +122.07         | +-0.05      | +191.15          | -               | -         |
| Efficiency        | 64.9%              | -               | -           | (baseline)       | -               | -         |

## Key Findings

1. **RAPL-RPICT Correlation**: RAPL 전력과 실측 전력(RPICT) 간 강한 선형 상관관계 (효율 분석 그래프 참조)
2. **Power Efficiency**: RAPL 증가분 / RPICT 증가분 = 64.9%
   - RAPL은 CPU 패키지 전력만 측정, RPICT는 전체 시스템 전력 측정
3. **Gap Analysis**: 67.1W의 차이 = PSU 손실 + VRM + 팬 + 마더보드 등
4. **GPU**: 이 테스트에서는 Idle 상태 유지 (~6.8W)
