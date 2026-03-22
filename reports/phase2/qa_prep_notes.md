# 교수님 예상 질문 대비: cgroup v2 및 워크로드 특징

## 1. cgroup v2 란?

**"리눅스 커널이 프로세스들을 그룹화하여 자원(CPU, 메모리, I/O)을 제어하고 격리하는 기능"**입니다.

* **Version 2의 차이점**: v1과 달리 "계층 구조가 통합"되어 관리가 쉽고, 특히 **"Buffered I/O (Writeback)에 대한 정확한 추적"**이 가능해졌습니다. 덕분에 우리가 실험한 파일 쓰기 작업(IO)이 어느 그룹에서 발생했는지 정확히 측정할 수 있었습니다.
* **우리 실험에서의 역할**:
  * `yolo.slice`: 0-1번 코어, 4GB 메모리만 쓰도록 가둠 (격리).
  * `nodejs.slice`: 2-3번 코어, 4GB 메모리만 쓰도록 가둠.
  * **Accounting**: 각 그룹이 쓴 CPU cycle과 IO량을 별도로 카운팅하여 데이터(`workload_usage.tsv`)를 뽑아냄.

## 2. 워크로드별 특징 (한 줄 요약)

### A. YOLO (AI 추론) - GPU Bound + High Memory Bandwidth

* **특징**: GPU 연산이 주가 되며, CPU는 전처리/후처리만 담당.
* **A1 (Nano)**: 경량화 모델. GPU를 적게 쓰지만(13~15%), 매우 빠르게 반복되어 CPU 부하가 오히려 높음(100%).
* **A2 (Medium)**: 표준 모델. GPU 사용률이 높고(40~50%), 메모리 대역폭을 많이 사용.
* **Resource Pattern**:
  * **CPU**: 100% (Full Load - 데이터 로딩 및 전처리 병목).
  * **GPU**: 지속적인 연산 부하 발생.
  * **I/O**: 모델 로딩 시점에만 잠깐 발생.

### B. Node.js (웹 서버) - CPU Bound + Network I/O

* **특징**: 싱글 스레드 기반의 자바스크립트 런타임. GPU를 전혀 쓰지 않음.
* **B1 (Light)**: 단순 응답. CPU 부하가 낮음(15% 내외).
* **B2 (Heavy)**: 암호화 연산(bcrypt) 반복. CPU 연산을 **매우** 많이 함.
* **Resource Pattern**:
  * **CPU**: B2 기준 100%에 근접하지만, YOLO와 달리 I/O Wait이 거의 없음 (Pure Computation).
  * **GPU**: 0% (사용 안 함).
  * **I/O**: 거의 없음 (네트워크 소켓만 사용).
