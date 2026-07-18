#!/bin/bash
# 공유 코어 co-schedule 실험 (Shared-Core Co-scheduling Experiment)
#
# 목적: Reviewer 2 #3 직접 대응 — "quantify the error this linear assumption
#       would introduce when heterogeneous workloads genuinely share a CPU
#       under shared DVFS"
#
# 설계: 전력 밀도가 다른 두 CPU 워크로드(Node.js crypto vs ffmpeg x264)를
#   같은 cpuset(0-3, 4코어)에서 co-schedule — cgroup 경계는 유지하되(귀속 측정용)
#   코어는 공유 → 진짜 경합. 두 주파수 조건에서 반복:
#     fixed : 3.6GHz 고정, turbo off  (기존 프로토콜과 동일)
#     free  : DVFS/turbo 활성        (R2#3가 명시한 조건)
#
# Phases:
#   P0 baseline_fixed          P4 baseline_free
#   P1 solo_ffmpeg_fixed       P5 solo_ffmpeg_free
#   P2 solo_node_fixed         P6 solo_node_free
#   P3 cosched_fixed           P7 cosched_free
#   (모든 워크로드 phase는 cpuset 0-3 공유, 각 cgroup quota 400%)
#
# 분석: cosched에서 이용률 비례 CPU 분할 vs 같은 조건 solo(-idle) 기준 비교
#   → 공유 코어 + DVFS 환경에서 선형 가정의 오차를 직접 정량화
#
# Usage:
#   sudo -E ./run_experiment_cosched.sh [RUN_NUM]
#   예) sudo -E ./run_experiment_cosched.sh 1   → cosched_run1  (~15분)

set +e

########################################
# sudo 확인
########################################
if [ "$EUID" -ne 0 ]; then
    echo "Error: sudo로 실행해야 합니다."
    echo "Usage: sudo -E $0 [RUN_NUM]"
    exit 1
fi
REAL_UID=${SUDO_UID:-$(id -u)}
REAL_GID=${SUDO_GID:-$(id -g)}
REAL_USER=${SUDO_USER:-$(whoami)}

RUN_NUM=${1:-1}

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${INTEGRATED_LOG_DIR:-$BASE_DIR/data/raw/alienware/cosched_run${RUN_NUM}}"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"

CGROUP_ROOT="/sys/fs/cgroup"
FF_CGROUP="$CGROUP_ROOT/yolo.slice"      # ffmpeg 수용 (기존 slice 재사용 — 로거 호환)
NODE_CGROUP="$CGROUP_ROOT/nodejs.slice"  # Node.js 수용

SHARED_CPUSET="0-3"      # 두 워크로드가 공유하는 4코어
SHARED_QUOTA="400000 100000"

BASELINE_DURATION=60
WORKLOAD_DURATION=90
COOLDOWN=20

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
    command -v node &>/dev/null    || { echo "Node.js 미설치."; exit 1; }
    command -v setpriv &>/dev/null || { echo "setpriv 미설치."; exit 1; }
    command -v ffmpeg &>/dev/null  || { echo "ffmpeg 미설치."; exit 1; }
    ( cd "$WORKLOAD_DIR" && node -e "require('express')" ) 2>/dev/null || {
        echo "ERROR: express 미설치 → cd $WORKLOAD_DIR && npm install express"; exit 1; }
    log "사전 확인 완료 (GPU 불필요 실험)"
}

