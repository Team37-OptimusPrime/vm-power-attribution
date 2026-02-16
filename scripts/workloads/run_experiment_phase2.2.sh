#!/bin/bash
# Phase 2.2 실험: 동시실행 5-Component Attribution 검증
#
# Phase 2.0에서 도출한 컴포넌트 파라미터(GPU hidden 7.6W/card, Memory 0.25W/DIMM)와
# Phase 2.1에서 도출한 Storage 에너지(0.0025~0.0028 W/(MB/s))를 적용하여
# 동시실행 시 에너지 분배가 solo 결과와 일치하는지 검증한다.
#
# 핵심: A solo → B solo → A+B 동시 → 분배 비율 일치 검증 (4가지 조합)
#
# GPU 분리: GPU0=YOLO, GPU1=Node.js(idle hidden power 귀속)
#
# Solo Workloads:
#   A1: YOLO Nano (yolov8n.pt) - GPU0
#   A2: YOLO Medium (yolov8m.pt) - GPU0
#   B1: Node.js Light (server_light.js)
#   B2: Node.js Heavy (server_heavy.js)
#
# Concurrent Combinations:
#   A1+B1, A1+B2, A2+B1, A2+B2
#
# Usage:
#   sudo -E ./run_experiment_phase2.2.sh fixed   # Round 1: Fixed frequency (3.6GHz)
#   sudo -E ./run_experiment_phase2.2.sh free    # Round 2: Free frequency (turbo enabled)

set +e

########################################
# 인자 파싱
########################################
ROUND_MODE=${1:-""}
if [ "$ROUND_MODE" != "fixed" ] && [ "$ROUND_MODE" != "free" ]; then
    echo "Usage: sudo -E $0 {fixed|free}"
    echo "  fixed  — Round 1: no_turbo=1, performance governor, 3.6GHz 고정"
    echo "  free   — Round 2: turbo enabled, powersave governor"
    exit 1
fi

# sudo 권한 확인
if [ "$EUID" -ne 0 ]; then
    echo "Error: 이 스크립트는 sudo로 실행해야 합니다."
    echo "Usage: sudo -E $0 {fixed|free}"
    exit 1
fi

# 실제 사용자 UID/GID (sudo 전 사용자)
REAL_UID=${SUDO_UID:-$(id -u)}
REAL_GID=${SUDO_GID:-$(id -g)}
REAL_USER=${SUDO_USER:-$(whoami)}

########################################
# 설정
########################################
BASE_DIR="$HOME/vm-power-attribution"
LOG_DIR="$BASE_DIR/data/raw/alienware/phase2.2_${ROUND_MODE}"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"

# cgroup 경로
CGROUP_ROOT="/sys/fs/cgroup"
YOLO_CGROUP="$CGROUP_ROOT/yolo.slice"
NODEJS_CGROUP="$CGROUP_ROOT/nodejs.slice"

# 시간 설정 (초) — Phase 1.6 대비 연장
BASELINE_DURATION=60    # was 30
WORKLOAD_DURATION=90    # was 60
COOLDOWN=20             # was 15

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
phase() { echo -e "\n${CYAN}========================================${NC}"; echo -e "${CYAN}$1${NC}"; echo -e "${CYAN}========================================${NC}"; }

