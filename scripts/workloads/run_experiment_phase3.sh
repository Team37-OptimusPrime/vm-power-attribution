#!/bin/bash
# Phase 3 실험: 다중 AI 워크로드 확장 실험
#
# 교수님 피드백: AI 워크로드가 YOLO 하나만으로는 빈약
# → PyTorch GEMM, ResNet18, GPT-2 추가
# → AI+AI 조합도 포함
#
# Fixed frequency만 사용 (논문에 fixed 결과만 포함)
#
# 워크로드:
#   A2: YOLO Medium (yolov8m.pt)      - GPU (CUDA)
#   PT: PyTorch Large GEMM (4096×4096) - GPU (CUDA)
#   RN: ResNet18 Inference             - GPU (CUDA)
#   GPT: GPT-2 Inference              - GPU (CUDA)
#   B2: Node.js Heavy (server_heavy.js) - CPU only
#
# 실험 매트릭스 (16 phases):
#   Baseline (1)
#   Solo (5): A2, PT, RN, GPT, B2
#   AI+B2 (4): A2+B2, PT+B2, RN+B2, GPT+B2
#   AI+AI (6): A2+PT, A2+RN, A2+GPT, PT+RN, PT+GPT, RN+GPT
#
# GPU 할당:
#   AI+B2: AI→GPU0, B2→CPU only
#   AI+AI: Workload A→GPU0, Workload B→GPU1
#
# cgroup:
#   yolo.slice: cpuset 0-1, 4GB, 200% CPU
#   nodejs.slice: cpuset 2-3, 4GB, 200% CPU
#
# Usage:
#   sudo -E ./run_experiment_phase3.sh

set +e

########################################
# sudo 권한 확인
########################################
if [ "$EUID" -ne 0 ]; then
    echo "Error: 이 스크립트는 sudo로 실행해야 합니다."
    echo "Usage: sudo -E $0"
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
LOG_DIR="$BASE_DIR/data/raw/alienware/phase3_fixed_run3"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"

# cgroup 경로
CGROUP_ROOT="/sys/fs/cgroup"
YOLO_CGROUP="$CGROUP_ROOT/yolo.slice"
NODEJS_CGROUP="$CGROUP_ROOT/nodejs.slice"

# 시간 설정 (초)
BASELINE_DURATION=60
WORKLOAD_DURATION=90
COOLDOWN=20

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
        warn "yolo_venv가 없습니다. AI 워크로드 실행에 문제가 발생할 수 있습니다."
    fi

    if ! command -v node &> /dev/null; then
        echo "Node.js가 설치되어 있지 않습니다."
        exit 1
    fi

    # GPU 확인 (2장 필요 — AI+AI에서 GPU0/GPU1 분리)
    local gpu_count
    gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
    if [ "$gpu_count" -lt 2 ]; then
        warn "GPU가 ${gpu_count}장 감지됨. AI+AI 동시실행에는 GPU 2장이 필요합니다."
    else
        log "GPU ${gpu_count}장 감지됨"
    fi

    # Python 패키지 확인
    if [ -d "$WORKLOAD_DIR/yolo_venv" ]; then
        local venv_python="$WORKLOAD_DIR/yolo_venv/bin/python3"
        $venv_python -c "import torch; assert torch.cuda.is_available()" 2>/dev/null || \
            warn "PyTorch CUDA 사용 불가"
        $venv_python -c "import torchvision" 2>/dev/null || \
            warn "torchvision 미설치 (ResNet18에 필요)"
        $venv_python -c "import transformers" 2>/dev/null || \
            warn "transformers 미설치 (GPT-2에 필요)"
    fi

    log "사전 요구사항 확인 완료"
}

