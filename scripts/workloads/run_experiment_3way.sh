#!/bin/bash
# 3-way 동시실행 실험 (Three-Workload Concurrent Experiment)
#
# 목적: 2-way에서 3-way로 확장했을 때 에너지 귀속 모델의 일반성 검증
#       "조합을 다 해보기보다 한두 케이스 정도로 별 차이 없다는 정도면 족함" — 교수님
#
# 실험 케이스 (3가지):
#   Case 1: YOLO(GPU0) + ResNet(GPU1) + Node.js(CPU)  — AI+AI+NonAI (3-way)
#   Case 2: YOLO(GPU0) + GPT2(GPU1)   + ffmpeg(CPU)   — AI+AI+NonAI (3-way, 다른 NonAI)
#   Case 3: YOLO(GPU0) + GPT2(GPU1) + Node.js(CPU) + ffmpeg(CPU) — 4-way
#           (교수님 3월 메일: "3개 혹은 4개의 워크로드를 동시에")
#
# cgroup 구성:
#   yolo.slice    → Workload A (AI, GPU0): cpuset 0-1, 4GB
#   nodejs.slice  → Workload B (AI, GPU1): cpuset 2-3, 4GB
#   work.slice    → Workload C (NonAI, CPU only): cpuset 4-5, 4GB   ← 신규 생성
#   work2.slice   → Workload D (NonAI, CPU only): cpuset 6-7, 4GB   ← 4-way용
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
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${INTEGRATED_LOG_DIR:-$BASE_DIR/data/raw/alienware/phase3_3way_run${RUN_NUM}}"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"

CGROUP_ROOT="/sys/fs/cgroup"
YOLO_CGROUP="$CGROUP_ROOT/yolo.slice"      # Workload A (AI)
NODEJS_CGROUP="$CGROUP_ROOT/nodejs.slice"   # Workload B (AI in 3-way)
WORK_CGROUP="$CGROUP_ROOT/work.slice"       # Workload C (NonAI) — 신규
WORK2_CGROUP="$CGROUP_ROOT/work2.slice"     # Workload D (NonAI) — 4-way Case 3용

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

    # work.slice 설정: cpuset 4-5 (2코어), 4GB, cpu.max 200% (setup_cgroups.sh와 동일)
    echo "0"         > "$WORK_CGROUP/cpuset.mems"   2>/dev/null || warn "cpuset.mems 설정 실패"
    echo "4-5"       > "$WORK_CGROUP/cpuset.cpus"   2>/dev/null || warn "cpuset.cpus 설정 실패"
    echo "4294967296" > "$WORK_CGROUP/memory.max"   2>/dev/null || warn "memory.max 설정 실패 (4GB)"
    echo "200000 100000" > "$WORK_CGROUP/cpu.max"   2>/dev/null || warn "cpu.max 설정 실패"
    # memory.max = 4 * 1024^3 = 4294967296

    sleep 1
    log "work.slice 설정 완료:"
    log "  cpuset.cpus = $(cat $WORK_CGROUP/cpuset.cpus 2>/dev/null || echo 'N/A')"
    log "  memory.max  = $(cat $WORK_CGROUP/memory.max  2>/dev/null || echo 'N/A')"
}

