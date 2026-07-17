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
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${INTEGRATED_LOG_DIR:-$BASE_DIR/data/raw/alienware/phase3_asym_run${RUN_NUM}}"
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
    "5to1:0-4:10:5:2"     # 교수님 6월 메일: "2:1 5:1 등" — AI 5코어/10GB vs NonAI 1코어/2GB
    "1to5:0:2:1-5:10"     # 역방향 극단 비율 (NonAI 우대)
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
    command -v node &>/dev/null    || { echo "Node.js 미설치."; exit 1; }
    command -v setpriv &>/dev/null || { echo "setpriv 미설치 (util-linux 포함, 필수)."; exit 1; }
    ( cd "$WORKLOAD_DIR" && node -e "require('express')" ) 2>/dev/null || {
        echo "ERROR: express 미설치 → cd $WORKLOAD_DIR && npm install express"; exit 1; }
    command -v ffmpeg &>/dev/null || warn "ffmpeg 미설치 (필요시 sudo apt install ffmpeg)"

    local gpu_count
    gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
    [ "$gpu_count" -ge 2 ] || warn "GPU ${gpu_count}장 감지 (AI+AI에는 2장 필요)"
    log "GPU ${gpu_count}장 확인 완료"

    # YOLO 테스트 비디오 (*.mp4는 gitignore — 없으면 YOLO가 에러 루프에 빠짐)
    if [ ! -f "$WORKLOAD_DIR/test_video.mp4" ]; then
        warn "test_video.mp4 없음 — 합성 비디오 자동 생성"
        ffmpeg -y -f lavfi -i "testsrc=duration=60:size=1280x720:rate=30" \
            -pix_fmt yuv420p "$WORKLOAD_DIR/test_video.mp4" &>/dev/null
        chown $REAL_UID:$REAL_GID "$WORKLOAD_DIR/test_video.mp4" 2>/dev/null || true
    fi
    log "test_video.mp4 확인: $(md5sum "$WORKLOAD_DIR/test_video.mp4" | cut -c1-8)..."
}