########################################
# CPU Frequency 통제 (Fixed only)
########################################
set_cpu_fixed() {
    log "CPU frequency 고정 모드 설정 중... (no_turbo=1, performance, 3.6GHz)"

    if [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
        echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo
        log "  no_turbo = 1"
    else
        warn "intel_pstate/no_turbo 파일 없음"
    fi

    for cpu in /sys/devices/system/cpu/cpu*/cpufreq; do
        [ -d "$cpu" ] || continue
        echo performance > "$cpu/scaling_governor" 2>/dev/null || true
        echo 3600000 > "$cpu/scaling_max_freq" 2>/dev/null || true
        echo 3600000 > "$cpu/scaling_min_freq" 2>/dev/null || true
    done
    log "  governor=performance, freq=3.6GHz (all cores)"
}

########################################
# 시스템 설정 기록
########################################
save_config() {
    local config_file="$LOG_DIR/config.txt"

    cat > "$config_file" << CFGEOF
===== Phase 3 Experiment Configuration =====
Date: $(date)
Type: Multi-AI Workload Expansion (Fixed frequency only)

--- CPU Frequency Control ---
CFGEOF

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
AI+B2: AI→GPU0, B2→CPU only (GPU1 idle)
AI+AI: Workload_A→GPU0 (yolo.slice), Workload_B→GPU1 (nodejs.slice)
CFGEOF

    nvidia-smi --query-gpu=index,name,driver_version,power.limit,power.default_limit \
        --format=csv >> "$config_file" 2>/dev/null || echo "(nvidia-smi unavailable)" >> "$config_file"

    cat >> "$config_file" << CFGEOF

--- cgroup Configuration ---
yolo.slice (Workload A):
  cpuset.cpus: $(cat $YOLO_CGROUP/cpuset.cpus 2>/dev/null || echo "N/A")
  cpuset.mems: $(cat $YOLO_CGROUP/cpuset.mems 2>/dev/null || echo "N/A")
  cpu.max: $(cat $YOLO_CGROUP/cpu.max 2>/dev/null || echo "N/A")
  memory.max: $(cat $YOLO_CGROUP/memory.max 2>/dev/null || echo "N/A")
  io.max: $(cat $YOLO_CGROUP/io.max 2>/dev/null || echo "N/A")
nodejs.slice (Workload B):
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
Page cache: dropped (sync + echo 3 > drop_caches) between every phase
Total Phases: 16 (1 baseline + 5 solo + 4 AI+B2 + 6 AI+AI)
Estimated time: $((BASELINE_DURATION + WORKLOAD_DURATION*15 + COOLDOWN*15))s

--- Workloads ---
Solo:
  A2: YOLO Medium (yolov8m.pt) - GPU0, yolo.slice
  PT: PyTorch GEMM (4096×4096) - GPU0, yolo.slice
  RN: ResNet18 Inference - GPU0, yolo.slice
  GPT: GPT-2 Inference - GPU0, yolo.slice
  B2: Node.js Heavy (server_heavy.js) - nodejs.slice
AI+B2 Concurrent:
  A2+B2, PT+B2, RN+B2, GPT+B2
AI+AI Concurrent:
  A2+PT, A2+RN, A2+GPT, PT+RN, PT+GPT, RN+GPT
  (Workload A → GPU0/yolo.slice, Workload B → GPU1/nodejs.slice)

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
    pkill -f "pytorch_gemm" 2>/dev/null || true
    pkill -f "resnet18_inference" 2>/dev/null || true
    pkill -f "gpt2_inference" 2>/dev/null || true
    pkill -f "yolo predict" 2>/dev/null || true
    log "정리 완료"
}

trap cleanup EXIT

########################################
# 전역 PID 변수
########################################
WL_A_PID=""
WL_B_PID=""
CURL_PID=""
NODE_PID=""

########################################
# 범용 AI 워크로드 실행 함수
########################################
start_ai_workload() {
    local workload_type=$1  # yolo_medium, pytorch_gemm, resnet18, gpt2
    local gpu_id=$2         # 0 or 1
    local slice=$3          # yolo.slice or nodejs.slice
    local duration=$4
    local pid_var=$5        # WL_A_PID or WL_B_PID

    local script=""
    local extra_args=""

    local log_file="$LOG_DIR/${workload_type}_gpu${gpu_id}_${slice}.log"

    case "$workload_type" in
        yolo_medium)
            # YOLO는 별도 실행 방식 (yolo CLI)
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
            log "YOLO Medium 시작 (PID: ${!pid_var}, GPU${gpu_id}, ${slice}, log: $log_file)"
            return
            ;;
        pytorch_gemm)
            script="$WORKLOAD_DIR/pytorch_gemm.py"
            extra_args="--duration $duration"
            ;;
        resnet18)
            script="$WORKLOAD_DIR/resnet18_inference.py"
            extra_args="--duration $duration"
            ;;
        gpt2)
            script="$WORKLOAD_DIR/gpt2_inference.py"
            extra_args="--duration $duration"
            ;;
        *)
            warn "알 수 없는 워크로드: $workload_type"
            return
            ;;
    esac

    local log_file="$LOG_DIR/${workload_type}_gpu${gpu_id}_${slice}.log"
    timeout $((duration + 10)) \
        systemd-run --scope --slice=$slice --uid=$REAL_UID --gid=$REAL_GID \
        bash -c "
            export CUDA_VISIBLE_DEVICES=$gpu_id
            source $WORKLOAD_DIR/yolo_venv/bin/activate
            python3 $script $extra_args 2>&1
        " > "$log_file" 2>&1 &
    eval "${pid_var}=$!"
    log "${workload_type} 시작 (PID: ${!pid_var}, GPU${gpu_id}, ${slice}, log: $log_file)"
}

