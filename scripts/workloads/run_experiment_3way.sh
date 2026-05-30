#!/bin/bash
# 3-way 동시실행 실험 (Three-Workload Concurrent Experiment)
#
# 목적: 2-way에서 3-way로 확장했을 때 에너지 귀속 모델의 일반성 검증
#       "조합을 다 해보기보다 한두 케이스 정도로 별 차이 없다는 정도면 족함" — 교수님
#
# 실험 케이스 (2가지):
#   Case 1: YOLO(GPU0) + ResNet(GPU1) + Node.js(CPU)  — AI+AI+NonAI
#   Case 2: YOLO(GPU0) + GPT2(GPU1)   + ffmpeg(CPU)   — AI+AI+NonAI (다른 NonAI)
#
# cgroup 구성:
#   yolo.slice    → Workload A (AI, GPU0): cpuset 0-1, 4GB
#   nodejs.slice  → Workload B (AI, GPU1): cpuset 2-3, 4GB
#   work.slice    → Workload C (NonAI, CPU only): cpuset 4-5, 4GB   ← 신규 생성
#
# Usage:
#   sudo -E ./run_experiment_3way.sh [RUN_NUM]
#   예) sudo -E ./run_experiment_3way.sh 1    → phase3_3way_run1

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
LOG_DIR="${INTEGRATED_LOG_DIR:-$BASE_DIR/data/raw/alienware/phase3_3way_run${RUN_NUM}}"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"

CGROUP_ROOT="/sys/fs/cgroup"
YOLO_CGROUP="$CGROUP_ROOT/yolo.slice"      # Workload A (AI)
NODEJS_CGROUP="$CGROUP_ROOT/nodejs.slice"   # Workload B (AI in 3-way)
WORK_CGROUP="$CGROUP_ROOT/work.slice"       # Workload C (NonAI) — 신규

########################################
# 타이밍
########################################
BASELINE_DURATION=60
WORKLOAD_DURATION=90
COOLDOWN=20

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
# work.slice cgroup 생성 및 설정
########################################
setup_work_cgroup() {
    log "work.slice cgroup 설정 중..."

    # work.slice 디렉토리 생성
    if [ ! -d "$WORK_CGROUP" ]; then
        mkdir -p "$WORK_CGROUP"
        log "work.slice 생성: $WORK_CGROUP"
    fi

    # cgroup v2 컨트롤러 활성화
    local parent_cgroup="$CGROUP_ROOT"
    if ! grep -q "cpuset" "$parent_cgroup/cgroup.controllers" 2>/dev/null; then
        warn "cpuset 컨트롤러가 루트에 없습니다."
    fi

    # subtree_control 활성화 (부모에서)
    echo "+cpuset +memory +cpu +io" > "$parent_cgroup/cgroup.subtree_control" 2>/dev/null || true

    # work.slice 설정: cpuset 4-5 (2코어), 4GB
    echo "0"         > "$WORK_CGROUP/cpuset.mems"   2>/dev/null || warn "cpuset.mems 설정 실패"
    echo "4-5"       > "$WORK_CGROUP/cpuset.cpus"   2>/dev/null || warn "cpuset.cpus 설정 실패"
    echo "4294967296" > "$WORK_CGROUP/memory.max"   2>/dev/null || warn "memory.max 설정 실패 (4GB)"
    # memory.max = 4 * 1024^3 = 4294967296

    sleep 1
    log "work.slice 설정 완료:"
    log "  cpuset.cpus = $(cat $WORK_CGROUP/cpuset.cpus 2>/dev/null || echo 'N/A')"
    log "  memory.max  = $(cat $WORK_CGROUP/memory.max  2>/dev/null || echo 'N/A')"
}