########################################
# slice 리셋/생성 — systemd에서 분리 후 raw 디렉토리로 소유
########################################
reset_slice() {
    local cg="$CGROUP_ROOT/$1"
    systemctl stop "$1" 2>/dev/null || true
    sleep 0.2
    echo "+cpuset +memory +cpu +io" > "$CGROUP_ROOT/cgroup.subtree_control" 2>/dev/null || true
    mkdir -p "$cg" 2>/dev/null || true
    if [ ! -d "$cg" ]; then
        echo -e "${RED}[FATAL] cgroup 재생성 실패: $cg${NC}"; exit 1
    fi
    local child
    for child in "$cg"/*/; do
        [ -d "$child" ] || continue
        if [ -f "$child/cgroup.procs" ]; then
            while read -r pid; do kill -9 "$pid" 2>/dev/null || true; done < "$child/cgroup.procs" 2>/dev/null
        fi
        sleep 0.3
        rmdir "$child" 2>/dev/null || warn "자식 cgroup 제거 실패: $child"
    done
    local c
    for c in $(cat "$cg/cgroup.subtree_control" 2>/dev/null); do
        echo "-$c" > "$cg/cgroup.subtree_control" 2>/dev/null || true
    done
}

clear_subtree() {
    local cg=$1 c
    for c in $(cat "$cg/cgroup.subtree_control" 2>/dev/null); do
        echo "-$c" > "$cg/cgroup.subtree_control" 2>/dev/null || true
    done
}

attach_self() {
    local cg=$1 c
    if echo $BASHPID > "$cg/cgroup.procs" 2>/dev/null; then
        return 0
    fi
    echo "[WARN] attach 1차 실패: $cg"
    echo "  -- subtree=[$(cat $cg/cgroup.subtree_control 2>&1)] children=[$(ls -d $cg/*/ 2>/dev/null | tr '\n' ' ')]"
    for c in $(cat "$cg/cgroup.subtree_control" 2>/dev/null); do
        echo "-$c" > "$cg/cgroup.subtree_control" 2>/dev/null || true
    done
    sleep 0.5
    echo $BASHPID > "$cg/cgroup.procs" && echo "[INFO] attach 재시도 성공"
}

########################################
# 공유 cpuset 설정 — 두 slice 모두 0-3, quota 400%
########################################
configure_shared() {
    local cg
    for cg in "$FF_CGROUP" "$NODE_CGROUP"; do
        echo "$SHARED_CPUSET" > "$cg/cpuset.cpus"  2>/dev/null || true
        echo "0"              > "$cg/cpuset.mems"  2>/dev/null || true
        echo "4294967296"     > "$cg/memory.max"   2>/dev/null || true
        echo "$SHARED_QUOTA"  > "$cg/cpu.max"      2>/dev/null || true
    done
    sleep 1
    local a b
    a=$(cat "$FF_CGROUP/cpuset.cpus" 2>/dev/null)
    b=$(cat "$NODE_CGROUP/cpuset.cpus" 2>/dev/null)
    if [ "$a" != "$SHARED_CPUSET" ] || [ "$b" != "$SHARED_CPUSET" ]; then
        echo -e "${RED}[FATAL] 공유 cpuset 적용 실패: ff='$a' node='$b' (기대 $SHARED_CPUSET)${NC}"
        exit 1
    fi
    log "공유 cpuset 적용: 양쪽 slice 모두 cpuset=$SHARED_CPUSET, quota=400%, 4GB"
}

########################################
# CPU 주파수 모드
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
    log "CPU freq: FIXED (performance, 3.6GHz, turbo off)"
}

set_cpu_free() {
    [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ] && \
        echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo
    for cpu in /sys/devices/system/cpu/cpu*/cpufreq; do
        [ -d "$cpu" ] || continue
        echo powersave > "$cpu/scaling_governor" 2>/dev/null || true
        cat "$cpu/cpuinfo_min_freq" > "$cpu/scaling_min_freq" 2>/dev/null || true
        cat "$cpu/cpuinfo_max_freq" > "$cpu/scaling_max_freq" 2>/dev/null || true
    done
    log "CPU freq: FREE (powersave governor, DVFS+turbo 활성)"
}

########################################
# 워크로드
########################################
WL_FF_PID=""; CURL_PID=""; NODE_PID=""
HOST_PID=""; CGROUP_PID=""