########################################
# 전처리 체크
########################################
check_prerequisites() {
    log "사전 요구사항 확인 중..."

    if [ ! -d "$YOLO_CGROUP" ]; then
        echo "yolo.slice cgroup이 없습니다. 'sudo ./setup_cgroups.sh' 먼저 실행하세요."
        exit 1
    fi

    if [ ! -d "$NODEJS_CGROUP" ]; then
        echo "nodejs.slice cgroup이 없습니다. 'sudo ./setup_cgroups.sh' 먼저 실행하세요."
        exit 1
    fi

    if [ ! -d "$WORKLOAD_DIR/yolo_venv" ]; then
        warn "yolo_venv가 없습니다. YOLO 테스트 시 문제가 발생할 수 있습니다."
    fi

    if ! command -v node &> /dev/null; then
        echo "Node.js가 설치되어 있지 않습니다."
        exit 1
    fi

    # GPU 확인 (2장 필요)
    local gpu_count
    gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
    if [ "$gpu_count" -lt 2 ]; then
        warn "GPU가 ${gpu_count}장 감지됨. 이 실험은 GPU 2장을 전제로 합니다."
        warn "GPU1 power 측정이 불가능할 수 있습니다. 계속 진행합니다."
    else
        log "GPU ${gpu_count}장 감지됨"
    fi

    log "사전 요구사항 확인 완료"
}

