#!/bin/bash
# Phase 1 실험: YOLO vs Node.js 전력 비교
# Usage: ./run_experiment.sh [experiment_name]

set -e

EXP_NAME=${1:-"exp_$(date +%Y%m%d_%H%M%S)"}
BASE_DIR="$HOME/vm-power-exp"
LOG_DIR="$BASE_DIR/logs/$EXP_NAME"
YOLO_DIR="$BASE_DIR/workloads/yolo"
NODE_DIR="$BASE_DIR/workloads/nodejs"
SCRIPT_DIR="$BASE_DIR/scripts"

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"
log "Experiment: $EXP_NAME"
log "Log directory: $LOG_DIR"

# 측정 시간 설정 (초)
BASELINE_DURATION=30
WORKLOAD_DURATION=60
COOLDOWN=10

########################################
# Phase 0: Baseline (Idle)
########################################
log "=== Phase 0: Baseline (Idle) - ${BASELINE_DURATION}s ==="
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/baseline.csv" -d $BASELINE_DURATION -i 1
log "Baseline complete. Cooling down ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 1: YOLO Solo
########################################
log "=== Phase 1: YOLO Solo - ${WORKLOAD_DURATION}s ==="

# 로거 시작 (백그라운드)
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/yolo_solo.csv" -d $WORKLOAD_DURATION -i 1 &
LOGGER_PID=$!
sleep 2  # 로거 안정화

# YOLO 실행
cd "$YOLO_DIR"
source optimusVM/bin/activate

log "Starting YOLO inference..."
# 반복 실행하여 duration 동안 유지
END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
while [ $SECONDS -lt $END_TIME ]; do
    yolo predict model=yolov8n.pt source=test_video.mp4 device=0 verbose=False 2>/dev/null || true
done

wait $LOGGER_PID 2>/dev/null || true
deactivate 2>/dev/null || true

log "YOLO solo complete. Cooling down ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 2: Node.js Solo
########################################
log "=== Phase 2: Node.js Solo - ${WORKLOAD_DURATION}s ==="

# Node.js 서버 시작
cd "$NODE_DIR"
node server.js &
NODE_PID=$!
sleep 2

# 로거 시작
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/nodejs_solo.csv" -d $WORKLOAD_DURATION -i 1 &
LOGGER_PID=$!
sleep 2

# 부하 생성 (autocannon 또는 간단한 curl 루프)
log "Generating load with curl loop..."
END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
while [ $SECONDS -lt $END_TIME ]; do
    for i in {1..100}; do
        curl -s http://localhost:3000/ > /dev/null &
    done
    wait
done

wait $LOGGER_PID 2>/dev/null || true
kill $NODE_PID 2>/dev/null || true

log "Node.js solo complete. Cooling down ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 3: YOLO + Node.js 동시 실행
########################################
log "=== Phase 3: YOLO + Node.js Concurrent - ${WORKLOAD_DURATION}s ==="

# Node.js 서버 시작
cd "$NODE_DIR"
node server.js &
NODE_PID=$!
sleep 2

# 로거 시작
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/concurrent.csv" -d $WORKLOAD_DURATION -i 1 &
LOGGER_PID=$!
sleep 2

# YOLO 시작 (백그라운드)
cd "$YOLO_DIR"
source optimusVM/bin/activate
(
    END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
    while [ $SECONDS -lt $END_TIME ]; do
        yolo predict model=yolov8n.pt source=test_video.mp4 device=0 verbose=False 2>/dev/null || true
    done
) &
YOLO_PID=$!

# Node.js 부하 생성 (동시)
cd "$NODE_DIR"
END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
while [ $SECONDS -lt $END_TIME ]; do
    for i in {1..100}; do
        curl -s http://localhost:3000/ > /dev/null &
    done
    wait
done

wait $YOLO_PID 2>/dev/null || true
wait $LOGGER_PID 2>/dev/null || true
kill $NODE_PID 2>/dev/null || true
deactivate 2>/dev/null || true

########################################
# 완료
########################################
log "=== Experiment Complete ==="
log "Results saved to: $LOG_DIR"
ls -la "$LOG_DIR"

echo ""
log "CSV files:"
echo "  - baseline.csv    : Idle power"
echo "  - yolo_solo.csv   : YOLO only"
echo "  - nodejs_solo.csv : Node.js only"
echo "  - concurrent.csv  : Both running"
