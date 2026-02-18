#!/bin/bash
# AI+AI 동시실행 6개 phase만 재실험
# Solo/AI+B2는 이미 정상 → 그 데이터는 유지
#
# 원인 디버깅: 각 워크로드의 stdout/stderr를 로그 파일에 저장
#
# Usage:
#   sudo -E ./rerun_ai_ai.sh

set +e

if [ "$EUID" -ne 0 ]; then
    echo "Error: sudo -E $0"
    exit 1
fi

REAL_UID=${SUDO_UID:-$(id -u)}
REAL_GID=${SUDO_GID:-$(id -g)}

BASE_DIR="$HOME/vm-power-attribution"
LOG_DIR="$BASE_DIR/data/raw/alienware/phase3_fixed"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"
CGROUP_ROOT="/sys/fs/cgroup"

WORKLOAD_DURATION=90
COOLDOWN=20

GREEN='\033[0;32m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
phase() { echo -e "\n${CYAN}========================================${NC}"; echo -e "${CYAN}$1${NC}"; echo -e "${CYAN}========================================${NC}"; }

# CPU fixed frequency
log "CPU frequency 고정 설정..."
echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null
for cpu in /sys/devices/system/cpu/cpu*/cpufreq; do
    [ -d "$cpu" ] || continue
    echo performance > "$cpu/scaling_governor" 2>/dev/null || true
    echo 3600000 > "$cpu/scaling_max_freq" 2>/dev/null || true
    echo 3600000 > "$cpu/scaling_min_freq" 2>/dev/null || true
done

WL_A_PID=""
WL_B_PID=""

cleanup() {
    jobs -p | xargs -r kill 2>/dev/null || true
    pkill -f "pytorch_gemm" 2>/dev/null || true
    pkill -f "resnet18_inference" 2>/dev/null || true
    pkill -f "gpt2_inference" 2>/dev/null || true
    pkill -f "yolo predict" 2>/dev/null || true
}
trap cleanup EXIT

start_loggers() {
    local prefix=$1
    local duration=$2
    python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/${prefix}_host.csv" -d "$duration" -i 1 &
    HOST_PID=$!
    python3 "$SCRIPT_DIR/cgroup_logger.py" -o "$LOG_DIR/${prefix}_cgroup.csv" -d "$duration" -i 1 --include-system-io &
    CGROUP_PID=$!
    log "로거 시작 (host=$HOST_PID, cgroup=$CGROUP_PID)"
}

wait_loggers() { wait $HOST_PID $CGROUP_PID 2>/dev/null || true; }

drop_caches() {
    sync
    echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    log "Page cache dropped"
}

stop_workloads() {
    [ -n "$WL_A_PID" ] && kill $WL_A_PID 2>/dev/null
    [ -n "$WL_B_PID" ] && kill $WL_B_PID 2>/dev/null
    pkill -f "pytorch_gemm" 2>/dev/null || true
    pkill -f "resnet18_inference" 2>/dev/null || true
    pkill -f "gpt2_inference" 2>/dev/null || true
    pkill -f "yolo predict" 2>/dev/null || true
    WL_A_PID=""
    WL_B_PID=""
    sleep 2
}

