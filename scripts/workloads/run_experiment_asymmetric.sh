#!/bin/bash
# 비대칭 자원할당 실험 (Asymmetric Resource Allocation Experiment)
#
# 목적: 동일한 워크로드 조합에서 CPU/메모리 할당 비율을 바꿔가며 실험
#       → 자원 비율이 달라도 전력은 workload type이 결정함을 검증 (J Kim et al. 결론 확장)
#
# 실험 설계:
#   총 4코어(32GB 중 8GB) 사용, 3가지 비율:
#   - 1:1  → AI=cpuset 0-1 (2코어, 4GB) | NonAI=cpuset 2-3 (2코어, 4GB)  [기존과 동일]
#   - 2:1  → AI=cpuset 0-2 (3코어, 6GB) | NonAI=cpuset 3   (1코어, 2GB)  [AI 우대]
#   - 1:2  → AI=cpuset 0   (1코어, 2GB) | NonAI=cpuset 1-3 (3코어, 6GB)  [NonAI 우대]
#
# 각 비율별 실행 phases:
#   - YOLO+Node.js   (AI+NonAI)
#   - ResNet+Node.js (AI+NonAI)
#   - GPT2+Node.js   (AI+NonAI)
#   - YOLO+ResNet    (AI+AI) — GPU-dominant이라 ratio 영향 거의 없음 예상
#
# + 최초 1회: Baseline + Solo phases (비율 독립)
#
# Usage:
#   sudo -E ./run_experiment_asymmetric.sh [RUN_NUM]
#   예) sudo -E ./run_experiment_asymmetric.sh 1    → phase3_asym_run1

set +e

########################################
# sudo 권한 확인
########################################
if [ "$EUID" -ne 0 ]; then
    echo "Error: sudo로 실행해야 합니다."
    echo "Usage: sudo -E $0 [RUN_NUM]"
    exit 1
fi

REAL_UID=${SUDO_UID:-$(id -u)}
REAL_GID=${SUDO_GID:-$(id -g)}
REAL_USER=${SUDO_USER:-$(whoami)}

########################################
# 인수 처리
########################################
RUN_NUM=${1:-1}

########################################
# 경로 설정
########################################
BASE_DIR="$HOME/vm-power-attribution"
LOG_DIR="$BASE_DIR/data/raw/alienware/phase3_asym_run${RUN_NUM}"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"

CGROUP_ROOT="/sys/fs/cgroup"
YOLO_CGROUP="$CGROUP_ROOT/yolo.slice"
NODEJS_CGROUP="$CGROUP_ROOT/nodejs.slice"

########################################
# 타이밍
########################################
BASELINE_DURATION=60
WORKLOAD_DURATION=90
COOLDOWN=20

########################################
# 비율 정의
#   RATIOS 배열: "label:ai_cpuset:ai_mem_gb:nonai_cpuset:nonai_mem_gb"
########################################
RATIOS=(
    "1to1:0-1:4:2-3:4"
    "2to1:0-2:6:3:2"
    "1to2:0:2:1-3:6"
)

########################################
# 색상
########################################
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; NC='\033[0m'

log()   { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
phase() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}"
}

########################################
# 사전 확인
########################################
check_prerequisites() {
    log "사전 요구사항 확인..."
    [ -d "$YOLO_CGROUP" ]   || { echo "yolo.slice 없음. setup_cgroups.sh 먼저 실행."; exit 1; }
    [ -d "$NODEJS_CGROUP" ] || { echo "nodejs.slice 없음. setup_cgroups.sh 먼저 실행."; exit 1; }
    command -v node &>/dev/null  || { echo "Node.js 미설치."; exit 1; }
    command -v ffmpeg &>/dev/null || warn "ffmpeg 미설치 (필요시 sudo apt install ffmpeg)"

    local gpu_count
    gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
    [ "$gpu_count" -ge 2 ] || warn "GPU ${gpu_count}장 감지 (AI+AI에는 2장 필요)"
    log "GPU ${gpu_count}장 확인 완료"
}

########################################
# CPU 주파수 고정
########################################
set_cpu_fixed() {
    [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ] && \
        echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo
    for cpu in /sys/devices/system/cpu/cpu*/cpufreq; do
        [ -d "$cpu" ] || continue
        echo performance > "$cpu/scaling_governor" 2>/dev/null || true
        echo 3600000 > "$cpu/scaling_max_freq" 2>/dev/null || true
        echo 3600000 > "$cpu/scaling_min_freq" 2>/dev/null || true
    done
    log "CPU freq 고정: performance, 3.6GHz"
}

