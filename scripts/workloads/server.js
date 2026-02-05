/**
 * Node.js Express 서버 - Non-AI 워크로드
 * CPU-light, I/O 중심 워크로드
 */

const express = require('express');
const app = express();
const PORT = 3000;

// 간단한 JSON 응답 (CPU 최소 사용)
app.get('/', (req, res) => {
    res.json({
        status: 'ok',
        timestamp: Date.now(),
        message: 'Hello from Express'
    });
});

// 약간의 연산이 포함된 엔드포인트
app.get('/compute', (req, res) => {
    const n = parseInt(req.query.n) || 1000;
    let sum = 0;
    for (let i = 0; i < n; i++) {
        sum += Math.sqrt(i) * Math.sin(i);
    }
    res.json({ result: sum, n: n });
});

// 메모리 할당 테스트
app.get('/memory', (req, res) => {
    const size = parseInt(req.query.size) || 1000;
    const arr = new Array(size).fill(0).map((_, i) => ({ id: i, data: 'x'.repeat(100) }));
    res.json({ allocated: arr.length });
});

app.listen(PORT, () => {
    console.log(`[Express] Server running on http://localhost:${PORT}`);
    console.log(`[Express] Endpoints: /, /compute?n=1000, /memory?size=1000`);
});