# AI 워크로드 시작 (로그 캡처)
start_ai() {
    local wl_type=$1
    local gpu_id=$2
    local slice=$3
    local duration=$4
    local pid_var=$5

    local script=""
    local label=""
    local log_file="$LOG_DIR/debug_${wl_type}_gpu${gpu_id}.log"

    case "$wl_type" in
        yolo_medium)
            timeout $((duration + 10)) \
                systemd-run --scope --slice=$slice --uid=$REAL_UID --gid=$REAL_GID \
                bash -c "
                    export CUDA_VISIBLE_DEVICES=$gpu_id
                    source $WORKLOAD_DIR/yolo_venv/bin/activate
                    cd $WORKLOAD_DIR
                    END_TIME=\$((SECONDS + $duration - 5))
                    while [ \$SECONDS -lt \$END_TIME ]; do
                        yolo predict model=yolov8m.pt source=test_video.mp4 device=0 verbose=False 2>&1 || true
                    done
                " > "$log_file" 2>&1 &
            eval "${pid_var}=$!"
            log "YOLO 시작 (PID=${!pid_var}, GPU$gpu_id, $slice, log=$log_file)"
            return
            ;;
        pytorch_gemm) script="pytorch_gemm.py" ;;
        resnet18) script="resnet18_inference.py" ;;
        gpt2) script="gpt2_inference.py" ;;
    esac

    timeout $((duration + 10)) \
        systemd-run --scope --slice=$slice --uid=$REAL_UID --gid=$REAL_GID \
        bash -c "
            export CUDA_VISIBLE_DEVICES=$gpu_id
            source $WORKLOAD_DIR/yolo_venv/bin/activate
            python3 $WORKLOAD_DIR/$script --duration $duration 2>&1
        " > "$log_file" 2>&1 &
    eval "${pid_var}=$!"
    log "$wl_type 시작 (PID=${!pid_var}, GPU$gpu_id, $slice, log=$log_file)"
}

run_ai_ai() {
    local num=$1
    local name=$2
    local prefix=$3
    local ai_a=$4
    local ai_b=$5

    phase "Phase $num: $name - ${WORKLOAD_DURATION}s"
    info "AI_A: $ai_a (GPU0, yolo.slice) + AI_B: $ai_b (GPU1, nodejs.slice)"

    # 기존 CSV 덮어쓰기
    start_loggers "$prefix" $WORKLOAD_DURATION
    sleep 2

    start_ai "$ai_a" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
    start_ai "$ai_b" 1 "nodejs.slice" $WORKLOAD_DURATION "WL_B_PID"

    # 5초 후 GPU 상태 확인
    sleep 5
    log "=== GPU 상태 확인 (5초 후) ==="
    nvidia-smi --query-gpu=index,utilization.gpu,memory.used,power.draw --format=csv,noheader
    log "==="

    wait_loggers
    stop_workloads
    drop_caches

    # 로그 확인
    log "--- Workload A 로그 (마지막 3줄) ---"
    tail -3 "$LOG_DIR/debug_${ai_a}_gpu0.log" 2>/dev/null || echo "(로그 없음)"
    log "--- Workload B 로그 (마지막 3줄) ---"
    tail -3 "$LOG_DIR/debug_${ai_b}_gpu1.log" 2>/dev/null || echo "(로그 없음)"

    log "$name 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
}

########################################
# 메인
########################################
phase "AI+AI 재실험 (6 phases, ~11분)"

mkdir -p "$LOG_DIR"
EXPERIMENT_START=$SECONDS

run_ai_ai 10 "A2+PT" "A2PT_concurrent" "yolo_medium" "pytorch_gemm"
run_ai_ai 11 "A2+RN" "A2RN_concurrent" "yolo_medium" "resnet18"
run_ai_ai 12 "A2+GPT" "A2GPT_concurrent" "yolo_medium" "gpt2"
run_ai_ai 13 "PT+RN" "PTRN_concurrent" "pytorch_gemm" "resnet18"
run_ai_ai 14 "PT+GPT" "PTGPT_concurrent" "pytorch_gemm" "gpt2"
run_ai_ai 15 "RN+GPT" "RNGPT_concurrent" "resnet18" "gpt2"

ELAPSED=$((SECONDS - EXPERIMENT_START))
phase "AI+AI 재실험 완료"
log "총 시간: ${ELAPSED}초 (~$((ELAPSED / 60))분)"

echo ""
log "디버그 로그 확인:"
ls -la "$LOG_DIR"/debug_*.log 2>/dev/null
echo ""
log "GPU 활용 여부는 host CSV의 gpu1_util_pct 확인"