########################################
# CPU Frequency 통제
########################################
set_cpu_fixed() {
    log "CPU frequency 고정 모드 설정 중... (no_turbo=1, performance, 3.6GHz)"

    # Turbo Boost 비활성화
    if [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
        echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo
        log "  no_turbo = 1"
    else
        warn "intel_pstate/no_turbo 파일 없음"
    fi

    # 모든 코어: performance governor, 3.6GHz 고정
    for cpu in /sys/devices/system/cpu/cpu*/cpufreq; do
        [ -d "$cpu" ] || continue
        echo performance > "$cpu/scaling_governor" 2>/dev/null || true
        echo 3600000 > "$cpu/scaling_max_freq" 2>/dev/null || true
        echo 3600000 > "$cpu/scaling_min_freq" 2>/dev/null || true
    done
    log "  governor=performance, freq=3.6GHz (all cores)"
}

set_cpu_free() {
    log "CPU frequency 자유 모드 설정 중... (turbo enabled, powersave)"

    # Turbo Boost 활성화
    if [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
        echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo
        log "  no_turbo = 0"
    else
        warn "intel_pstate/no_turbo 파일 없음"
    fi

    # 모든 코어: powersave governor, 넓은 범위
    for cpu in /sys/devices/system/cpu/cpu*/cpufreq; do
        [ -d "$cpu" ] || continue
        echo powersave > "$cpu/scaling_governor" 2>/dev/null || true
        echo 5000000 > "$cpu/scaling_max_freq" 2>/dev/null || true
        echo 800000 > "$cpu/scaling_min_freq" 2>/dev/null || true
    done
    log "  governor=powersave, freq=800MHz~5.0GHz (all cores)"
}

########################################
# 시스템 설정 기록
########################################
save_config() {
    local config_file="$LOG_DIR/config.txt"

    cat > "$config_file" << CFGEOF
===== Phase 2.2 Experiment Configuration =====
Date: $(date)
Round: $ROUND_MODE
Type: 5-Component Attribution Concurrent Verification

--- CPU Frequency Control ---
CFGEOF

    # CPU governor/freq 상태
    if [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
        echo "no_turbo: $(cat /sys/devices/system/cpu/intel_pstate/no_turbo)" >> "$config_file"
    fi
    local sample_cpu="/sys/devices/system/cpu/cpu0/cpufreq"
    if [ -d "$sample_cpu" ]; then
        echo "governor: $(cat $sample_cpu/scaling_governor 2>/dev/null)" >> "$config_file"
        echo "scaling_min_freq: $(cat $sample_cpu/scaling_min_freq 2>/dev/null)" >> "$config_file"
        echo "scaling_max_freq: $(cat $sample_cpu/scaling_max_freq 2>/dev/null)" >> "$config_file"
        echo "scaling_cur_freq: $(cat $sample_cpu/scaling_cur_freq 2>/dev/null)" >> "$config_file"
    fi

    cat >> "$config_file" << CFGEOF

--- GPU Configuration ---
GPU assignment: GPU0=YOLO, GPU1=Node.js(idle hidden power)
CFGEOF

    nvidia-smi --query-gpu=index,name,driver_version,power.limit,power.default_limit \
        --format=csv >> "$config_file" 2>/dev/null || echo "(nvidia-smi unavailable)" >> "$config_file"

    cat >> "$config_file" << CFGEOF

--- cgroup Configuration ---
YOLO slice:
  cpuset.cpus: $(cat $YOLO_CGROUP/cpuset.cpus 2>/dev/null || echo "N/A")
  cpuset.mems: $(cat $YOLO_CGROUP/cpuset.mems 2>/dev/null || echo "N/A")
  cpu.max: $(cat $YOLO_CGROUP/cpu.max 2>/dev/null || echo "N/A")
  memory.max: $(cat $YOLO_CGROUP/memory.max 2>/dev/null || echo "N/A")
  io.max: $(cat $YOLO_CGROUP/io.max 2>/dev/null || echo "N/A")
Node.js slice:
  cpuset.cpus: $(cat $NODEJS_CGROUP/cpuset.cpus 2>/dev/null || echo "N/A")
  cpuset.mems: $(cat $NODEJS_CGROUP/cpuset.mems 2>/dev/null || echo "N/A")
  cpu.max: $(cat $NODEJS_CGROUP/cpu.max 2>/dev/null || echo "N/A")
  memory.max: $(cat $NODEJS_CGROUP/memory.max 2>/dev/null || echo "N/A")
  io.max: $(cat $NODEJS_CGROUP/io.max 2>/dev/null || echo "N/A")

--- Hardware ---
DIMM: 2x16GB (32GB total)
Kernel: $(uname -r)
CPU: $(lscpu 2>/dev/null | grep "Model name" | sed 's/Model name: *//')
SSD: $(lsblk -dn -o MODEL /dev/nvme0n1 2>/dev/null || echo "N/A")

--- Timing ---
Baseline: ${BASELINE_DURATION}s
Each Phase: ${WORKLOAD_DURATION}s
Cooldown: ${COOLDOWN}s
Total Phases: 9 (1 baseline + 4 solo + 4 concurrent)
Estimated time: $((BASELINE_DURATION + WORKLOAD_DURATION*8 + COOLDOWN*8))s

--- Workloads ---
Solo:
  A1: YOLO Nano (yolov8n.pt) - GPU0, yolo.slice
  A2: YOLO Medium (yolov8m.pt) - GPU0, yolo.slice
  B1: Node.js Light (server_light.js) - nodejs.slice
  B2: Node.js Heavy (server_heavy.js) - nodejs.slice
Concurrent:
  A1+B1, A1+B2, A2+B1, A2+B2

--- nvidia-smi Full Output ---
CFGEOF

    nvidia-smi -q >> "$config_file" 2>/dev/null || echo "(nvidia-smi -q unavailable)" >> "$config_file"

    chown $REAL_UID:$REAL_GID "$config_file"
    log "설정 기록 완료: $config_file"
}

########################################
# Cleanup & trap
########################################
cleanup() {
    log "정리 중..."
    jobs -p | xargs -r kill 2>/dev/null || true
    pkill -f "node.*server" 2>/dev/null || true
    log "정리 완료"
}

trap cleanup EXIT

########################################
# 전역 PID 변수
########################################
YOLO_PID=""
CURL_PID=""
NODE_PID=""

########################################
# YOLO 실행 함수 — GPU0 고정 (CUDA_VISIBLE_DEVICES=0)
########################################
start_yolo() {
    local model=$1  # yolov8n.pt or yolov8m.pt
    local duration=$2

    YOLO_PID=""
    if [ -d "$WORKLOAD_DIR/yolo_venv" ]; then
        timeout $((duration + 10)) \
            sudo CUDA_VISIBLE_DEVICES=0 systemd-run --scope --slice=yolo.slice --uid=$REAL_UID --gid=$REAL_GID \
            bash -c "
                export CUDA_VISIBLE_DEVICES=0
                source $WORKLOAD_DIR/yolo_venv/bin/activate
                END_TIME=\$((SECONDS + $duration - 5))
                while [ \$SECONDS -lt \$END_TIME ]; do
                    yolo predict model=$model source=test_video.mp4 device=0 verbose=False 2>/dev/null || true
                done
            " &
        YOLO_PID=$!
        log "YOLO 시작 (PID: $YOLO_PID, model: $model, GPU0)"
    else
        warn "yolo_venv 없음, YOLO 스킵"
    fi
}

########################################
# Node.js Light 부하 생성
########################################
start_nodejs_light() {
    local duration=$1

    (
        echo $$ > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null || true
        END_TIME=$((SECONDS + duration - 5))
        while [ $SECONDS -lt $END_TIME ]; do
            for i in {1..20}; do
                curl -s --max-time 2 "http://localhost:3000/" > /dev/null 2>&1 &
            done
            wait
            sleep 0.5
        done
    ) &
    CURL_PID=$!
    log "Light 부하 시작 (PID: $CURL_PID)"
}

########################################
# Node.js Heavy 부하 생성
########################################
start_nodejs_heavy() {
    local duration=$1

    (
        echo $$ > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null || true
        END_TIME=$((SECONDS + duration - 5))

        for worker in {1..4}; do
            (
                while [ $SECONDS -lt $END_TIME ]; do
                    for i in {1..10}; do
                        curl -s --max-time 3 "http://localhost:3000/" > /dev/null 2>&1 &
                        curl -s --max-time 3 "http://localhost:3000/heavy?n=30000" > /dev/null 2>&1 &
                        curl -s --max-time 3 "http://localhost:3000/prime?limit=5000" > /dev/null 2>&1 &
                    done
                    wait
                    sleep 0.1
                done
            ) &
        done
        wait
    ) &
    CURL_PID=$!
    log "Heavy 부하 시작 (PID: $CURL_PID)"
}

########################################
# Node.js 서버 시작
########################################
start_nodejs_server() {
    local server_file=$1

    cd "$WORKLOAD_DIR"
    (
        echo $$ > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null || true
        exec node "$server_file" 2>/dev/null
    ) &
    NODE_PID=$!
    sleep 2
    log "Node.js 서버 시작 (PID: $NODE_PID, file: $server_file)"
}

########################################
# 워크로드 정리
########################################
stop_workloads() {
    [ -n "$YOLO_PID" ] && kill $YOLO_PID 2>/dev/null
    [ -n "$CURL_PID" ] && kill $CURL_PID 2>/dev/null
    [ -n "$NODE_PID" ] && kill $NODE_PID 2>/dev/null
    pkill -f "node.*server" 2>/dev/null || true
    YOLO_PID=""
    CURL_PID=""
    NODE_PID=""
}

########################################
# 측정 시작 헬퍼 — host_logger + cgroup_logger 병렬 실행
########################################
start_loggers() {
    local prefix=$1
    local duration=$2

    python3 "$SCRIPT_DIR/host_logger.py" \
        -o "$LOG_DIR/${prefix}_host.csv" \
        -d "$duration" -i 1 &
    HOST_PID=$!

    python3 "$SCRIPT_DIR/cgroup_logger.py" \
        -o "$LOG_DIR/${prefix}_cgroup.csv" \
        -d "$duration" -i 1 \
        --include-system-io &
    CGROUP_PID=$!

    log "로거 시작 (host PID: $HOST_PID, cgroup PID: $CGROUP_PID)"
}

wait_loggers() {
    wait $HOST_PID $CGROUP_PID 2>/dev/null || true
}

########################################
# 단일 Phase 실행 헬퍼
########################################
run_solo_phase() {
    local phase_num=$1
    local phase_name=$2     # e.g. "A1 - YOLO Nano Solo"
    local prefix=$3         # e.g. "A1_yolo_nano"
    local workload_type=$4  # yolo_nano, yolo_medium, nodejs_light, nodejs_heavy

    phase "Phase ${phase_num}: ${phase_name} - ${WORKLOAD_DURATION}s"

    case "$workload_type" in
        yolo_nano)
            info "Model: yolov8n.pt | cgroup: yolo.slice | GPU0"
            start_loggers "$prefix" $WORKLOAD_DURATION
            sleep 2
            cd "$WORKLOAD_DIR"
            start_yolo "yolov8n.pt" $WORKLOAD_DURATION
            ;;
        yolo_medium)
            info "Model: yolov8m.pt | cgroup: yolo.slice | GPU0"
            start_loggers "$prefix" $WORKLOAD_DURATION
            sleep 2
            cd "$WORKLOAD_DIR"
            start_yolo "yolov8m.pt" $WORKLOAD_DURATION
            ;;
        nodejs_light)
            info "Server: server_light.js | cgroup: nodejs.slice"
            start_nodejs_server "server_light.js"
            start_loggers "$prefix" $WORKLOAD_DURATION
            sleep 2
            start_nodejs_light $WORKLOAD_DURATION
            ;;
        nodejs_heavy)
            info "Server: server_heavy.js | cgroup: nodejs.slice"
            start_nodejs_server "server_heavy.js"
            start_loggers "$prefix" $WORKLOAD_DURATION
            sleep 2
            start_nodejs_heavy $WORKLOAD_DURATION
            ;;
    esac

    wait_loggers
    stop_workloads

    log "${phase_name} 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
}

