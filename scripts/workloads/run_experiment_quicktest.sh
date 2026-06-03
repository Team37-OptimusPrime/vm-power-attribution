#!/bin/bash
# Quick pipeline test: YOLO solo, 30s baseline + 60s workload
# Usage: sudo -E ./run_experiment_quicktest.sh

set +e

if [ "$EUID" -ne 0 ]; then
    echo "Error: sudo로 실행해야 합니다."
    echo "Usage: sudo -E $0"
    exit 1
fi

REAL_UID=${SUDO_UID:-$(id -u)}
REAL_GID=${SUDO_GID:-$(id -g)}
REAL_USER=${SUDO_USER:-$(whoami)}

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${INTEGRATED_LOG_DIR:-$BASE_DIR/data/raw/alienware/quicktest_run1}"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"

CGROUP_ROOT="/sys/fs/cgroup"
YOLO_CGROUP="$CGROUP_ROOT/yolo.slice"

BASELINE_DURATION=30
WORKLOAD_DURATION=60
COOLDOWN=10

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
log()   { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
phase() { echo -e "\n${CYAN}=== $1 ===${NC}"; }

########################################
# 사전 확인
########################################
if [ ! -d "$YOLO_CGROUP" ]; then
    echo "yolo.slice cgroup 없음. 'sudo ./setup_cgroups.sh' 먼저 실행하세요."
    exit 1
fi
if [ ! -d "$WORKLOAD_DIR/yolo_venv" ]; then
    warn "yolo_venv 없음 — YOLO 워크로드 실패할 수 있음"
fi

mkdir -p "$LOG_DIR"
chown -R "$REAL_UID:$REAL_GID" "$LOG_DIR"

VENV_PYTHON="$WORKLOAD_DIR/yolo_venv/bin/python3"
HOST_LOG="$SCRIPT_DIR/host_logger.py"
CGROUP_LOG="$SCRIPT_DIR/cgroup_logger.py"

########################################
# CPU 고정
########################################
if [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
    echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo
fi
for cpu in /sys/devices/system/cpu/cpu*/cpufreq; do
    [ -d "$cpu" ] || continue
    echo performance > "$cpu/scaling_governor" 2>/dev/null || true
    echo 3600000 > "$cpu/scaling_max_freq" 2>/dev/null || true
    echo 3600000 > "$cpu/scaling_min_freq" 2>/dev/null || true
done
log "CPU 고정: performance governor, 3.6GHz"

########################################
# Helper: start/stop loggers
########################################
start_loggers() {
    local prefix="$1"
    python3 "$HOST_LOG" --output "$LOG_DIR/${prefix}_host.csv" --interval 1 &
    HOST_PID=$!
    python3 "$CGROUP_LOG" --output "$LOG_DIR/${prefix}_cgroup.csv" --interval 1 &
    CGROUP_PID=$!
    log "  로거 시작 (host PID=$HOST_PID, cgroup PID=$CGROUP_PID)"
}

stop_loggers() {
    kill "$HOST_PID" "$CGROUP_PID" 2>/dev/null
    wait "$HOST_PID" "$CGROUP_PID" 2>/dev/null
    log "  로거 종료"
}

########################################
# Phase: Baseline
########################################
phase "Baseline (${BASELINE_DURATION}s)"
start_loggers "baseline"
sleep "$BASELINE_DURATION"
stop_loggers

########################################
# Phase: YOLO solo (GPU0, yolo.slice)
########################################
phase "YOLO Solo (${WORKLOAD_DURATION}s)"
start_loggers "yolo_solo"

# Launch YOLO inside yolo.slice
YOLO_SCRIPT="$WORKLOAD_DIR/yolo_workload.py"
if [ ! -f "$YOLO_SCRIPT" ]; then
    # Fallback: inline minimal YOLO loop
    YOLO_SCRIPT="/tmp/yolo_quicktest.py"
    cat > "$YOLO_SCRIPT" << 'PYEOF'
import torch, time, sys
from ultralytics import YOLO
model = YOLO("yolov8m.pt")
dummy = torch.randn(1, 3, 640, 640).cuda()
end = time.time() + int(sys.argv[1]) if len(sys.argv) > 1 else time.time() + 60
while time.time() < end:
    model(dummy, verbose=False)
PYEOF
fi

CUDA_VISIBLE_DEVICES=0 \
    systemd-run --slice=yolo.slice --uid="$REAL_UID" --gid="$REAL_GID" \
    --collect --wait \
    "$VENV_PYTHON" "$YOLO_SCRIPT" "$WORKLOAD_DURATION" &
WORKLOAD_PID=$!
sleep "$WORKLOAD_DURATION"
kill "$WORKLOAD_PID" 2>/dev/null; wait "$WORKLOAD_PID" 2>/dev/null

stop_loggers

########################################
# Cooldown
########################################
phase "Cooldown (${COOLDOWN}s)"
sleep "$COOLDOWN"

########################################
# 완료
########################################
chown -R "$REAL_UID:$REAL_GID" "$LOG_DIR"
log "Quick test 완료. 데이터: $LOG_DIR"
echo ""
echo "생성 파일:"
ls -lh "$LOG_DIR/"
