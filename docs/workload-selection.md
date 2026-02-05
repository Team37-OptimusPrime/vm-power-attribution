# 워크로드 선정 (Workload Selection)

> 최종 수정: 2026-02-03
> 근거: Lab Meeting 피드백 + 관련 논문 조사

---

## 1. 선정 기준

교수님 피드백:
- stress-ng 같은 마이크로벤치마크는 논문에 부적절
- **유명한 실제 애플리케이션** 사용 (레퍼런스 하나만 달면 설명 불필요)
- **에너지 패턴이 확연히 다른** 2종류:
  - AI/GPU-heavy: GPU 많이 사용, 에너지 많이 소모
  - 전통적/light: 자원 할당은 하지만 이용률 낮음

---

## 2. 워크로드 A: AI/GPU-Heavy

### ResNet-50 v1.5 Inference (PyTorch)

**선정 이유:**
- **MLPerf Inference**의 표준 벤치마크 모델 (업계 최고 권위)
- 논문에서 추가 설명 불필요 → "MLPerf Inference의 ResNet-50을 사용했다" 한 줄로 충분
- RTX 3060 12GB에서 충분히 실행 가능 (모델 크기 ~100MB)
- GPU를 80-99% 활용하며 명확한 에너지 시그널 생성
- NVIDIA 공식 벤치마크 스크립트 제공

**예상 에너지 프로파일:**
- GPU: 100-150W (RTX 3060 TDP 170W)
- CPU: 40-60W (데이터 피딩)
- 총 Wall Power: ~200-250W

**실행 방법:**
```bash
# 방법 1: 직접 PyTorch inference loop
pip install torch torchvision
python resnet50_inference.py --batch-size 64 --iterations 10000

# 방법 2: NVIDIA DeepLearningExamples
git clone https://github.com/NVIDIA/DeepLearningExamples
cd PyTorch/Classification/ConvNets
python main.py --arch resnet50 --evaluate --epochs 1 --synthetic-data
```

**인용:**
- Reddi et al., "MLPerf Inference Benchmark," ISCA 2020
- MLPerf Power, arXiv:2410.12032, HPCA 2025

### 대안: BERT-Large Inference (SQuAD)
- Transformer 기반 언어 모델 → CNN과 다른 연산 패턴
- MLPerf Inference 표준 워크로드
- RTX 3060 12GB에서 실행 가능 (~1.3GB)

---

## 3. 워크로드 B: 전통적/Light

### NGINX 웹서버 + wrk (저부하 요청)

**선정 이유:**
- NGINX = 세계에서 가장 많이 배포된 웹서버
- CloudSuite Web Serving (ASPLOS 2012)의 표준 벤치마크
- 낮은/안정적인 CPU 이용률 → 자원 할당 대비 실제 사용이 적은 전형적 사례
- VM 내 설치 및 실행이 매우 간단

**예상 에너지 프로파일:**
- GPU: ~7W (idle)
- CPU: 5-15% → 10-30W
- 총 Wall Power: ~50-80W

**실행 방법:**
```bash
# VM 내부
sudo apt install nginx
# 정적 페이지 제공 설정

# 부하 생성 (호스트 또는 다른 VM에서)
# 저부하: ~100 req/s, CPU 5-15% 유지
wrk -t2 -c10 -d300s http://<vm-ip>/index.html
```

**인용:**
- Ferdman et al., "Clearing the Clouds," ASPLOS 2012 (CloudSuite)

### 대안: Redis + redis-benchmark
- 인메모리 키-밸류 스토어
- CPU 효율 매우 높음 (싱글스레드 이벤트 루프)
- 저-중 부하에서 CPU 5-20%

---

## 4. 비교 요약

| 속성 | ResNet-50 (GPU) | NGINX (CPU-light) |
|------|----------------|-------------------|
| 타입 | AI/GPU 집약적 | 전통적 웹서비스 |
| 주 리소스 | GPU (RTX 3060) | CPU (1-2코어) |
| GPU 전력 | 100-150W | ~7W (idle) |
| CPU 전력 | 40-60W | 10-30W |
| GPU 이용률 | 80-99% | 0% |
| CPU 이용률 | 20-40% | 5-15% |
| VM 실행 | GPU passthrough 필요 | 표준 VM |
| 설치 난이도 | 중간 (CUDA 설치) | 낮음 (apt install) |

**핵심 시나리오:**
```
동일 자원 할당: VM_A = VM_B = (4 vCPU, 8GB RAM, GPU share)

VM_A (ResNet-50): 에너지 ~200W  →  에너지 비용 ~80%
VM_B (NGINX):     에너지 ~50W   →  에너지 비용 ~20%

자원 기반 과금:   50% vs 50%  (동일)
에너지 기반 과금: 80% vs 20%  (4배 차이!)
```

---

## 5. 참고 논문

### VM 전력 귀속 분야
1. Krishnan et al., "VM Power Metering: Feasibility and Challenges," GreenMetrics/SIGMETRICS 2010
2. Kansal et al., "Virtual Machine Power Metering and Provisioning," ACM SoCC 2010
3. Luo et al., "VPower: Metering Power Consumption of VM," IEEE 2013

### AI 에너지 벤치마크
4. MLPerf Power, "Benchmarking the Energy Efficiency of ML Systems," arXiv:2410.12032, HPCA 2025
5. Reddi et al., "MLPerf Inference Benchmark," ISCA 2020

### 클라우드 벤치마크
6. Ferdman et al., "Clearing the Clouds," ASPLOS 2012 (CloudSuite)
7. Barroso & Holzle, "The Case for Energy-Proportional Computing," IEEE Computer 2007

### RAPL 검증
8. Desrochers et al., "A Validation of DRAM RAPL Power Measurements," ACM TOMPECS 2018

### 컨테이너 에너지
9. Kepler (CNCF) - eBPF 기반 전력 모니터링
10. Pijnacker, "Container-level Energy Observability in Kubernetes," arXiv:2504.10702, 2025

---

## 6. 다음 단계

- [ ] Host에서 ResNet-50 inference 사전 테스트 (에너지 프로파일 확인)
- [ ] VM에서 NGINX + wrk 사전 테스트
- [ ] 두 워크로드의 에너지 차이가 명확한지 확인
- [ ] GPU passthrough 설정 (VT-d, vfio-pci)