run_concurrent_phase() {
    local phase_num=$1
    local phase_name=$2     # e.g. "A1+B1 - YOLO Nano + Node.js Light"
    local prefix=$3         # e.g. "A1B1_concurrent"
    local yolo_model=$4     # yolov8n.pt or yolov8m.pt
    local nodejs_server=$5  # server_light.js or server_heavy.js
    local nodejs_load=$6    # light or heavy

    phase "Phase ${phase_num}: ${phase_name} - ${WORKLOAD_DURATION}s"
    info "YOLO: ${yolo_model} (yolo.slice, GPU0) + Node.js: ${nodejs_server} (nodejs.slice)"

    start_nodejs_server "$nodejs_server"
    start_loggers "$prefix" $WORKLOAD_DURATION

    sleep 2
    cd "$WORKLOAD_DIR"
    start_yolo "$yolo_model" $WORKLOAD_DURATION

    if [ "$nodejs_load" = "light" ]; then
        start_nodejs_light $WORKLOAD_DURATION
    else
        start_nodejs_heavy $WORKLOAD_DURATION
    fi

    wait_loggers
    stop_workloads

    log "${phase_name} 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
}

########################################
# 메인 시작
########################################

phase "Phase 2.2 실험: 5-Component Attribution 동시실행 검증"
echo -e "${MAGENTA}Round: ${ROUND_MODE}${NC}"
echo -e "${MAGENTA}A1: YOLO Nano (GPU0)    A2: YOLO Medium (GPU0)${NC}"
echo -e "${MAGENTA}B1: Node.js Light       B2: Node.js Heavy${NC}"
echo -e "${MAGENTA}GPU0=YOLO, GPU1=Node.js(idle hidden power)${NC}"

