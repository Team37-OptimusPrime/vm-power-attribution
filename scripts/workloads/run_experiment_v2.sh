#!/bin/bash
# Phase 1 실험 v2: YOLO vs Node.js 전력 비교 (보완 버전)
#
# 개선사항:
# - CPU 코어 제한 (taskset)
# - IO 측정 추가 (host_logger.py 개선)
# - 리소스 할당 명시
#
# Usage: ./run_experiment_v2.sh [experiment_name]

set -e

EXP_NAME=${1:-"exp_v2_$(date +%Y%m%d_%H%M%S)"}
BASE_DIR="$HOME/vm-power-attribution"
LOG_DIR="$BASE_DIR/data/raw/phase1/$EXP_NAME"
YOLO_DIR="$BASE_DIR/scripts/workloads"
NODE_DIR="$BASE_DIR/scripts/workloads"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"

# 리소스 할당 설정 (동일하게)
CPU_CORES="0-3"          # 4개 코어 사용 (코어 0,1,2,3)
MEMORY_LIMIT="4G"        # 4GB 메모리 제한 (cgroup 사용 시)

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"
log "Experiment: $EXP_NAME"
log "Log directory: $LOG_DIR"

# 측정 시간 설정 (초)
BASELINE_DURATION=30
WORKLOAD_DURATION=60
COOLDOWN=10

# 실험 설정 기록
cat > "$LOG_DIR/config.txt" << EOF
Experiment: $EXP_NAME
Date: $(date)
CPU Cores: $CPU_CORES
Memory Limit: $MEMORY_LIMIT (not enforced in v2)
Baseline Duration: ${BASELINE_DURATION}s
Workload Duration: ${WORKLOAD_DURATION}s
Cooldown: ${COOLDOWN}s

Workloads:
- AI: YOLOv8 Nano inference (test_video.mp4)
- Non-AI: Node.js Express + curl load

Resource Allocation:
- Both workloads use same CPU cores via taskset
- Memory not restricted (monitoring only)
EOF

info "Configuration saved to $LOG_DIR/config.txt"
info "CPU cores limited to: $CPU_CORES"

########################################
# Phase 0: Baseline (Idle)
########################################
log "=== Phase 0: Baseline (Idle) - ${BASELINE_DURATION}s ==="
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/baseline.csv" -d $BASELINE_DURATION -i 1
log "Baseline complete. Cooling down ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 1: YOLO Solo (AI)
########################################
log "=== Phase 1: YOLO Solo (AI) - ${WORKLOAD_DURATION}s ==="
info "CPU cores: $CPU_CORES (taskset)"

# 로거 시작 (백그라운드)
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/yolo_solo.csv" -d $WORKLOAD_DURATION -i 1 &
LOGGER_PID=$!
sleep 2  # 로거 안정화

# YOLO 실행 (taskset으로 코어 제한)
cd "$YOLO_DIR"
source yolo_venv/bin/activate

log "Starting YOLO inference (cores: $CPU_CORES)..."
END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
while [ $SECONDS -lt $END_TIME ]; do
    taskset -c $CPU_CORES yolo predict model=yolov8n.pt source=test_video.mp4 device=0 verbose=False 2>/dev/null || true
done

wait $LOGGER_PID 2>/dev/null || true
deactivate 2>/dev/null || true

log "YOLO solo complete. Cooling down ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 2: Node.js Solo (Non-AI)
########################################
log "=== Phase 2: Node.js Solo (Non-AI) - ${WORKLOAD_DURATION}s ==="
info "CPU cores: $CPU_CORES (taskset)"

# Node.js 서버 시작 (taskset으로 코어 제한)
cd "$NODE_DIR"
taskset -c $CPU_CORES node server.js &
NODE_PID=$!
sleep 2

# 로거 시작
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/nodejs_solo.csv" -d $WORKLOAD_DURATION -i 1 &
LOGGER_PID=$!
sleep 2

# 부하 생성 (taskset으로 코어 제한)
log "Generating load with curl (cores: $CPU_CORES)..."
END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
while [ $SECONDS -lt $END_TIME ]; do
    for i in {1..50}; do
        taskset -c $CPU_CORES curl -s http://localhost:3000/ > /dev/null &
    done
    sleep 0.1
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
info "Both workloads share CPU cores: $CPU_CORES"

# Node.js 서버 시작
cd "$NODE_DIR"
taskset -c $CPU_CORES node server.js &
NODE_PID=$!
sleep 2

# 로거 시작
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/concurrent.csv" -d $WORKLOAD_DURATION -i 1 &
LOGGER_PID=$!
sleep 2

# YOLO 시작 (백그라운드)
cd "$YOLO_DIR"
source yolo_venv/bin/activate
(
    END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
    while [ $SECONDS -lt $END_TIME ]; do
        taskset -c $CPU_CORES yolo predict model=yolov8n.pt source=test_video.mp4 device=0 verbose=False 2>/dev/null || true
    done
) &
YOLO_PID=$!

# Node.js 부하 생성 (동시)
cd "$NODE_DIR"
END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
while [ $SECONDS -lt $END_TIME ]; do
    for i in {1..50}; do
        taskset -c $CPU_CORES curl -s http://localhost:3000/ > /dev/null &
    done
    sleep 0.1
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
echo "  - config.txt      : Experiment configuration"
echo "  - baseline.csv    : Idle power"
echo "  - yolo_solo.csv   : YOLO only (AI)"
echo "  - nodejs_solo.csv : Node.js only (Non-AI)"
echo "  - concurrent.csv  : Both running simultaneously"
echo ""
info "New columns in v2: iowait_pct, io_read_kbs, io_write_kbs, mem_used_pct"
info "CPU cores limited to: $CPU_CORES for all workloads"
