/**
 * Node.js Express 서버 - Light Version (B1)
 * I/O 중심, CPU 최소 사용
 */

const express = require('express');
const app = express();
const PORT = 3000;

// 단순 JSON 응답 (CPU 최소 사용)
app.get('/', (req, res) => {
    res.json({
        status: 'ok',
        timestamp: Date.now(),
        message: 'Hello from Express (Light)'
    });
});

// 약간의 연산
app.get('/compute', (req, res) => {
    const n = parseInt(req.query.n) || 1000;
    let sum = 0;
    for (let i = 0; i < n; i++) {
        sum += Math.sqrt(i) * Math.sin(i);
    }
    res.json({ result: sum, n: n });
});

// 헬스체크
app.get('/health', (req, res) => {
    res.json({ status: 'ok', mode: 'light' });
});

app.listen(PORT, () => {
    console.log(`[Express Light] Server running on http://localhost:${PORT}`);
});