check_prerequisites

# CPU frequency 설정
if [ "$ROUND_MODE" = "fixed" ]; then
    set_cpu_fixed
else
    set_cpu_free
fi

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"
log "로그 디렉토리: $LOG_DIR"

# 시스템 설정 기록
save_config

# 전체 실험 시작 시간 기록
EXPERIMENT_START=$SECONDS

########################################
# Phase 0: Baseline (Idle) — 60s
########################################
phase "Phase 0: Baseline (Idle) - ${BASELINE_DURATION}s"
info "모든 워크로드 중지 상태에서 idle 전력 측정"

start_loggers "baseline" $BASELINE_DURATION
wait_loggers

log "Baseline 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 1-4: Solo Workloads
########################################

run_solo_phase 1 "A1 - YOLO Nano Solo" "A1_yolo_nano" "yolo_nano"
run_solo_phase 2 "A2 - YOLO Medium Solo" "A2_yolo_medium" "yolo_medium"
run_solo_phase 3 "B1 - Node.js Light Solo" "B1_nodejs_light" "nodejs_light"
run_solo_phase 4 "B2 - Node.js Heavy Solo" "B2_nodejs_heavy" "nodejs_heavy"

########################################
# Phase 5-8: Concurrent Workloads
########################################

run_concurrent_phase 5 "A1+B1 - YOLO Nano + Node.js Light" "A1B1_concurrent" \
    "yolov8n.pt" "server_light.js" "light"

