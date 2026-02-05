# References

> 관련 연구 및 참고 자료

---

## 1. VM Energy Measurement

### 1.1 RAPL 기반 측정

- **Intel RAPL Documentation**
  - Running Average Power Limit (RAPL) interface
  - `/sys/class/powercap/intel-rapl/`
  - Domains: Package, Core, Uncore, DRAM

- Khan, K. N., et al. (2018). "RAPL in Action: Experiences in Using RAPL for Power Measurements"
  - RAPL 정확도 분석
  - 실제 전력 측정과의 비교

### 1.2 VM 레벨 전력 추정

- Kansal, A., et al. (2010). "Virtual Machine Power Metering and Provisioning"
  - Joulemeter: VM 전력 추정 모델
  - CPU, 디스크, 메모리 전력 모델링

- Dhiman, G., et al. (2010). "vGreen: A System for Energy-Efficient Computing in Virtualized Environments"
  - VM 레벨 에너지 관리
  - 전력 인식 스케줄링

### 1.3 클라우드 에너지 측정

- Hsu, C. H., et al. (2011). "Power Management for Cloud Computing"
  - 데이터센터 전력 관리 개요
  - 가상화 환경 고려사항

---

## 2. Performance Interference in VMs

### 2.1 리소스 경합 분석

- Mars, J., et al. (2011). "Bubble-Up: Increasing Utilization in Modern Warehouse Scale Computers via Sensible Co-locations"
  - 워크로드 간섭 측정
  - 안전한 동시 배치 전략

- Kambadur, M., et al. (2012). "Measuring Interference Between Live Datacenter Applications"
  - 실제 데이터센터 간섭 측정
  - 성능 저하 정량화

### 2.2 캐시/메모리 경합

- Nathuji, R., et al. (2010). "Q-Clouds: Managing Performance Interference Effects for QoS-Aware Clouds"
  - 성능 간섭 모델
  - QoS 기반 리소스 할당

---

## 3. Fair Resource Attribution

### 3.1 Shapley Value

- Shapley, L. S. (1953). "A Value for n-Person Games"
  - 게임 이론 기반 공정 분배
  - 원본 논문

- Jain, R., et al. (1984). "A Quantitative Measure of Fairness"
  - Jain's Fairness Index
  - 자원 분배 공정성 측정

### 3.2 클라우드 빌링 모델

- Liu, H., et al. (2011). "GreenCloud: A New Architecture for Green Data Center"
  - 에너지 기반 빌링 제안
  - 그린 데이터센터 아키텍처

---

## 4. Physical Power Measurement

### 4.1 측정 장비

- **RPICT (Raspberry Pi Current Transformer)**
  - <https://lechacalshop.com/>
  - CT 센서 기반 AC 전력 측정
  - Open source 하드웨어

- **WattsUp Pro**
  - 상용 전력 측정기
  - USB 인터페이스

### 4.2 측정 방법론

- Hackenberg, D., et al. (2013). "Power Measurement Techniques on Standard Compute Nodes: A Quantitative Comparison"
  - 다양한 전력 측정 방법 비교
  - 정확도 분석

---

## 5. GPU Power Measurement

### 5.1 NVIDIA 관련

- **nvidia-smi Documentation**
  - `nvidia-smi --query-gpu=power.draw --format=csv`
  - 실시간 GPU 전력 쿼리

- **NVML (NVIDIA Management Library)**
  - Python: pynvml
  - C: nvml.h

### 5.2 GPU 전력 모델

- Hong, S., et al. (2010). "An Integrated GPU Power and Performance Model"
  - GPU 전력 예측 모델
  - 커널 특성 기반 추정

---

## 6. AI Workload Power Characteristics

### 6.1 딥러닝 학습

- Strubell, E., et al. (2019). "Energy and Policy Considerations for Deep Learning in NLP"
  - 대규모 모델 학습 에너지 비용
  - 환경적 영향

- Patterson, D., et al. (2021). "Carbon Emissions and Large Neural Network Training"
  - 탄소 발자국 분석
  - 효율적 학습 전략

### 6.2 추론 최적화

- Chen, T., et al. (2018). "TVM: An Automated End-to-End Optimizing Compiler for Deep Learning"
  - 추론 최적화
  - 에너지 효율 개선

---

## 7. 도구 및 라이브러리

### 7.1 Python 패키지

| 패키지 | 용도 | 문서 |
|-------|------|-----|
| psutil | 시스템 모니터링 | <https://psutil.readthedocs.io/> |
| pynvml | NVIDIA GPU 관리 | <https://pypi.org/project/pynvml/> |
| libvirt-python | VM 관리 | <https://libvirt.org/python.html> |
| pyserial | 시리얼 통신 | <https://pythonhosted.org/pyserial/> |

### 7.2 Linux 도구

| 도구 | 용도 | 명령어 예시 |
|-----|------|------------|
| perf | 성능 카운터 | `perf stat -e power/energy-pkg/` |
| powerstat | CPU 전력 | `powerstat -R 1 60` |
| turbostat | CPU 상태 | `turbostat --interval 1` |

---

## 8. 관련 데이터셋

- **Google Cluster Trace**
  - <https://github.com/google/cluster-data>
  - 대규모 클러스터 워크로드 데이터

- **Azure Public Dataset**
  - VM 배치 및 리소스 사용 데이터

---

## 읽을 논문 목록 (To-Read)

- [ ] Lim, H., et al. "A Study on VM Power Metering" (찾아볼 것)
- [ ] 최신 ISCA/ASPLOS/MICRO 논문 중 VM energy 관련
- [ ] MLSys 2024-2025 energy-aware ML 논문

---

## 변경 이력

| 날짜 | 변경 내용 | 작성자 |
|-----|----------|-------|
| 2026-02-01 | 최초 작성 | Woorim Shin |
