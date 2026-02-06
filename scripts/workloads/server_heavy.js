/**
 * Node.js Express 서버 - Non-AI 워크로드 (Heavy Version)
 * CPU-intensive 워크로드 for Phase 1.5 실험
 *
 * 목표: Idle 대비 유의미한 전력 차이 생성 (+15-25W)
 */

const express = require('express');
const crypto = require('crypto');
const app = express();
const PORT = 3000;

// CPU 집약적 기본 엔드포인트 (이전: 단순 JSON)
app.get('/', (req, res) => {
    // PBKDF2 해시 계산 - CPU 집약적
    const hash = crypto.pbkdf2Sync('password', 'salt', 5000, 64, 'sha512');

    res.json({
        status: 'ok',
        timestamp: Date.now(),
        hash: hash.toString('hex').slice(0, 16)
    });
});

// 고부하 연산 엔드포인트
app.get('/heavy', (req, res) => {
    const iterations = parseInt(req.query.n) || 50000;

    // 복합 CPU 부하: 해시 + 수학 연산
    let result = 0;
    for (let i = 0; i < iterations; i++) {
        // 매 100번째 iteration마다 해시 계산
        if (i % 100 === 0) {
            const hash = crypto.createHash('sha256').update(String(i)).digest('hex');
            result += parseInt(hash.slice(0, 8), 16);
        }
        // 삼각함수 연산
        result += Math.sin(i) * Math.cos(i) * Math.tan(i % 1000 + 1);
    }

    res.json({ result: result, iterations: iterations });
});

// 소수 계산 (CPU 집약적)
app.get('/prime', (req, res) => {
    const limit = parseInt(req.query.limit) || 10000;
    let count = 0;

    for (let num = 2; num <= limit; num++) {
        let isPrime = true;
        for (let i = 2; i <= Math.sqrt(num); i++) {
            if (num % i === 0) {
                isPrime = false;
                break;
            }
        }
        if (isPrime) count++;
    }

    res.json({ primes_count: count, limit: limit });
});

// 메모리 + CPU 복합 부하
app.get('/memory', (req, res) => {
    const size = parseInt(req.query.size) || 10000;

    // 큰 배열 생성 및 정렬 (CPU + 메모리)
    const arr = new Array(size).fill(0).map(() => Math.random());
    arr.sort((a, b) => a - b);

    // 추가 연산
    const sum = arr.reduce((acc, val) => acc + Math.sin(val), 0);

    res.json({ allocated: size, sum: sum.toFixed(4) });
});

// JSON 직렬화/역직렬화 부하
app.get('/json', (req, res) => {
    const depth = parseInt(req.query.depth) || 5;
    const width = parseInt(req.query.width) || 100;

    // 복잡한 객체 생성
    function createNested(d, w) {
        if (d === 0) return { value: Math.random(), data: 'x'.repeat(50) };
        return {
            level: d,
            children: Array(w).fill(null).map(() => createNested(d - 1, Math.max(1, Math.floor(w / 2))))
        };
    }

    const obj = createNested(Math.min(depth, 6), Math.min(width, 50));
    const serialized = JSON.stringify(obj);
    const parsed = JSON.parse(serialized);

    res.json({
        size: serialized.length,
        depth: depth,
        width: width
    });
});

// 헬스체크 (가벼운 버전 유지)
app.get('/health', (req, res) => {
    res.json({ status: 'ok' });
});

app.listen(PORT, () => {
    console.log(`[Express Heavy] Server running on http://localhost:${PORT}`);
    console.log(`[Express Heavy] Endpoints:`);
    console.log(`  / - PBKDF2 hash (CPU intensive)`);
    console.log(`  /heavy?n=50000 - Complex computation`);
    console.log(`  /prime?limit=10000 - Prime number calculation`);
    console.log(`  /memory?size=10000 - Array sort + computation`);
    console.log(`  /json?depth=5&width=100 - JSON serialization`);
    console.log(`  /health - Simple health check`);
});