run_concurrent_phase 6 "A1+B2 - YOLO Nano + Node.js Heavy" "A1B2_concurrent" \
    "yolov8n.pt" "server_heavy.js" "heavy"

run_concurrent_phase 7 "A2+B1 - YOLO Medium + Node.js Light" "A2B1_concurrent" \
    "yolov8m.pt" "server_light.js" "light"

run_concurrent_phase 8 "A2+B2 - YOLO Medium + Node.js Heavy" "A2B2_concurrent" \
    "yolov8m.pt" "server_heavy.js" "heavy"

########################################
# 완료
########################################
EXPERIMENT_ELAPSED=$((SECONDS - EXPERIMENT_START))
phase "실험 완료 (Round: ${ROUND_MODE})"

log "결과 파일:"
ls -la "$LOG_DIR"

echo ""
info "생성된 파일:"
echo "  [Baseline]"
echo "  baseline_host.csv, baseline_cgroup.csv"
echo ""
echo "  [Solo Runs]"
echo "  A1 (YOLO Nano):     A1_yolo_nano_host.csv,     A1_yolo_nano_cgroup.csv"
echo "  A2 (YOLO Medium):   A2_yolo_medium_host.csv,   A2_yolo_medium_cgroup.csv"
echo "  B1 (Node.js Light): B1_nodejs_light_host.csv,   B1_nodejs_light_cgroup.csv"
echo "  B2 (Node.js Heavy): B2_nodejs_heavy_host.csv,   B2_nodejs_heavy_cgroup.csv"
echo ""
echo "  [Concurrent Runs]"
echo "  A1+B1: A1B1_concurrent_host.csv, A1B1_concurrent_cgroup.csv"
echo "  A1+B2: A1B2_concurrent_host.csv, A1B2_concurrent_cgroup.csv"
echo "  A2+B1: A2B1_concurrent_host.csv, A2B1_concurrent_cgroup.csv"
echo "  A2+B2: A2B2_concurrent_host.csv, A2B2_concurrent_cgroup.csv"

echo ""
log "총 실험 시간: ${EXPERIMENT_ELAPSED}초 (~$((EXPERIMENT_ELAPSED / 60))분)"
log "예상 시간: $((BASELINE_DURATION + WORKLOAD_DURATION*8 + COOLDOWN*8))초 (~$(( (BASELINE_DURATION + WORKLOAD_DURATION*8 + COOLDOWN*8) / 60 ))분)"
echo ""
log "다음 단계:"
if [ "$ROUND_MODE" = "fixed" ]; then
    echo "  1. 최소 5분 대기 (시스템 냉각)"
    echo "  2. sudo -E ./run_experiment_phase2.2.sh free   # Round 2 실행"
    echo "  3. RPICT 데이터 수집 (별도 Raspberry Pi)"
else
    echo "  1. RPICT 로깅 종료"
    echo "  2. 분석 스크립트 실행 (5-Component Attribution)"
fi
echo ""
log "실험 완료: Phase 2.2 (${ROUND_MODE})"