########################################
# Node.js 서버 시작 & Heavy 부하 생성
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
# 워크로드 정리
########################################
stop_workloads() {
    [ -n "$WL_A_PID" ] && kill $WL_A_PID 2>/dev/null
    [ -n "$WL_B_PID" ] && kill $WL_B_PID 2>/dev/null
    [ -n "$CURL_PID" ] && kill $CURL_PID 2>/dev/null
    [ -n "$NODE_PID" ] && kill $NODE_PID 2>/dev/null
    pkill -f "node.*server" 2>/dev/null || true
    pkill -f "pytorch_gemm" 2>/dev/null || true
    pkill -f "resnet18_inference" 2>/dev/null || true
    pkill -f "gpt2_inference" 2>/dev/null || true
    pkill -f "yolo predict" 2>/dev/null || true
    WL_A_PID=""
    WL_B_PID=""
    CURL_PID=""
    NODE_PID=""
    sleep 2  # 프로세스 종료 대기
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
# 페이지 캐시 초기화 (Phase 간 I/O 공정성 보장)
########################################
drop_caches() {
    sync
    echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    log "Page cache dropped (sync + drop_caches)"
}

########################################
# Solo Phase 실행 헬퍼
########################################
run_solo_ai_phase() {
    local phase_num=$1
    local phase_name=$2     # e.g. "A2 - YOLO Medium Solo"
    local prefix=$3         # e.g. "A2_yolo_medium"
    local workload_type=$4  # yolo_medium, pytorch_gemm, resnet18, gpt2

    phase "Phase ${phase_num}: ${phase_name} - ${WORKLOAD_DURATION}s"
    info "워크로드: ${workload_type} | cgroup: yolo.slice | GPU0"

    start_loggers "$prefix" $WORKLOAD_DURATION
    sleep 2
    start_ai_workload "$workload_type" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"

    wait_loggers
    stop_workloads
    drop_caches

    log "${phase_name} 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
}

run_solo_b2_phase() {
    local phase_num=$1

    phase "Phase ${phase_num}: B2 - Node.js Heavy Solo - ${WORKLOAD_DURATION}s"
    info "Server: server_heavy.js | cgroup: nodejs.slice"

    start_nodejs_server "server_heavy.js"
    start_loggers "B2_nodejs_heavy" $WORKLOAD_DURATION
    sleep 2
    start_nodejs_heavy $WORKLOAD_DURATION

    wait_loggers
    stop_workloads
    drop_caches

    log "B2 Solo 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
}

########################################
# AI + B2 동시실행 Phase
########################################
run_ai_b2_phase() {
    local phase_num=$1
    local phase_name=$2     # e.g. "A2+B2"
    local prefix=$3         # e.g. "A2B2_concurrent"
    local ai_type=$4        # yolo_medium, pytorch_gemm, resnet18, gpt2

    phase "Phase ${phase_num}: ${phase_name} - ${WORKLOAD_DURATION}s"
    info "AI: ${ai_type} (GPU0, yolo.slice) + B2: Node.js Heavy (nodejs.slice)"

    start_nodejs_server "server_heavy.js"
    start_loggers "$prefix" $WORKLOAD_DURATION
    sleep 2

    # AI → GPU0, yolo.slice
    start_ai_workload "$ai_type" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"

    # B2 → nodejs.slice (CPU only)
    start_nodejs_heavy $WORKLOAD_DURATION

    wait_loggers
    stop_workloads
    drop_caches

    log "${phase_name} 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
}

########################################
# AI + AI 동시실행 Phase
########################################
run_ai_ai_phase() {
    local phase_num=$1
    local phase_name=$2     # e.g. "A2+PT"
    local prefix=$3         # e.g. "A2PT_concurrent"
    local ai_a_type=$4      # 첫 번째 AI → GPU0, yolo.slice
    local ai_b_type=$5      # 두 번째 AI → GPU1, nodejs.slice

    phase "Phase ${phase_num}: ${phase_name} - ${WORKLOAD_DURATION}s"
    info "AI_A: ${ai_a_type} (GPU0, yolo.slice) + AI_B: ${ai_b_type} (GPU1, nodejs.slice)"

    start_loggers "$prefix" $WORKLOAD_DURATION
    sleep 2

    # Workload A → GPU0, yolo.slice (cpuset 0-1)
    start_ai_workload "$ai_a_type" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"

    # Workload B → GPU1, nodejs.slice (cpuset 2-3)
    start_ai_workload "$ai_b_type" 1 "nodejs.slice" $WORKLOAD_DURATION "WL_B_PID"

    wait_loggers
    stop_workloads
    drop_caches

    log "${phase_name} 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
}

########################################
# 메인 시작
########################################

phase "Phase 3 실험: 다중 AI 워크로드 확장 (Fixed frequency)"
echo -e "${MAGENTA}워크로드:${NC}"
echo -e "${MAGENTA}  A2: YOLO Medium (GPU)    PT: PyTorch GEMM (GPU)${NC}"
echo -e "${MAGENTA}  RN: ResNet18 (GPU)       GPT: GPT-2 (GPU)${NC}"
echo -e "${MAGENTA}  B2: Node.js Heavy (CPU)${NC}"
echo -e "${MAGENTA}GPU 할당: AI+B2 → GPU0+CPU, AI+AI → GPU0+GPU1${NC}"
echo -e "${MAGENTA}총 16 phases, 예상 ~30분${NC}"

check_prerequisites

# CPU frequency 고정 (Fixed only)
set_cpu_fixed

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
drop_caches

log "Baseline 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 1-5: Solo Workloads
########################################

run_solo_ai_phase 1 "A2 - YOLO Medium Solo" "A2_yolo_medium" "yolo_medium"
run_solo_ai_phase 2 "PT - PyTorch GEMM Solo" "PT_pytorch_gemm" "pytorch_gemm"
run_solo_ai_phase 3 "RN - ResNet18 Solo" "RN_resnet18" "resnet18"
run_solo_ai_phase 4 "GPT - GPT-2 Solo" "GPT_gpt2" "gpt2"
run_solo_b2_phase 5

########################################
# Phase 6-9: AI + B2 동시실행
########################################

run_ai_b2_phase 6 "A2+B2 - YOLO Medium + Node.js Heavy" "A2B2_concurrent" "yolo_medium"
run_ai_b2_phase 7 "PT+B2 - PyTorch GEMM + Node.js Heavy" "PTB2_concurrent" "pytorch_gemm"
run_ai_b2_phase 8 "RN+B2 - ResNet18 + Node.js Heavy" "RNB2_concurrent" "resnet18"
run_ai_b2_phase 9 "GPT+B2 - GPT-2 + Node.js Heavy" "GPTB2_concurrent" "gpt2"

########################################
# Phase 10-15: AI + AI 동시실행
########################################

run_ai_ai_phase 10 "A2+PT - YOLO Medium + PyTorch GEMM" "A2PT_concurrent" "yolo_medium" "pytorch_gemm"
run_ai_ai_phase 11 "A2+RN - YOLO Medium + ResNet18" "A2RN_concurrent" "yolo_medium" "resnet18"
run_ai_ai_phase 12 "A2+GPT - YOLO Medium + GPT-2" "A2GPT_concurrent" "yolo_medium" "gpt2"
run_ai_ai_phase 13 "PT+RN - PyTorch GEMM + ResNet18" "PTRN_concurrent" "pytorch_gemm" "resnet18"
run_ai_ai_phase 14 "PT+GPT - PyTorch GEMM + GPT-2" "PTGPT_concurrent" "pytorch_gemm" "gpt2"
run_ai_ai_phase 15 "RN+GPT - ResNet18 + GPT-2" "RNGPT_concurrent" "resnet18" "gpt2"

########################################
# 완료
########################################
EXPERIMENT_ELAPSED=$((SECONDS - EXPERIMENT_START))
phase "실험 완료 (Phase 3 Fixed)"

log "결과 파일:"
ls -la "$LOG_DIR"

echo ""
info "생성된 파일:"
echo "  [Baseline]"
echo "  baseline_host.csv, baseline_cgroup.csv"
echo ""
echo "  [Solo Runs]"
echo "  A2 (YOLO Medium):   A2_yolo_medium_host.csv,   A2_yolo_medium_cgroup.csv"
echo "  PT (PyTorch GEMM):  PT_pytorch_gemm_host.csv,   PT_pytorch_gemm_cgroup.csv"
echo "  RN (ResNet18):      RN_resnet18_host.csv,       RN_resnet18_cgroup.csv"
echo "  GPT (GPT-2):        GPT_gpt2_host.csv,          GPT_gpt2_cgroup.csv"
echo "  B2 (Node.js Heavy): B2_nodejs_heavy_host.csv,   B2_nodejs_heavy_cgroup.csv"
echo ""
echo "  [AI + B2 Concurrent]"
echo "  A2+B2:  A2B2_concurrent_host.csv,  A2B2_concurrent_cgroup.csv"
echo "  PT+B2:  PTB2_concurrent_host.csv,  PTB2_concurrent_cgroup.csv"
echo "  RN+B2:  RNB2_concurrent_host.csv,  RNB2_concurrent_cgroup.csv"
echo "  GPT+B2: GPTB2_concurrent_host.csv, GPTB2_concurrent_cgroup.csv"
echo ""
echo "  [AI + AI Concurrent]"
echo "  A2+PT:  A2PT_concurrent_host.csv,  A2PT_concurrent_cgroup.csv"
echo "  A2+RN:  A2RN_concurrent_host.csv,  A2RN_concurrent_cgroup.csv"
echo "  A2+GPT: A2GPT_concurrent_host.csv, A2GPT_concurrent_cgroup.csv"
echo "  PT+RN:  PTRN_concurrent_host.csv,  PTRN_concurrent_cgroup.csv"
echo "  PT+GPT: PTGPT_concurrent_host.csv, PTGPT_concurrent_cgroup.csv"
echo "  RN+GPT: RNGPT_concurrent_host.csv, RNGPT_concurrent_cgroup.csv"

echo ""
log "총 실험 시간: ${EXPERIMENT_ELAPSED}초 (~$((EXPERIMENT_ELAPSED / 60))분)"
log "예상 시간: $((BASELINE_DURATION + WORKLOAD_DURATION*15 + COOLDOWN*15))초 (~$(( (BASELINE_DURATION + WORKLOAD_DURATION*15 + COOLDOWN*15) / 60 ))분)"
echo ""
log "다음 단계:"
echo "  1. RPICT 로깅 종료"
echo "  2. python3 scripts/analysis/extract_phase3_data.py 실행"
echo ""
log "실험 완료: Phase 3 (fixed)"