start_ffmpeg_ws() {   # $1=duration $2=로그 프리픽스
    local duration=$1
    local prefix=${2:-solo}
    clear_subtree "$FF_CGROUP"
    ( if ! attach_self "$FF_CGROUP"; then
          echo "[FATAL] yolo.slice(ffmpeg) attach 실패"
          exit 1
      fi
      exec timeout $((duration + 10)) env PYTHONUNBUFFERED=1 \
          python3 "$WORKLOAD_DIR/ffmpeg_encode.py" --duration $duration
    ) > "$LOG_DIR/${prefix}_ffmpeg.log" 2>&1 &
    WL_FF_PID=$!
    log "ffmpeg 시작 (PID: $WL_FF_PID, yolo.slice)"
}

start_nodejs_ws() {   # $1=duration
    local duration=$1
    cd "$WORKLOAD_DIR"
    clear_subtree "$NODE_CGROUP"
    ( if ! attach_self "$NODE_CGROUP"; then
          echo "[FATAL] nodejs.slice attach 실패"
          exit 1
      fi
      exec node "server_heavy.js" ) > "$LOG_DIR/nodejs_server.log" 2>&1 &
    NODE_PID=$!
    sleep 2
    if ! kill -0 $NODE_PID 2>/dev/null; then
        echo -e "${RED}[ABORT] Node.js 시작 실패 — 실험 중단${NC}"
        cat "$LOG_DIR/nodejs_server.log"
        exit 1
    fi
    log "Node.js 서버 시작 (PID: $NODE_PID, nodejs.slice)"
    # 부하 클라이언트 (cgroup 밖)
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

start_loggers() {
    local prefix=$1; local duration=$2
    python3 "$SCRIPT_DIR/host_logger.py" \
        -o "$LOG_DIR/${prefix}_host.csv" -d "$duration" -i 1 &
    HOST_PID=$!
    python3 "$SCRIPT_DIR/cgroup_logger.py" \
        -c yolo.slice nodejs.slice \
        -o "$LOG_DIR/${prefix}_cgroup.csv" -d "$duration" -i 1 \
        --include-system-io &
    CGROUP_PID=$!
    log "로거 시작 (host=$HOST_PID, cgroup=$CGROUP_PID)"
}
wait_loggers() { wait $HOST_PID $CGROUP_PID 2>/dev/null || true; }

stop_workloads() {
    [ -n "$WL_FF_PID" ] && kill $WL_FF_PID 2>/dev/null; WL_FF_PID=""
    [ -n "$CURL_PID" ] && kill $CURL_PID 2>/dev/null; CURL_PID=""
    [ -n "$NODE_PID" ] && kill $NODE_PID 2>/dev/null; NODE_PID=""
    pkill -f "node.*server"    2>/dev/null || true
    pkill -f "ffmpeg_encode"   2>/dev/null || true
    pkill -f "ffmpeg.*testsrc" 2>/dev/null || true
    sleep 2
}
drop_caches() { sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true; }
cleanup() { stop_workloads; set_cpu_fixed; }
trap cleanup EXIT

########################################
# 메인
########################################
phase "공유 코어 co-schedule 실험 — Run ${RUN_NUM} (~15분)"
echo -e "${MAGENTA}Node.js + ffmpeg를 같은 cpuset(${SHARED_CPUSET})에서 경합 실행${NC}"
echo -e "${MAGENTA}주파수 2조건: fixed(3.6GHz) / free(DVFS+turbo)${NC}"
echo -e "${MAGENTA}출력: $LOG_DIR${NC}"

check_prerequisites
reset_slice "yolo.slice"
reset_slice "nodejs.slice"
configure_shared
set_cpu_fixed

mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

cat > "$LOG_DIR/config.txt" << EOF
===== Shared-Core Co-scheduling Experiment (R2#3) =====
Date: $(date)
Run: ${RUN_NUM}

Both cgroups share cpuset ${SHARED_CPUSET} (4 cores), quota 400% each, 4GB each:
  yolo.slice   → ffmpeg x264 (multi-thread, ~370% demand on 4 cores)
  nodejs.slice → Node.js Heavy (single-thread, ~100% demand)
  Combined demand ~470% > 400% capacity → genuine core contention.

Frequency conditions:
  fixed: performance governor, 3.6GHz pinned, turbo off (기존 프로토콜)
  free : powersave governor, full DVFS range + turbo (R2#3 명시 조건)

Phases: baseline/solo_ffmpeg/solo_node/cosched × {fixed, free}
Purpose: quantify utilization-proportional CPU attribution error under
genuine shared-core contention with and without DVFS.
Execution: direct cgroup.procs registration (systemd-detached raw cgroups)
EOF
chown $REAL_UID:$REAL_GID "$LOG_DIR/config.txt"

# ── 스모크 (~30s) ──
phase "Phase S: 스모크"
start_ffmpeg_ws 10 "smoke"
sleep 10; stop_workloads
grep -q "\[ffmpeg\] 시작" "$LOG_DIR/smoke_ffmpeg.log" 2>/dev/null \
    && log "  ✓ ffmpeg OK" || { echo -e "${RED}스모크 실패(ffmpeg) — 중단${NC}"; exit 1; }
start_nodejs_ws 12
sleep 5
if curl -s --max-time 3 "http://localhost:3000/" >/dev/null 2>&1 \
   && [ -n "$(cat "$NODE_CGROUP/cgroup.procs" 2>/dev/null)" ]; then
    log "  ✓ Node.js OK"
else
    echo -e "${RED}스모크 실패(Node.js) — 중단${NC}"; exit 1
fi
stop_workloads; drop_caches; sleep $COOLDOWN

EXPERIMENT_START=$SECONDS

run_condition() {   # $1=fixed|free
    local cond=$1
    if [ "$cond" = "fixed" ]; then set_cpu_fixed; else set_cpu_free; fi
    sleep 3

    phase "baseline_${cond} - ${BASELINE_DURATION}s"
    start_loggers "baseline_${cond}" $BASELINE_DURATION
    wait_loggers; drop_caches; sleep $COOLDOWN

    phase "solo_ffmpeg_${cond} (cpuset ${SHARED_CPUSET}) - ${WORKLOAD_DURATION}s"
    start_loggers "solo_ffmpeg_${cond}" $WORKLOAD_DURATION
    sleep 2
    start_ffmpeg_ws $WORKLOAD_DURATION "solo_${cond}"
    wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

    phase "solo_node_${cond} (cpuset ${SHARED_CPUSET}) - ${WORKLOAD_DURATION}s"
    start_nodejs_ws $WORKLOAD_DURATION
    start_loggers "solo_node_${cond}" $WORKLOAD_DURATION
    sleep 2
    wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

    phase "cosched_${cond}: Node.js + ffmpeg 같은 코어 경합 - ${WORKLOAD_DURATION}s"
    start_nodejs_ws $WORKLOAD_DURATION
    start_loggers "cosched_${cond}" $WORKLOAD_DURATION
    sleep 2
    start_ffmpeg_ws $WORKLOAD_DURATION "cosched_${cond}"
    wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN
}

run_condition "fixed"
run_condition "free"

set_cpu_fixed   # 원상 복구

ELAPSED=$((SECONDS - EXPERIMENT_START))
phase "co-schedule 실험 완료 — Run ${RUN_NUM}"
log "총 실험 시간: ${ELAPSED}초 (~$((ELAPSED / 60))분)"
ls -la "$LOG_DIR"
echo ""
log "다음 단계:"
echo "  1. RPICT 종료 → data/raw/rpict/cosched_run${RUN_NUM}.csv 저장"
echo "  2. 반복: sudo -E $0 $((RUN_NUM + 1))  (3회 권장)"
echo "  3. 분석: 이용률 비례 분할 오차 (fixed vs free 조건 비교)"
