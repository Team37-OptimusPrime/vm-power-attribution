# Phase 1.6 Workload Description

## 실험 환경

### Hardware
- **Host**: Alienware Aurora R12
- **CPU**: Intel Core i7-11700KF (8 cores, 16 threads, 125W TDP)
- **GPU**: NVIDIA GeForce RTX 3060 (170W TDP)
- **RAM**: 32GB DDR4-3467 (16GB × 2)
- **Storage**: Samsung SSD 980 500GB (NVMe)

### Resource Isolation (cgroup v2)
| Slice | CPU Cores | Memory | CPU Quota |
|-------|-----------|--------|-----------|
| yolo.slice | 0-1 (2 cores) | 4GB | 200% |
| nodejs.slice | 2-3 (2 cores) | 4GB | 200% |

---

## Workload Details

### A1: YOLO Nano (경량 AI)

**Model**: YOLOv8n (Nano)
- Parameters: 3.2M
- Model Size: 6MB
- 특징: 가장 작은 YOLO 모델, 빠른 추론 속도

**운용 방식**:
```bash
yolo predict model=yolov8n.pt source=test_video.mp4 device=0
```
- 60초간 test_video.mp4에 대해 연속 추론
- GPU (device=0) 사용
- cgroup: yolo.slice (cores 0-1)

**리소스 사용 특성**:
- GPU Utilization: ~40%
- GPU Power: ~39W
- CPU Usage: ~7% (전처리/후처리)

---

### A2: YOLO Medium (보편 AI)

**Model**: YOLOv8m (Medium)
- Parameters: 25.9M (Nano 대비 8배)
- Model Size: 52MB (Nano 대비 8.7배)
- 특징: 실무에서 가장 많이 사용되는 균형잡힌 모델

**운용 방식**:
```bash
yolo predict model=yolov8m.pt source=test_video.mp4 device=0
```
- 60초간 test_video.mp4에 대해 연속 추론
- GPU (device=0) 사용
- cgroup: yolo.slice (cores 0-1)

**리소스 사용 특성**:
- GPU Utilization: **~80%** (Nano 대비 2배)
- GPU Power: **~63W** (Nano 대비 1.6배)
- CPU Usage: ~8%

**A1 → A2 전력 증가 요인**:
| 요인 | A1 (Nano) | A2 (Medium) | 증가 |
|------|-----------|-------------|------|
| Model Parameters | 3.2M | 25.9M | 8.1× |
| GPU Memory | ~500MB | ~2GB | 4× |
| GPU Compute | ~40% | ~80% | 2× |
| **GPU Power** | 39W | 63W | **+24W** |

---

### B1: Node.js Light (경량 Non-AI)

**Server**: Express.js (server_light.js)
```javascript
// 단순 JSON 응답 - CPU 최소 사용
app.get('/', (req, res) => {
    res.json({
        status: 'ok',
        timestamp: Date.now(),
        message: 'Hello from Express'
    });
});
```

**부하 생성**:
```bash
# 20개 병렬 요청, 0.5초 간격
for i in {1..20}; do
    curl -s http://localhost:3000/ &
done
sleep 0.5
```

**리소스 사용 특성**:
- CPU Usage: ~5-10% (I/O 대기 시간이 대부분)
- CPU Power: ~7W (Idle 대비 +1.4W)
- GPU: Idle 상태 유지 (8.5W)

**특징**: I/O bound 워크로드, CPU 연산 거의 없음

---

### B2: Node.js Heavy (고부하 Non-AI)