########################################
# cgroup 비율 재설정
# $1: ai_cpuset  (예: "0-2")
# $2: ai_mem_gb
# $3: nonai_cpuset (예: "3")
# $4: nonai_mem_gb
########################################
configure_cgroup_ratio() {
    local ai_cpuset=$1
    local ai_mem_gb=$2
    local nonai_cpuset=$3
    local nonai_mem_gb=$4

    local ai_mem_bytes=$(( ai_mem_gb * 1024 * 1024 * 1024 ))
    local nonai_mem_bytes=$(( nonai_mem_gb * 1024 * 1024 * 1024 ))

    # yolo.slice (AI 워크로드)
    echo "$ai_cpuset" > "$YOLO_CGROUP/cpuset.cpus"   2>/dev/null || true
    echo "0"          > "$YOLO_CGROUP/cpuset.mems"   2>/dev/null || true
    echo "$ai_mem_bytes" > "$YOLO_CGROUP/memory.max" 2>/dev/null || true

    # nodejs.slice (Non-AI 워크로드)
    echo "$nonai_cpuset" > "$NODEJS_CGROUP/cpuset.cpus"    2>/dev/null || true
    echo "0"             > "$NODEJS_CGROUP/cpuset.mems"    2>/dev/null || true
    echo "$nonai_mem_bytes" > "$NODEJS_CGROUP/memory.max"  2>/dev/null || true

    sleep 1  # cgroup 적용 대기
    log "cgroup 재설정: AI=cpuset${ai_cpuset}/${ai_mem_gb}GB, NonAI=cpuset${nonai_cpuset}/${nonai_mem_gb}GB"
    log "  yolo.slice  cpuset.cpus = $(cat $YOLO_CGROUP/cpuset.cpus 2>/dev/null)"
    log "  nodejs.slice cpuset.cpus = $(cat $NODEJS_CGROUP/cpuset.cpus 2>/dev/null)"
}

########################################
# 전역 PID
########################################
WL_A_PID=""; WL_B_PID=""; CURL_PID=""; NODE_PID=""
HOST_PID="";  CGROUP_PID=""

########################################
# AI 워크로드 시작
########################################
start_ai_workload() {
    local workload_type=$1  # yolo_medium | resnet18 | gpt2
    local gpu_id=$2
    local slice=$3
    local duration=$4
    local pid_var=$5
    local log_file="$LOG_DIR/${workload_type}_gpu${gpu_id}_${slice}.log"

    case "$workload_type" in
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
            ;;
        resnet18|gpt2)
            local script=""
            [ "$workload_type" = "resnet18" ] && script="$WORKLOAD_DIR/resnet18_inference.py"
            [ "$workload_type" = "gpt2" ]     && script="$WORKLOAD_DIR/gpt2_inference.py"
            timeout $((duration + 10)) \
                systemd-run --scope --slice=$slice --uid=$REAL_UID --gid=$REAL_GID \
                bash -c "
                    export CUDA_VISIBLE_DEVICES=$gpu_id
                    source $WORKLOAD_DIR/yolo_venv/bin/activate
                    python3 $script --duration $duration 2>&1
                " > "$log_file" 2>&1 &
            ;;
        *)
            warn "알 수 없는 워크로드: $workload_type"
            return
            ;;
    esac

    eval "${pid_var}=$!"
    log "${workload_type} 시작 (PID: ${!pid_var}, GPU${gpu_id}, ${slice})"
}

########################################
# Node.js 서버 + Heavy 부하
########################################
start_nodejs_server() {
    cd "$WORKLOAD_DIR"
    ( echo $$ > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null || true
      exec node "server_heavy.js" 2>/dev/null ) &
    NODE_PID=$!
    sleep 2
    log "Node.js 서버 시작 (PID: $NODE_PID)"
}

start_nodejs_heavy() {
    local duration=$1
    ( echo $$ > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null || true
      END_TIME=$((SECONDS + duration - 5))
      for worker in {1..4}; do
        ( while [ $SECONDS -lt $END_TIME ]; do
            for i in {1..10}; do
                curl -s --max-time 3 "http://localhost:3000/" >/dev/null 2>&1 &
                curl -s --max-time 3 "http://localhost:3000/heavy?n=30000" >/dev/null 2>&1 &
                curl -s --max-time 3 "http://localhost:3000/prime?limit=5000" >/dev/null 2>&1 &
            done
            wait; sleep 0.1
          done ) &
      done
      wait ) &
    CURL_PID=$!
    log "Node.js Heavy 부하 시작 (PID: $CURL_PID)"
}

