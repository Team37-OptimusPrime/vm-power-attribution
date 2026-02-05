#!/bin/bash
# Phase 1 실험 v2: YOLO vs Node.js 전력 비교 (보완 버전)
# Debug Mode Enabled

set -x  # Print commands as they are executed

# Helper: Process Wait with Timeout & Zombie Check
wait_safe() {
    local pid=$1
    local name=$2
    local timeout=${3:-15} # Default timeout 15s
    
    echo "DEBUG: Entering wait_safe for $name (PID $pid)"
    log "Waiting for $name (PID $pid) to finish..."
    
    local count=0
    while kill -0 $pid 2>/dev/null; do
        # Check if process is Zombie (Z) or Defunct
        local state=$(ps -p $pid -o stat= 2>/dev/null || echo "?")
        if [[ "$state" == *"Z"* ]]; then
            echo "DEBUG: Process $pid is Zombie. Breaking loop."
            break
        fi
        
        sleep 1
        count=$((count+1))
        
        if [ $count -ge $timeout ]; then
            warn "$name (PID $pid) did not exit after ${timeout}s. Force killing..."
            kill -SIGTERM $pid 2>/dev/null || true
            sleep 2
            kill -SIGKILL $pid 2>/dev/null || true
            break
        fi
    done
    
    echo "DEBUG: Waiting for $pid to be reaped..."
    wait $pid 2>/dev/null || true
    log "$name (PID $pid) finished/reaped."
}

EXP_NAME=${1:-"exp_v2_$(date +%Y%m%d_%H%M%S)"}
BASE_DIR="$HOME/vm-power-attribution"
LOG_DIR="$BASE_DIR/data/raw/phase1/$EXP_NAME"
YOLO_DIR="$BASE_DIR/scripts/workloads"
NODE_DIR="$BASE_DIR/scripts/workloads"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"

# 리소스 할당 설정
CPU_CORES="0-3"
MEMORY_LIMIT="4G"

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

mkdir -p "$LOG_DIR"
log "Experiment: $EXP_NAME"

# 측정 시간 설정
BASELINE_DURATION=30
WORKLOAD_DURATION=60
COOLDOWN=10

cat > "$LOG_DIR/config.txt" << EOF
Experiment: $EXP_NAME
Date: $(date)
CPU Cores: $CPU_CORES
Baseline Duration: ${BASELINE_DURATION}s
Workload Duration: ${WORKLOAD_DURATION}s
Cooldown: ${COOLDOWN}s
EOF

info "Configuration saved."

########################################
# Phase 0: Baseline
########################################
log "=== Phase 0: Baseline (Idle) ==="
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/baseline.csv" -d $BASELINE_DURATION -i 1
log "Baseline complete. Cooling down..."
sleep $COOLDOWN

########################################
# Phase 1: YOLO Solo
########################################
log "=== Phase 1: YOLO Solo ==="
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/yolo_solo.csv" -d $WORKLOAD_DURATION -i 1 &
LOGGER_PID=$!
sleep 2

cd "$YOLO_DIR"
source yolo_venv/bin/activate

log "Starting YOLO..."
echo "DEBUG: Loop Start"
END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
while [ $SECONDS -lt $END_TIME ]; do
    taskset -c $CPU_CORES yolo predict model=yolov8n.pt source=test_video.mp4 device=0 verbose=False 2>/dev/null || true
done
echo "DEBUG: Loop End"

wait_safe $LOGGER_PID "Phase 1 Logger"
deactivate 2>/dev/null || true

log "Phase 1 complete. Cooling down..."
sleep $COOLDOWN

########################################
# Phase 2: Node.js Solo
########################################
log "=== Phase 2: Node.js Solo ==="
cd "$NODE_DIR"
taskset -c $CPU_CORES node server.js &
NODE_PID=$!
info "Node.js PID: $NODE_PID"
sleep 2

python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/nodejs_solo.csv" -d $WORKLOAD_DURATION -i 1 &
LOGGER_PID=$!
sleep 2

log "Generating load..."
echo "DEBUG: Loop Start Phase 2"
END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
while [ $SECONDS -lt $END_TIME ]; do
    CURL_PIDS=""
    for i in {1..20}; do
        taskset -c $CPU_CORES curl -s --max-time 2 http://localhost:3000/ > /dev/null &
        CURL_PIDS="$CURL_PIDS $!"
    done
    sleep 0.5
    for pid in $CURL_PIDS; do
        wait $pid 2>/dev/null || true
    done
done
echo "DEBUG: Loop End Phase 2"

wait_safe $LOGGER_PID "Phase 2 Logger" 20

echo "DEBUG: Killing Node.js"
kill $NODE_PID 2>/dev/null || true

log "Phase 2 complete. Cooling down..."
sleep $COOLDOWN

########################################
# Phase 3: concurrent
########################################
log "=== Phase 3: Concurrent ==="
cd "$NODE_DIR"
taskset -c $CPU_CORES node server.js &
NODE_PID=$!
sleep 2

python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/concurrent.csv" -d $WORKLOAD_DURATION -i 1 &
LOGGER_PID=$!
sleep 2

cd "$YOLO_DIR"
source yolo_venv/bin/activate
(
    echo "DEBUG: Subshell Loop Start"
    END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
    while [ $SECONDS -lt $END_TIME ]; do
        taskset -c $CPU_CORES yolo predict model=yolov8n.pt source=test_video.mp4 device=0 verbose=False 2>/dev/null || true
    done
    echo "DEBUG: Subshell Loop End"
) &
YOLO_PID=$!

cd "$NODE_DIR"
echo "DEBUG: Loop Start Phase 3"
END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
while [ $SECONDS -lt $END_TIME ]; do
    CURL_PIDS=""
    for i in {1..20}; do
        taskset -c $CPU_CORES curl -s --max-time 2 http://localhost:3000/ > /dev/null &
        CURL_PIDS="$CURL_PIDS $!"
    done
    sleep 0.5
    for pid in $CURL_PIDS; do
        wait $pid 2>/dev/null || true
    done
done
echo "DEBUG: Loop End Phase 3"

wait_safe $YOLO_PID "Phase 3 YOLO"
wait_safe $LOGGER_PID "Phase 3 Logger" 20

kill $NODE_PID 2>/dev/null || true
deactivate 2>/dev/null || true

log "=== Experiment Complete ==="