**Server**: Express.js (server_heavy.js)
```javascript
const crypto = require('crypto');

// CPU 집약적 엔드포인트
app.get('/', (req, res) => {
    // PBKDF2 해시 계산 (5000 iterations)
    const hash = crypto.pbkdf2Sync('password', 'salt', 5000, 64, 'sha512');
    res.json({ status: 'ok', hash: hash.toString('hex').slice(0, 16) });
});

// 소수 계산 엔드포인트
app.get('/prime', (req, res) => {
    const limit = parseInt(req.query.limit) || 5000;
    let count = 0;
    for (let num = 2; num <= limit; num++) {
        let isPrime = true;
        for (let i = 2; i <= Math.sqrt(num); i++) {
            if (num % i === 0) { isPrime = false; break; }
        }
        if (isPrime) count++;
    }
    res.json({ primes_count: count });
});

// 복합 연산 엔드포인트
app.get('/heavy', (req, res) => {
    const n = parseInt(req.query.n) || 30000;
    let result = 0;
    for (let i = 0; i < n; i++) {
        if (i % 100 === 0) {
            const hash = crypto.createHash('sha256').update(String(i)).digest('hex');
            result += parseInt(hash.slice(0, 8), 16);
        }
        result += Math.sin(i) * Math.cos(i) * Math.tan(i % 1000 + 1);
    }
    res.json({ result: result });
});
```

**부하 생성**:
```bash
# 4개 워커 × 30개 요청/iteration = 120 RPS
for worker in {1..4}; do
    (
        while true; do
            for i in {1..10}; do
                curl -s "http://localhost:3000/" &           # PBKDF2 해시
                curl -s "http://localhost:3000/heavy?n=30000" &  # 복합 연산
                curl -s "http://localhost:3000/prime?limit=5000" &  # 소수 계산
            done
            wait
            sleep 0.1
        done
    ) &
done
```

**리소스 사용 특성**:
- CPU Usage: **~235%** (2코어 거의 100% 사용)
- CPU Power: **~54W** (Idle 대비 +48W)
- GPU: Idle 상태 유지 (8.6W)

**특징**: CPU bound 워크로드, 암호화/수학 연산 집중

---

## B1 vs B2 차이 요약

| 항목 | B1 (Light) | B2 (Heavy) | 차이 원인 |
|------|------------|------------|-----------|
| **서버 로직** | 단순 JSON 반환 | PBKDF2 + 소수 계산 + 삼각함수 | 연산 복잡도 |
| **요청 패턴** | 20 req/0.5s | 120 req/0.1s | 부하 강도 |
| **CPU Usage** | 5-10% | 235% | 연산량 |
| **CPU Power** | 7W | 54W | **+47W** |
| **Wall Power** | 41W | 118W | **+77W** |

### B2가 B1보다 전력을 많이 소비하는 이유

1. **암호화 연산 (PBKDF2)**
   - 5000번의 SHA-512 해시 iteration
   - 매 요청마다 ~5ms CPU 시간 소요

2. **수학 연산 (Prime, Heavy)**
   - 소수 판별: O(n√n) 복잡도
   - 삼각함수 30,000회 반복

3. **높은 동시성**
   - 4개 워커 프로세스
   - 요청 간격 0.1초 (vs B1의 0.5초)

---

## A2 vs B2 비교 (같은 전력대, 다른 분포)

| 항목 | A2 (YOLO Medium) | B2 (Node.js Heavy) |
|------|------------------|-------------------|
| **Wall Power** | 137W | 118W |
| **CPU Power** | 32W (23%) | 54W (46%) |
| **GPU Power** | 63W (46%) | 9W (7%) |
| **주요 연산** | GPU CUDA cores | CPU ALU/FPU |
| **병목** | GPU memory bandwidth | CPU cache/ALU |

### 시사점

1. **같은 cgroup 리소스 할당 (2 cores, 4GB)**에서도 전력 소비가 크게 다름
2. **AI 워크로드**: GPU 가속으로 인해 GPU 전력 비중 높음
3. **Non-AI 워크로드**: CPU 연산 집중으로 CPU 전력 비중 높음
4. **과금 정책**: 단순 vCPU/메모리 기반 과금은 실제 에너지 소비를 반영하지 못함

---

*Document generated: 2026-02-06*
*Phase 1.6 Experiment - VM Power Attribution Research*