########################################
# 로거 시작/대기
########################################
start_loggers() {
    local prefix=$1
    local duration=$2
    python3 "$SCRIPT_DIR/host_logger.py" \
        -o "$LOG_DIR/${prefix}_host.csv" -d "$duration" -i 1 &
    HOST_PID=$!
    python3 "$SCRIPT_DIR/cgroup_logger.py" \
        -o "$LOG_DIR/${prefix}_cgroup.csv" -d "$duration" -i 1 \
        --include-system-io &
    CGROUP_PID=$!
    log "로거 시작 (host=$HOST_PID, cgroup=$CGROUP_PID)"
}

wait_loggers() { wait $HOST_PID $CGROUP_PID 2>/dev/null || true; }

########################################
# 워크로드 정리
########################################
stop_workloads() {
    [ -n "$WL_A_PID" ] && kill $WL_A_PID 2>/dev/null; WL_A_PID=""
    [ -n "$WL_B_PID" ] && kill $WL_B_PID 2>/dev/null; WL_B_PID=""
    [ -n "$CURL_PID" ] && kill $CURL_PID 2>/dev/null; CURL_PID=""
    [ -n "$NODE_PID" ] && kill $NODE_PID 2>/dev/null; NODE_PID=""
    pkill -f "node.*server"       2>/dev/null || true
    pkill -f "resnet18_inference" 2>/dev/null || true
    pkill -f "gpt2_inference"     2>/dev/null || true
    pkill -f "yolo predict"       2>/dev/null || true
    sleep 2
}

drop_caches() {
    sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    log "Page cache dropped"
}

cleanup() { stop_workloads; }
trap cleanup EXIT

########################################
# 메인
########################################
phase "비대칭 자원할당 실험 — Run ${RUN_NUM}"
echo -e "${MAGENTA}비율 3종: 1:1 (equal) / 2:1 (AI-heavy) / 1:2 (NonAI-heavy)${NC}"
echo -e "${MAGENTA}출력: $LOG_DIR${NC}"

check_prerequisites
set_cpu_fixed

mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

# 실험 설정 기록
cat > "$LOG_DIR/config.txt" << EOF
===== Asymmetric Resource Allocation Experiment =====
Date: $(date)
Run: ${RUN_NUM}
Ratios: 1:1 / 2:1 / 1:2 (AI:NonAI CPU cores)
Memory: proportional to core ratio (total 8GB per ratio)

Ratio details:
  1:1  → AI=cpuset 0-1 (2 cores, 4GB) | NonAI=cpuset 2-3 (2 cores, 4GB)
  2:1  → AI=cpuset 0-2 (3 cores, 6GB) | NonAI=cpuset 3   (1 core,  2GB)
  1:2  → AI=cpuset 0   (1 core,  2GB) | NonAI=cpuset 1-3 (3 cores, 6GB)

Workload pairs per ratio:
  YOLO+Node.js, ResNet+Node.js, GPT2+Node.js, YOLO+ResNet

Hardware: Alienware Aurora R12 (i7-11700F 8c/16t, RTX 3060 x2, 32GB DDR4)
EOF
chown $REAL_UID:$REAL_GID "$LOG_DIR/config.txt"

EXPERIMENT_START=$SECONDS

########################################
# Phase 0: Baseline (비율 독립)
########################################
phase "Phase 0: Baseline (Idle) - ${BASELINE_DURATION}s"
start_loggers "baseline" $BASELINE_DURATION
wait_loggers
drop_caches
log "Baseline 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 1-4: Solo (1:1 비율 사용)
########################################
phase "Phase 1-4: Solo Workloads (1:1 equal allocation)"
configure_cgroup_ratio "0-1" 4 "2-3" 4

# Solo AI: YOLO
phase "Phase 1: YOLO Solo - ${WORKLOAD_DURATION}s"
start_loggers "solo_yolo_1to1" $WORKLOAD_DURATION
sleep 2
start_ai_workload "yolo_medium" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

# Solo AI: ResNet
phase "Phase 2: ResNet Solo - ${WORKLOAD_DURATION}s"
start_loggers "solo_resnet_1to1" $WORKLOAD_DURATION
sleep 2
start_ai_workload "resnet18" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

# Solo AI: GPT2
phase "Phase 3: GPT2 Solo - ${WORKLOAD_DURATION}s"
start_loggers "solo_gpt2_1to1" $WORKLOAD_DURATION
sleep 2
start_ai_workload "gpt2" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

# Solo NonAI: Node.js
phase "Phase 4: Node.js Solo - ${WORKLOAD_DURATION}s"
configure_cgroup_ratio "0-1" 4 "2-3" 4  # 1:1로 초기화
start_nodejs_server "server_heavy.js"
start_loggers "solo_nodejs_1to1" $WORKLOAD_DURATION
sleep 2
start_nodejs_heavy $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

########################################
# 비율별 동시실행 실험
########################################
PHASE_NUM=5