########################################
# work2.slice cgroup 생성 및 설정 (4-way Case 3용)
########################################
setup_work2_cgroup() {
    log "work2.slice cgroup 설정 중..."

    if [ ! -d "$WORK2_CGROUP" ]; then
        mkdir -p "$WORK2_CGROUP"
        log "work2.slice 생성: $WORK2_CGROUP"
    fi

    # work2.slice 설정: cpuset 6-7 (2코어), 4GB, cpu.max 200% (setup_cgroups.sh와 동일)
    echo "0"          > "$WORK2_CGROUP/cpuset.mems" 2>/dev/null || warn "cpuset.mems 설정 실패"
    echo "6-7"        > "$WORK2_CGROUP/cpuset.cpus" 2>/dev/null || warn "cpuset.cpus 설정 실패"
    echo "4294967296" > "$WORK2_CGROUP/memory.max"  2>/dev/null || warn "memory.max 설정 실패 (4GB)"
    echo "200000 100000" > "$WORK2_CGROUP/cpu.max"  2>/dev/null || warn "cpu.max 설정 실패"

    sleep 1
    log "work2.slice 설정 완료:"
    log "  cpuset.cpus = $(cat $WORK2_CGROUP/cpuset.cpus 2>/dev/null || echo 'N/A')"
    log "  memory.max  = $(cat $WORK2_CGROUP/memory.max  2>/dev/null || echo 'N/A')"
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

    # YOLO 테스트 비디오 확인 (*.mp4는 .gitignore라 clone에 미포함 — 없으면 YOLO가
    # FileNotFoundError 무한 루프에 빠져 GPU가 놀게 됨. run1에서 실제 발생한 문제)
    if [ ! -f "$WORKLOAD_DIR/test_video.mp4" ]; then
        warn "test_video.mp4 없음 — 합성 비디오 자동 생성 (기존 실험 원본이 있으면 교체 권장)"
        if command -v ffmpeg &>/dev/null; then
            ffmpeg -y -f lavfi -i "testsrc=duration=60:size=1280x720:rate=30" \
                -pix_fmt yuv420p "$WORKLOAD_DIR/test_video.mp4" &>/dev/null
            chown $REAL_UID:$REAL_GID "$WORKLOAD_DIR/test_video.mp4" 2>/dev/null || true
            log "합성 test_video.mp4 생성 완료 (1280x720@30fps, 60s testsrc)"
        else
            echo "ERROR: test_video.mp4 없음 + ffmpeg 미설치 → YOLO 실행 불가"
            exit 1
        fi
    fi
    log "test_video.mp4 확인: $(md5sum "$WORKLOAD_DIR/test_video.mp4" | cut -c1-8)... ($(du -h "$WORKLOAD_DIR/test_video.mp4" | cut -f1))"
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
    local slice=${2:-work.slice}    # 기본 work.slice, 4-way에서는 work2.slice
    local prefix=${3:-ffmpeg}       # 로그 파일명 충돌 방지용 phase 프리픽스
    local cg="$CGROUP_ROOT/$slice"
    local log_file="$LOG_DIR/${prefix}_ffmpeg_${slice%.slice}.log"

    # systemd-run --slice는 (1) 프로세스가 직접 등록된 raw cgroup과 충돌해
    # "Job failed"로 죽고 (2) slice 재생성 시 cpuset 제한을 리셋한다 (run1에서
    # 실제 발생: work.slice 실패 + work2.slice 891% CPU).
    # → Node.js와 동일하게 cgroup.procs 직접 등록 방식 사용.
    # ffmpeg_encode.py는 표준 라이브러리만 사용하므로 venv 불필요.
    ( echo $$ > "$cg/cgroup.procs" 2>/dev/null || true
      exec timeout $((duration + 10)) \
          python3 "$WORKLOAD_DIR/ffmpeg_encode.py" --duration $duration
    ) > "$log_file" 2>&1 &
    WL_C_PID=$!
    log "ffmpeg 시작 (PID: $WL_C_PID, $slice, log: $log_file)"
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
    # cgroup_logger 기본값은 yolo.slice+nodejs.slice뿐이므로
    # work.slice/work2.slice를 반드시 명시해야 함 (미지정 시 3/4번째 워크로드 데이터 누락)
    python3 "$SCRIPT_DIR/cgroup_logger.py" \
        -c yolo.slice nodejs.slice work.slice work2.slice \
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
setup_work2_cgroup

mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

# 실험 설정 기록
cat > "$LOG_DIR/config.txt" << EOF
===== 3-Way Concurrent Workload Experiment =====
Date: $(date)
Run: ${RUN_NUM}

cgroup allocation (equal, 2 cores / 4GB each):
  yolo.slice   → cpuset 0-1, 4GB  (Workload A: AI, GPU0)
  nodejs.slice → cpuset 2-3, 4GB  (Workload B: AI, GPU1)
  work.slice   → cpuset 4-5, 4GB  (Workload C: NonAI, CPU only)
  work2.slice  → cpuset 6-7, 4GB  (Workload D: NonAI, CPU only, 4-way)

Cases:
  Case 1: YOLO(yolo.slice,GPU0) + ResNet(nodejs.slice,GPU1) + Node.js(work.slice)
  Case 2: YOLO(yolo.slice,GPU0) + GPT2(nodejs.slice,GPU1)   + ffmpeg(work.slice)
  Case 3: YOLO(yolo.slice,GPU0) + GPT2(nodejs.slice,GPU1)
          + Node.js(work.slice) + ffmpeg(work2.slice)        — 4-way

Purpose:
  Extend 2-way energy attribution model to 3-way and 4-way
  Verify model accuracy under 3/4-workload concurrent execution
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

phase "Phase 3b: GPT2 Solo (GPU0, yolo.slice) - ${WORKLOAD_DURATION}s"
info "Case 2/3 검증용 solo 기준값 (동일 run 내 확보)"
start_loggers "solo_gpt2" $WORKLOAD_DURATION
sleep 2
start_ai_workload "gpt2" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

if command -v ffmpeg &>/dev/null; then
    phase "Phase 3c: ffmpeg Solo (work.slice) - ${WORKLOAD_DURATION}s"
    info "Case 2/3 검증용 solo 기준값 (동일 run 내 확보)"
    start_loggers "solo_ffmpeg" $WORKLOAD_DURATION
    sleep 2
    start_ffmpeg_3way $WORKLOAD_DURATION "work.slice" "solo"
    wait_loggers; stop_workloads; drop_caches
    sleep $COOLDOWN
fi

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
    start_ffmpeg_3way $WORKLOAD_DURATION "work.slice" "case2"

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
# Case 3: YOLO + GPT2 + Node.js + ffmpeg (4-way)
# 교수님 3월 메일: "3개 혹은 4개의 워크로드를 동시에"
########################################
if command -v ffmpeg &>/dev/null; then
    phase "Phase 6 [Case 3]: YOLO(GPU0) + GPT2(GPU1) + Node.js(CPU) + ffmpeg(CPU) — 4-way"
    info "yolo.slice(0-1) | nodejs.slice(2-3) | work.slice(4-5) | work2.slice(6-7)"

    start_nodejs_3way $WORKLOAD_DURATION
    start_loggers "case3_yolo_gpt2_nodejs_ffmpeg" $WORKLOAD_DURATION
    sleep 2

    # Workload A: YOLO → GPU0, yolo.slice
    start_ai_workload "yolo_medium" 0 "yolo.slice"   $WORKLOAD_DURATION "WL_A_PID"
    # Workload B: GPT2 → GPU1, nodejs.slice
    start_ai_workload "gpt2"        1 "nodejs.slice"  $WORKLOAD_DURATION "WL_B_PID"
    # Workload C: Node.js → CPU, work.slice (위에서 시작)
    # Workload D: ffmpeg → CPU, work2.slice
    start_ffmpeg_3way $WORKLOAD_DURATION "work2.slice" "case3"

    wait_loggers
    stop_workloads
    drop_caches
    log "Case 3 (4-way) 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
else
    warn "ffmpeg 미설치 → Case 3 (4-way) 건너뜀"
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
