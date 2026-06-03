#!/bin/bash
# alienware에서 Streamlit 대시보드 + ngrok 터널 시작
# Usage: ./start_dashboard.sh [--port 8501] [--ngrok]
#
# 사전 준비:
#   pip install streamlit plotly pandas numpy
#   pip install pyngrok   (ngrok 옵션 사용 시)
#   ngrok config add-authtoken <YOUR_TOKEN>   (최초 1회)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8501
USE_NGROK=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --port) PORT="$2"; shift 2 ;;
        --ngrok) USE_NGROK=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }

# Python 환경 확인
if ! python3 -c "import streamlit" &>/dev/null; then
    log "streamlit 설치 중..."
    pip install streamlit plotly pandas numpy --quiet
fi

log "Streamlit 시작 (port $PORT)..."

cd "$SCRIPT_DIR"

# streamlit을 백그라운드로 실행
streamlit run app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false &
STREAMLIT_PID=$!

log "Streamlit PID: $STREAMLIT_PID"
echo $STREAMLIT_PID > /tmp/streamlit_dashboard.pid

# 서버 뜰 때까지 대기
sleep 3

LOCAL_IP=$(hostname -I | awk '{print $1}')
log "로컬 접속: http://${LOCAL_IP}:${PORT}"

# ------------------------------------------------------------------
# ngrok 터널
# ------------------------------------------------------------------
if $USE_NGROK; then
    if ! command -v ngrok &>/dev/null; then
        log "ngrok 바이너리 없음. snap 또는 직접 설치 필요:"
        echo "  sudo snap install ngrok"
        echo "  ngrok config add-authtoken <YOUR_TOKEN>"
    else
        log "ngrok 터널 시작..."
        ngrok http "$PORT" --log=stdout &
        NGROK_PID=$!
        echo $NGROK_PID >> /tmp/streamlit_dashboard.pid
        sleep 3
        # ngrok 공개 URL 출력
        PUBLIC_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null \
            | python3 -c "import sys,json; t=json.load(sys.stdin)['tunnels']; print(t[0]['public_url'])" 2>/dev/null || echo "")
        if [ -n "$PUBLIC_URL" ]; then
            echo ""
            echo -e "${CYAN}========================================${NC}"
            echo -e "${CYAN}  공개 URL: ${PUBLIC_URL}${NC}"
            echo -e "${CYAN}========================================${NC}"
            echo ""
        else
            log "ngrok API에서 URL 가져오기 실패. http://localhost:4040 에서 직접 확인하세요."
        fi
    fi
fi

log "종료하려면 Ctrl+C"
log "또는: kill \$(cat /tmp/streamlit_dashboard.pid)"

# foreground 유지
wait $STREAMLIT_PID