########################################
# 사전 확인
########################################
check_prerequisites() {
    log "사전 요구사항 확인..."
    [ -d "$YOLO_CGROUP" ]   || { echo "yolo.slice 없음. setup_cgroups.sh 먼저 실행."; exit 1; }
    [ -d "$NODEJS_CGROUP" ] || { echo "nodejs.slice 없음. setup_cgroups.sh 먼저 실행."; exit 1; }
    command -v node &>/dev/null   || { echo "Node.js 미설치."; exit 1; }
    command -v ffmpeg &>/dev/null || warn "ffmpeg 미설치 (Case 2 건너뜀, sudo apt install ffmpeg)"

    local gpu_count
    gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
    if [ "$gpu_count" -lt 2 ]; then
        echo "ERROR: GPU 2장 필요 (현재 ${gpu_count}장). 3-way AI+AI+NonAI 불가."
        exit 1
    fi
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
# 전역 PID
########################################
WL_A_PID=""; WL_B_PID=""; WL_C_PID=""
CURL_PID=""; NODE_PID=""
HOST_PID=""; CGROUP_PID=""

########################################
# AI 워크로드 시작 (yolo.slice 또는 nodejs.slice)
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
# Node.js Heavy (work.slice)
########################################
start_nodejs_3way() {
    local duration=$1

    # 서버를 work.slice에서 실행
    cd "$WORKLOAD_DIR"
    ( echo $$ > "$WORK_CGROUP/cgroup.procs" 2>/dev/null || true
      exec node "server_heavy.js" 2>/dev/null ) &
    NODE_PID=$!
    sleep 2
    log "Node.js 서버 시작 (PID: $NODE_PID, work.slice)"

    # Heavy 부하 (curl은 cgroup 밖에서 실행 — HTTP 클라이언트)
    ( END_TIME=$((SECONDS + duration - 5))
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
# ffmpeg Heavy (work.slice)
########################################
start_ffmpeg_3way() {
    local duration=$1
    local log_file="$LOG_DIR/ffmpeg_work.log"

    timeout $((duration + 10)) \
        systemd-run --scope --slice=work.slice --uid=$REAL_UID --gid=$REAL_GID \
        bash -c "
            source $WORKLOAD_DIR/yolo_venv/bin/activate
            python3 $WORKLOAD_DIR/ffmpeg_encode.py --duration $duration 2>&1
        " > "$log_file" 2>&1 &
    WL_C_PID=$!
    log "ffmpeg 시작 (PID: $WL_C_PID, work.slice, log: $log_file)"
}

########################################
# 로거 시작 (cgroup_logger에 work.slice 포함)
########################################
start_loggers() {
    local prefix=$1
    local duration=$2
    python3 "$SCRIPT_DIR/host_logger.py" \
        -o "$LOG_DIR/${prefix}_host.csv" -d "$duration" -i 1 &
    HOST_PID=$!
    # cgroup_logger는 yolo.slice + nodejs.slice + work.slice 모두 로깅
    python3 "$SCRIPT_DIR/cgroup_logger.py" \
        -o "$LOG_DIR/${prefix}_cgroup.csv" -d "$duration" -i 1 \
        --include-system-io &
    CGROUP_PID=$!
    log "로거 시작 (host=$HOST_PID, cgroup=$CGROUP_PID)"
}

wait_loggers() { wait $HOST_PID $CGROUP_PID 2>/dev/null || true; }

########################################
# 정리
########################################
stop_workloads() {
    [ -n "$WL_A_PID" ] && kill $WL_A_PID 2>/dev/null; WL_A_PID=""
    [ -n "$WL_B_PID" ] && kill $WL_B_PID 2>/dev/null; WL_B_PID=""
    [ -n "$WL_C_PID" ] && kill $WL_C_PID 2>/dev/null; WL_C_PID=""
    [ -n "$CURL_PID" ] && kill $CURL_PID 2>/dev/null; CURL_PID=""
    [ -n "$NODE_PID" ] && kill $NODE_PID 2>/dev/null; NODE_PID=""
    pkill -f "node.*server"       2>/dev/null || true
    pkill -f "resnet18_inference" 2>/dev/null || true
    pkill -f "gpt2_inference"     2>/dev/null || true
    pkill -f "yolo predict"       2>/dev/null || true
    pkill -f "ffmpeg_encode"      2>/dev/null || true
    pkill -f "ffmpeg.*testsrc"    2>/dev/null || true
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
phase "3-way 동시실행 실험 — Run ${RUN_NUM}"
echo -e "${MAGENTA}Case 1: YOLO(GPU0) + ResNet(GPU1) + Node.js(CPU)${NC}"
echo -e "${MAGENTA}Case 2: YOLO(GPU0) + GPT2(GPU1)   + ffmpeg(CPU)${NC}"
echo -e "${MAGENTA}cgroup: yolo.slice(0-1) | nodejs.slice(2-3) | work.slice(4-5)${NC}"
echo -e "${MAGENTA}출력: $LOG_DIR${NC}"

check_prerequisites
set_cpu_fixed
setup_work_cgroup

mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

# 실험 설정 기록
cat > "$LOG_DIR/config.txt" << EOF
===== 3-Way Concurrent Workload Experiment =====
Date: $(date)
Run: ${RUN_NUM}

cgroup allocation (equal 3-way, 2 cores / 4GB each):
  yolo.slice   → cpuset 0-1, 4GB  (Workload A: AI, GPU0)
  nodejs.slice → cpuset 2-3, 4GB  (Workload B: AI, GPU1)
  work.slice   → cpuset 4-5, 4GB  (Workload C: NonAI, CPU only)

Cases:
  Case 1: YOLO(yolo.slice,GPU0) + ResNet(nodejs.slice,GPU1) + Node.js(work.slice)
  Case 2: YOLO(yolo.slice,GPU0) + GPT2(nodejs.slice,GPU1)   + ffmpeg(work.slice)

Purpose:
  Extend 2-way energy attribution model to 3-way
  Verify model accuracy under 3-workload concurrent execution
  Expected: similar per-workload energy as in 2-way (energy profiles preserved)

Hardware: Alienware Aurora R12 (i7-11700F 8c/16t, RTX 3060 x2, 32GB DDR4)
EOF
chown $REAL_UID:$REAL_GID "$LOG_DIR/config.txt"

EXPERIMENT_START=$SECONDS

########################################
# Phase 0: Baseline
########################################
phase "Phase 0: Baseline (Idle) - ${BASELINE_DURATION}s"
start_loggers "baseline" $BASELINE_DURATION
wait_loggers
drop_caches
log "Baseline 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 1-3: Solo (2-way 결과와의 비교용)
########################################
phase "Phase 1: YOLO Solo (GPU0, yolo.slice) - ${WORKLOAD_DURATION}s"
info "2-way 실험 solo와 비교: 같아야 함 (에너지 프로파일 보존 확인)"
start_loggers "solo_yolo" $WORKLOAD_DURATION
sleep 2
start_ai_workload "yolo_medium" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

phase "Phase 2: ResNet Solo (GPU0, yolo.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_resnet" $WORKLOAD_DURATION
sleep 2
start_ai_workload "resnet18" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

phase "Phase 3: Node.js Solo (work.slice) - ${WORKLOAD_DURATION}s"
start_nodejs_3way $WORKLOAD_DURATION
start_loggers "solo_nodejs" $WORKLOAD_DURATION
sleep 2
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

########################################
# Case 1: YOLO + ResNet + Node.js (AI+AI+NonAI)
########################################
phase "Phase 4 [Case 1]: YOLO(GPU0) + ResNet(GPU1) + Node.js(CPU) — 3-way"
info "yolo.slice(cpuset 0-1) | nodejs.slice(cpuset 2-3) | work.slice(cpuset 4-5)"

start_nodejs_3way $WORKLOAD_DURATION
start_loggers "case1_yolo_resnet_nodejs" $WORKLOAD_DURATION
sleep 2

# Workload A: YOLO → GPU0, yolo.slice
start_ai_workload "yolo_medium" 0 "yolo.slice"   $WORKLOAD_DURATION "WL_A_PID"
# Workload B: ResNet → GPU1, nodejs.slice
start_ai_workload "resnet18"    1 "nodejs.slice"  $WORKLOAD_DURATION "WL_B_PID"
# Workload C: Node.js → CPU, work.slice (already started above)

wait_loggers
stop_workloads
drop_caches
log "Case 1 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Case 2: YOLO + GPT2 + ffmpeg (AI+AI+NonAI, 다른 NonAI)
########################################
if command -v ffmpeg &>/dev/null; then
    phase "Phase 5 [Case 2]: YOLO(GPU0) + GPT2(GPU1) + ffmpeg(CPU) — 3-way"
    info "yolo.slice(cpuset 0-1) | nodejs.slice(cpuset 2-3) | work.slice(cpuset 4-5)"

    start_loggers "case2_yolo_gpt2_ffmpeg" $WORKLOAD_DURATION
    sleep 2

    # Workload A: YOLO → GPU0, yolo.slice
    start_ai_workload "yolo_medium" 0 "yolo.slice"   $WORKLOAD_DURATION "WL_A_PID"
    # Workload B: GPT2 → GPU1, nodejs.slice
    start_ai_workload "gpt2"        1 "nodejs.slice"  $WORKLOAD_DURATION "WL_B_PID"
    # Workload C: ffmpeg → CPU, work.slice
    start_ffmpeg_3way $WORKLOAD_DURATION

    wait_loggers
    stop_workloads
    drop_caches
    log "Case 2 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
else
    warn "ffmpeg 미설치 → Case 2 (ffmpeg) 건너뜀"
    warn "  설치: sudo apt install ffmpeg 후 재실행"
fi

########################################
# 완료
########################################
ELAPSED=$((SECONDS - EXPERIMENT_START))
phase "3-way 실험 완료 — Run ${RUN_NUM}"
log "총 실험 시간: ${ELAPSED}초 (~$((ELAPSED / 60))분)"
echo ""
log "생성된 파일:"
ls -la "$LOG_DIR"
echo ""
log "다음 단계:"
echo "  1. RPICT 로깅 종료 → data/raw/rpict/phase3_3way_run${RUN_NUM}.csv 저장"
echo "  2. 분석:"
echo "     - Case 1 vs 2-way(YOLO+ResNet) 비교 → 3-way에서 에너지 프로파일 보존 확인"
echo "     - Case 2 vs 2-way(YOLO+GPT2) 비교   → ffmpeg 추가 시 AI 워크로드 영향 확인"
echo ""
log "실험 완료: phase3_3way_run${RUN_NUM}"