for ratio_spec in "${RATIOS[@]}"; do
    # 비율 파싱: label:ai_cpuset:ai_mem_gb:nonai_cpuset:nonai_mem_gb
    IFS=':' read -r ratio_label ai_cpuset ai_mem nonai_cpuset nonai_mem <<< "$ratio_spec"

    phase "=== 비율: ${ratio_label} (AI=cpuset${ai_cpuset}/${ai_mem}GB | NonAI=cpuset${nonai_cpuset}/${nonai_mem}GB) ==="

    configure_cgroup_ratio "$ai_cpuset" "$ai_mem" "$nonai_cpuset" "$nonai_mem"

    # YOLO + Node.js
    phase "Phase ${PHASE_NUM}: YOLO+Node.js [${ratio_label}] - ${WORKLOAD_DURATION}s"
    info "AI(YOLO,GPU0)=cpuset${ai_cpuset}/${ai_mem}GB | NonAI(Node.js)=cpuset${nonai_cpuset}/${nonai_mem}GB"
    start_nodejs_server "server_heavy.js"
    start_loggers "yolo_nodejs_${ratio_label}" $WORKLOAD_DURATION
    sleep 2
    start_ai_workload "yolo_medium" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
    start_nodejs_heavy $WORKLOAD_DURATION
    wait_loggers; stop_workloads; drop_caches
    log "YOLO+Node.js [${ratio_label}] 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
    PHASE_NUM=$((PHASE_NUM + 1))

    # ResNet + Node.js
    phase "Phase ${PHASE_NUM}: ResNet+Node.js [${ratio_label}] - ${WORKLOAD_DURATION}s"
    info "AI(ResNet,GPU0)=cpuset${ai_cpuset}/${ai_mem}GB | NonAI(Node.js)=cpuset${nonai_cpuset}/${nonai_mem}GB"
    start_nodejs_server "server_heavy.js"
    start_loggers "resnet_nodejs_${ratio_label}" $WORKLOAD_DURATION
    sleep 2
    start_ai_workload "resnet18" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
    start_nodejs_heavy $WORKLOAD_DURATION
    wait_loggers; stop_workloads; drop_caches
    log "ResNet+Node.js [${ratio_label}] 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
    PHASE_NUM=$((PHASE_NUM + 1))

    # GPT2 + Node.js
    phase "Phase ${PHASE_NUM}: GPT2+Node.js [${ratio_label}] - ${WORKLOAD_DURATION}s"
    info "AI(GPT2,GPU0)=cpuset${ai_cpuset}/${ai_mem}GB | NonAI(Node.js)=cpuset${nonai_cpuset}/${nonai_mem}GB"
    start_nodejs_server "server_heavy.js"
    start_loggers "gpt2_nodejs_${ratio_label}" $WORKLOAD_DURATION
    sleep 2
    start_ai_workload "gpt2" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
    start_nodejs_heavy $WORKLOAD_DURATION
    wait_loggers; stop_workloads; drop_caches
    log "GPT2+Node.js [${ratio_label}] 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
    PHASE_NUM=$((PHASE_NUM + 1))

    # YOLO + ResNet (AI+AI — GPU-dominant, ratio 영향 거의 없을 것)
    phase "Phase ${PHASE_NUM}: YOLO+ResNet [${ratio_label}] - ${WORKLOAD_DURATION}s"
    info "AI_A(YOLO,GPU0)=yolo.slice | AI_B(ResNet,GPU1)=nodejs.slice [${ratio_label}]"
    start_loggers "yolo_resnet_${ratio_label}" $WORKLOAD_DURATION
    sleep 2
    start_ai_workload "yolo_medium" 0 "yolo.slice"   $WORKLOAD_DURATION "WL_A_PID"
    start_ai_workload "resnet18"    1 "nodejs.slice"  $WORKLOAD_DURATION "WL_B_PID"
    wait_loggers; stop_workloads; drop_caches
    log "YOLO+ResNet [${ratio_label}] 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
    PHASE_NUM=$((PHASE_NUM + 1))
done

########################################
# 완료
########################################
ELAPSED=$((SECONDS - EXPERIMENT_START))
phase "비대칭 실험 완료 — Run ${RUN_NUM}"
log "총 실험 시간: ${ELAPSED}초 (~$((ELAPSED / 60))분)"
log "총 phases: $((PHASE_NUM - 1))"
echo ""
log "생성 파일 목록:"
ls -la "$LOG_DIR"
echo ""
log "다음 단계:"
echo "  1. RPICT 로깅 종료 → data/raw/rpict/phase3_asym_run${RUN_NUM}.csv 저장"
echo "  2. python3 scripts/analysis/extract_phase3_data.py 로 TSV 추출 (--asym 플래그 추가 예정)"