########################################
# slice 상태 리셋 — systemd scope 잔재/하위 컨트롤러 제거
# (남아 있으면 cgroup v2 internal-node 규칙 때문에 직접 등록이 실패)
########################################
reset_slice() {
    local cg="$CGROUP_ROOT/$1"
    [ -d "$cg" ] || return 0
    local child
    for child in "$cg"/*/; do
        [ -d "$child" ] || continue
        if [ -f "$child/cgroup.procs" ]; then
            while read -r pid; do kill -9 "$pid" 2>/dev/null || true; done < "$child/cgroup.procs" 2>/dev/null
        fi
        sleep 0.3
        rmdir "$child" 2>/dev/null || warn "자식 cgroup 제거 실패: $child"
    done
    echo "-cpuset -memory -cpu -io" > "$cg/cgroup.subtree_control" 2>/dev/null || true
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
# cpuset 표기("0-4", "3", "1-3")에서 코어 수 계산
count_cores() {
    local spec=$1 n=0 part
    local IFS=','
    for part in $spec; do
        if [[ "$part" == *-* ]]; then
            n=$((n + ${part#*-} - ${part%-*} + 1))
        else
            n=$((n + 1))
        fi
    done
    echo $n
}

configure_cgroup_ratio() {
    local ai_cpuset=$1
    local ai_mem_gb=$2
    local nonai_cpuset=$3
    local nonai_mem_gb=$4

    local ai_mem_bytes=$(( ai_mem_gb * 1024 * 1024 * 1024 ))
    local nonai_mem_bytes=$(( nonai_mem_gb * 1024 * 1024 * 1024 ))
    # cpu.max를 코어 수에 비례해 재설정 — setup_cgroups.sh가 걸어둔 200% 쿼터가
    # 남아 있으면 cpuset을 5코어로 늘려도 2코어로 캡되어 비율 실험이 무효가 된다
    local ai_quota=$(( $(count_cores "$ai_cpuset") * 100000 ))
    local nonai_quota=$(( $(count_cores "$nonai_cpuset") * 100000 ))

    # yolo.slice (AI 워크로드)
    echo "$ai_cpuset" > "$YOLO_CGROUP/cpuset.cpus"   2>/dev/null || true
    echo "0"          > "$YOLO_CGROUP/cpuset.mems"   2>/dev/null || true
    echo "$ai_mem_bytes" > "$YOLO_CGROUP/memory.max" 2>/dev/null || true
    echo "$ai_quota 100000" > "$YOLO_CGROUP/cpu.max" 2>/dev/null || true

    # nodejs.slice (Non-AI 워크로드)
    echo "$nonai_cpuset" > "$NODEJS_CGROUP/cpuset.cpus"    2>/dev/null || true
    echo "0"             > "$NODEJS_CGROUP/cpuset.mems"    2>/dev/null || true
    echo "$nonai_mem_bytes" > "$NODEJS_CGROUP/memory.max"  2>/dev/null || true
    echo "$nonai_quota 100000" > "$NODEJS_CGROUP/cpu.max"  2>/dev/null || true

    sleep 1  # cgroup 적용 대기

    # 적용 검증 — 비율 강제가 이 실험의 핵심이므로 불일치 시 즉시 중단
    local got_ai got_nonai
    got_ai=$(cat "$YOLO_CGROUP/cpuset.cpus" 2>/dev/null)
    got_nonai=$(cat "$NODEJS_CGROUP/cpuset.cpus" 2>/dev/null)
    if [ "$got_ai" != "$ai_cpuset" ] || [ "$got_nonai" != "$nonai_cpuset" ]; then
        echo -e "${RED}[FATAL] cpuset 적용 실패: AI '$got_ai'≠'$ai_cpuset' 또는 NonAI '$got_nonai'≠'$nonai_cpuset'${NC}"
        exit 1
    fi
    log "cgroup 재설정: AI=cpuset${ai_cpuset}/${ai_mem_gb}GB/quota$(( ai_quota/1000 ))% | NonAI=cpuset${nonai_cpuset}/${nonai_mem_gb}GB/quota$(( nonai_quota/1000 ))%"
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

    local cg="$CGROUP_ROOT/$slice"
    local inner=""
    case "$workload_type" in
        yolo_medium)
            inner="cd $WORKLOAD_DIR && source yolo_venv/bin/activate && \
END_TIME=\$((SECONDS + $duration - 5)); \
while [ \$SECONDS -lt \$END_TIME ]; do \
  yolo predict model=yolov8m.pt source=test_video.mp4 device=0 verbose=False || true; \
done"
            ;;
        resnet18)
            inner="source $WORKLOAD_DIR/yolo_venv/bin/activate && python3 $WORKLOAD_DIR/resnet18_inference.py --duration $duration"
            ;;
        gpt2)
            inner="source $WORKLOAD_DIR/yolo_venv/bin/activate && python3 $WORKLOAD_DIR/gpt2_inference.py --duration $duration"
            ;;
        *)
            warn "알 수 없는 워크로드: $workload_type"
            return
            ;;
    esac

    # cgroup.procs 직접 등록 ($BASHPID — $$는 메인 스크립트 PID라 절대 금지).
    # systemd-run --slice는 raw cgroup과 충돌하거나 cpuset/cpu.max를 리셋해
    # 비율 강제가 무효화된다 (3-way run1/run2에서 실증된 계열).
    ( if ! echo $BASHPID > "$cg/cgroup.procs" 2>/dev/null; then
          echo "[FATAL] cgroup attach 실패: $cg"
          exit 1
      fi
      exec timeout $((duration + 10)) \
          setpriv --reuid=$REAL_UID --regid=$REAL_GID --init-groups \
          env HOME="/home/$REAL_USER" \
              CUDA_VISIBLE_DEVICES=$gpu_id PYTHONUNBUFFERED=1 \
          bash -c "$inner"
    ) > "$log_file" 2>&1 &

    eval "${pid_var}=$!"
    log "${workload_type} 시작 (PID: ${!pid_var}, GPU${gpu_id}, ${slice})"
}

########################################
# Node.js 서버 + Heavy 부하
########################################
start_nodejs_server() {
    cd "$WORKLOAD_DIR"
    # $BASHPID 필수 — $$는 메인 스크립트를 slice로 옮겨 모든 후속 phase를 오염시킴
    ( if ! echo $BASHPID > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null; then
          echo "[FATAL] nodejs.slice attach 실패 — Node.js가 cgroup 밖에서 실행됨"
          exit 1
      fi
      exec node "server_heavy.js" ) > "$LOG_DIR/nodejs_server.log" 2>&1 &
    NODE_PID=$!
    sleep 2
    if ! kill -0 $NODE_PID 2>/dev/null; then
        warn "Node.js 시작 실패! $LOG_DIR/nodejs_server.log 확인"
    fi
    log "Node.js 서버 시작 (PID: $NODE_PID, nodejs.slice)"
}

start_nodejs_heavy() {
    local duration=$1
    # curl 부하는 외부 클라이언트 역할 — cgroup 밖에서 실행 (등록 금지)
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

# 이전 run 잔재(systemd scope 자식 등) 정리 — 직접 등록의 전제조건
reset_slice "yolo.slice"
reset_slice "nodejs.slice"

set_cpu_fixed

mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

# 실험 설정 기록
cat > "$LOG_DIR/config.txt" << EOF
===== Asymmetric Resource Allocation Experiment =====
Date: $(date)
Run: ${RUN_NUM}
Ratios: 1:1 / 2:1 / 1:2 / 5:1 / 1:5 (AI:NonAI CPU cores)
Memory: proportional to core ratio / cpu.max quota proportional to core count
Execution: direct cgroup.procs registration (no systemd-run), cpuset asserted per ratio

Ratio details:
  1:1  → AI=cpuset 0-1 (2 cores, 4GB) | NonAI=cpuset 2-3 (2 cores, 4GB)
  2:1  → AI=cpuset 0-2 (3 cores, 6GB) | NonAI=cpuset 3   (1 core,  2GB)
  1:2  → AI=cpuset 0   (1 core,  2GB) | NonAI=cpuset 1-3 (3 cores, 6GB)
  5:1  → AI=cpuset 0-4 (5 cores,10GB) | NonAI=cpuset 5   (1 core,  2GB)
  1:5  → AI=cpuset 0   (1 core,  2GB) | NonAI=cpuset 1-5 (5 cores,10GB)

Workload pairs per ratio:
  YOLO+Node.js, ResNet+Node.js, GPT2+Node.js, YOLO+ResNet

Hardware: Alienware Aurora R12 (i7-11700F 8c/16t, RTX 3060 x2, 32GB DDR4)
EOF
chown $REAL_UID:$REAL_GID "$LOG_DIR/config.txt"

########################################
# 스모크 테스트 (~1.5분) — 실패 시 즉시 중단 (장시간 무효 run 방지)
########################################
phase "Phase S: 스모크 테스트"
configure_cgroup_ratio "0-1" 4 "2-3" 4
SMOKE_FAIL=0

info "S1: YOLO (20s)"
start_ai_workload "yolo_medium" 0 "yolo.slice" 20 "WL_A_PID"
sleep 20; stop_workloads
grep -q "FileNotFoundError\|Traceback\|FATAL\|Job failed" "$LOG_DIR/yolo_medium_gpu0_yolo.slice.log" 2>/dev/null \
    && { warn "  ✗ YOLO 실패"; SMOKE_FAIL=1; } \
    || { grep -q "Ultralytics" "$LOG_DIR/yolo_medium_gpu0_yolo.slice.log" 2>/dev/null \
         && log "  ✓ YOLO OK" || { warn "  ✗ YOLO 마커 없음"; SMOKE_FAIL=1; }; }

info "S2: GPT2 (25s)"
start_ai_workload "gpt2" 0 "yolo.slice" 25 "WL_A_PID"
sleep 25; stop_workloads
grep -q "\[GPT-2\]" "$LOG_DIR/gpt2_gpu0_yolo.slice.log" 2>/dev/null \
    && log "  ✓ GPT2 OK" || { warn "  ✗ GPT2 실패"; SMOKE_FAIL=1; }

info "S3: Node.js (12s)"
start_nodejs_server "server_heavy.js"
sleep 3
if curl -s --max-time 3 "http://localhost:3000/" >/dev/null 2>&1 \
   && [ -n "$(cat "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null)" ]; then
    log "  ✓ Node.js OK (응답 + nodejs.slice 등록)"
else
    warn "  ✗ Node.js 실패 → $LOG_DIR/nodejs_server.log"; SMOKE_FAIL=1
fi
stop_workloads

if [ "$SMOKE_FAIL" -ne 0 ]; then
    echo -e "${RED}스모크 테스트 실패 — 본 실험을 시작하지 않습니다.${NC}"
    exit 1
fi
log "스모크 테스트 통과 — 본 실험 시작"
drop_caches; sleep $COOLDOWN

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

# Solo AI: ResNet @GPU1 — AI+AI(YOLO+ResNet) 검증용 디바이스 일치 기준
# (GPU0/GPU1 전력 특성이 달라 GPU0 solo로는 GPU1 배치 검증 불가 — 3-way에서 실증)
phase "Phase 3b: ResNet Solo (GPU1, nodejs.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_resnet_gpu1_1to1" $WORKLOAD_DURATION
sleep 2
start_ai_workload "resnet18" 1 "nodejs.slice" $WORKLOAD_DURATION "WL_B_PID"
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
