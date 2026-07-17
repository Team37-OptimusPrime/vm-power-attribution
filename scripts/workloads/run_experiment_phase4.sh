#!/bin/bash
# Phase 4: 워크로드 확장 실험 (Workload Expansion Experiment)
#
# 목적: 워크로드를 4종 → 9종으로 확장 (교수님 6월 메일 1순위)
#       기존 5종(YOLO/ResNet-GPU/GPT2/GEMM/Node.js)은 phase3 데이터 재사용,
#       본 스크립트는 신규 4종의 solo + 신규 concurrent 조합을 수집한다.
#
# 신규 워크로드 (자원 카테고리 커버리지):
#   W5: ResNet-18 CPU 추론   — CPU-AI      (AI ≠ GPU-dominant 케이스)
#   W7: ffmpeg x264 인코딩   — CPU-NonAI
#   W8: stress-ng --vm       — Memory-NonAI
#   W9: fio randrw           — I/O-NonAI   (+ bursty: iodepth 1→8→32 램프)
#
# 신규 concurrent 조합 (검증 포인트):
#   C1: ResNet-CPU + Node.js — 같은 CPU 자원을 AI/NonAI가 분할
#   C2: ffmpeg + Node.js     — CPU-NonAI 쌍의 CPU 이용률 비례 분할
#   C3: YOLO(GPU0) + fio     — 스토리지 계수의 concurrent 검증
#   C4: GPT2(GPU0) + stress  — 메모리 할당 귀속 + GPU 공존
#
# cgroup 구성 (기존 phase3와 동일한 2-slice 구조):
#   yolo.slice   → cpuset 0-1, 4GB (워크로드 A)
#   nodejs.slice → cpuset 2-3, 4GB (워크로드 B)
#
# 실행 방식: 모든 워크로드는 cgroup.procs 직접 등록($BASHPID)으로 실행한다.
#   systemd-run --slice와 raw cgroup을 혼용하면 이전 run 상태에 따라
#   "Job failed"/attach 실패가 비결정적으로 발생한다 (3-way run1/run2에서 실증).
#
# Usage:
#   sudo -E ./run_experiment_phase4.sh [RUN_NUM]
#   예) sudo -E ./run_experiment_phase4.sh 1    → phase4_expand_run1

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
LOG_DIR="${INTEGRATED_LOG_DIR:-$BASE_DIR/data/raw/alienware/phase4_expand_run${RUN_NUM}}"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"

CGROUP_ROOT="/sys/fs/cgroup"
YOLO_CGROUP="$CGROUP_ROOT/yolo.slice"
NODEJS_CGROUP="$CGROUP_ROOT/nodejs.slice"

FIO_FILE="/var/tmp/fio_phase4.dat"   # NVMe 시스템 디스크 상의 테스트 파일

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
# 사전 확인
########################################
check_prerequisites() {
    log "사전 요구사항 확인..."
    [ -d "$YOLO_CGROUP" ]   || { echo "yolo.slice 없음. setup_cgroups.sh 먼저 실행."; exit 1; }
    [ -d "$NODEJS_CGROUP" ] || { echo "nodejs.slice 없음. setup_cgroups.sh 먼저 실행."; exit 1; }
    command -v node &>/dev/null      || { echo "Node.js 미설치."; exit 1; }
    command -v setpriv &>/dev/null   || { echo "setpriv 미설치 (util-linux 포함, 필수)."; exit 1; }
    # express 확인 (node_modules는 gitignore — fresh clone엔 없음)
    ( cd "$WORKLOAD_DIR" && node -e "require('express')" ) 2>/dev/null || {
        echo "ERROR: express 미설치 → cd $WORKLOAD_DIR && npm install express"; exit 1; }
    command -v ffmpeg &>/dev/null    || { echo "ffmpeg 미설치. sudo apt install ffmpeg"; exit 1; }
    command -v stress-ng &>/dev/null || { echo "stress-ng 미설치. sudo apt install stress-ng"; exit 1; }
    command -v fio &>/dev/null       || { echo "fio 미설치. sudo apt install fio"; exit 1; }

    local gpu_count
    gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
    [ "$gpu_count" -lt 1 ] && { echo "ERROR: GPU 1장 이상 필요 (C3/C4)"; exit 1; }
    log "GPU ${gpu_count}장 확인"

    # YOLO 테스트 비디오 확인 (*.mp4는 .gitignore라 clone에 미포함)
    if [ ! -f "$WORKLOAD_DIR/test_video.mp4" ]; then
        warn "test_video.mp4 없음 — 합성 비디오 자동 생성 (기존 실험 원본이 있으면 교체 권장)"
        ffmpeg -y -f lavfi -i "testsrc=duration=60:size=1280x720:rate=30" \
            -pix_fmt yuv420p "$WORKLOAD_DIR/test_video.mp4" &>/dev/null
        chown $REAL_UID:$REAL_GID "$WORKLOAD_DIR/test_video.mp4" 2>/dev/null || true
    fi
    log "test_video.mp4 확인: $(md5sum "$WORKLOAD_DIR/test_video.mp4" | cut -c1-8)... ($(du -h "$WORKLOAD_DIR/test_video.mp4" | cut -f1))"

    # fio 테스트 파일 사전 생성 (측정 중 파일 레이아웃 I/O 방지)
    if [ ! -f "$FIO_FILE" ]; then
        log "fio 테스트 파일 사전 생성 (2GB)..."
        fio --name=prep --filename="$FIO_FILE" --size=2G --rw=write --bs=1M \
            --direct=1 --create_only=1 &>/dev/null || \
            fio --name=prep --filename="$FIO_FILE" --size=2G --rw=write --bs=1M \
                --direct=1 --runtime=1 --time_based &>/dev/null
    fi
    log "fio 파일 준비 완료: $FIO_FILE"
}

########################################
# slice 상태 리셋 — 이전 run 잔재 제거
# (systemd scope 자식 + 하위 컨트롤러가 남아 있으면 cgroup v2의
#  internal-node 규칙 때문에 프로세스 직접 등록이 실패한다)
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
        rmdir "$child" 2>/dev/null || warn "자식 cgroup 제거 실패: $child (프로세스 잔존?)"
    done
    # systemd가 이 slice를 유닛으로 알고 있으면 명시적으로 내려서 재간섭 차단
    systemctl stop "$1" 2>/dev/null || true
    # 켜져 있는 모든 하위 컨트롤러 해제 (pids 포함 — 하드코딩 목록은 pids를 놓쳤었음)
    local c
    for c in $(cat "$cg/cgroup.subtree_control" 2>/dev/null); do
        echo "-$c" > "$cg/cgroup.subtree_control" 2>/dev/null || true
    done
}

########################################
# attach 가드 — subtree 컨트롤러가 하나라도 켜져 있으면 cgroup v2
# internal-node 규칙 때문에 cgroup.procs 쓰기가 EBUSY로 실패한다.
# systemd가 slice가 비워질 때마다 +pids를 다시 켜므로(TasksAccounting),
# 모든 attach 직전에 호출해 무력화한다. (asym run1~3 실패 원인 실증)
########################################
clear_subtree() {
    local cg=$1 c
    for c in $(cat "$cg/cgroup.subtree_control" 2>/dev/null); do
        echo "-$c" > "$cg/cgroup.subtree_control" 2>/dev/null || true
    done
}

########################################
# attach_self <cgroup경로> — 서브셸 안에서 자기 자신($BASHPID)을 등록.
# 1차 실패 시 상태를 로그에 남기고 subtree 컨트롤러를 정리한 뒤 1회 재시도.
# (asym run1~3에서 attach가 실행 중에만 일시적으로 실패하는 현상 실증 —
#  2차도 실패하면 errno가 로그에 그대로 노출된다)
########################################
attach_self() {
    local cg=$1 c
    if echo $BASHPID > "$cg/cgroup.procs" 2>/dev/null; then
        return 0
    fi
    echo "[WARN] attach 1차 실패: $cg"
    echo "  -- subtree=[$(cat $cg/cgroup.subtree_control 2>&1)]"
    echo "  -- children=[$(ls -d $cg/*/ 2>/dev/null | tr '\n' ' ')]"
    echo "  -- cpus.eff=[$(cat $cg/cpuset.cpus.effective 2>&1)] type=[$(cat $cg/cgroup.type 2>&1)]"
    for c in $(cat "$cg/cgroup.subtree_control" 2>/dev/null); do
        echo "-$c" > "$cg/cgroup.subtree_control" 2>/dev/null || true
    done
    sleep 0.5
    echo $BASHPID > "$cg/cgroup.procs" && echo "[INFO] attach 재시도 성공"
}



########################################
# cgroup 자원 설정 (phase3와 동일: 2코어/4GB + cpu.max 200%)
########################################
setup_cgroups_equal() {
    echo "+cpuset +memory +cpu +io" > "$CGROUP_ROOT/cgroup.subtree_control" 2>/dev/null || true

    echo "0"          > "$YOLO_CGROUP/cpuset.mems" 2>/dev/null || true
    echo "0-1"        > "$YOLO_CGROUP/cpuset.cpus" 2>/dev/null || true
    echo "4294967296" > "$YOLO_CGROUP/memory.max"  2>/dev/null || true
    echo "200000 100000" > "$YOLO_CGROUP/cpu.max"  2>/dev/null || true

    echo "0"          > "$NODEJS_CGROUP/cpuset.mems" 2>/dev/null || true
    echo "2-3"        > "$NODEJS_CGROUP/cpuset.cpus" 2>/dev/null || true
    echo "4294967296" > "$NODEJS_CGROUP/memory.max"  2>/dev/null || true
    echo "200000 100000" > "$NODEJS_CGROUP/cpu.max"  2>/dev/null || true

    log "cgroup 설정: yolo.slice(0-1, 4GB, 200%) | nodejs.slice(2-3, 4GB, 200%)"
}

########################################
# CPU 주파수 고정 (phase3_fixed 규약과 동일)
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
WL_A_PID=""; WL_B_PID=""
CURL_PID=""; NODE_PID=""
HOST_PID=""; CGROUP_PID=""

########################################
# 공통: cgroup 직접 등록 실행기
#   run_in_cgroup <slice> <log_file> <pid_var> <duration> <as_user:0|1> <cmd...>
#   - $BASHPID 사용 ($$는 메인 스크립트 PID — 절대 금지)
#   - setpriv: PAM 없이 uid 강하 → cgroup 소속 유지
########################################
run_in_cgroup() {
    local slice=$1; local log_file=$2; local pid_var=$3
    local duration=$4; local as_user=$5
    shift 5
    local cg="$CGROUP_ROOT/$slice"

    if [ "$as_user" = "1" ]; then
        clear_subtree "$cg"
    ( if ! attach_self "$cg"; then
              echo "[FATAL] cgroup attach 실패: $cg"
              exit 1
          fi
          exec timeout $((duration + 10)) \
              setpriv --reuid=$REAL_UID --regid=$REAL_GID --init-groups \
              env HOME="/home/$REAL_USER" PYTHONUNBUFFERED=1 "$@"
        ) > "$log_file" 2>&1 &
    else
        clear_subtree "$cg"
    ( if ! attach_self "$cg"; then
              echo "[FATAL] cgroup attach 실패: $cg"
              exit 1
          fi
          exec timeout $((duration + 10)) env PYTHONUNBUFFERED=1 "$@"
        ) > "$log_file" 2>&1 &
    fi
    eval "${pid_var}=$!"
}

########################################
# 워크로드 시작 함수들
########################################

# ResNet-18 CPU 추론 (CPU-AI)
start_resnet_cpu() {
    local slice=$1; local duration=$2
    run_in_cgroup "$slice" "$LOG_DIR/resnet_cpu_${slice%.slice}.log" WL_A_PID $duration 1 \
        env CUDA_VISIBLE_DEVICES="" \
        bash -c "source $WORKLOAD_DIR/yolo_venv/bin/activate && python3 $WORKLOAD_DIR/resnet18_inference.py --duration $duration --device cpu"
    log "ResNet-CPU 시작 (PID: $WL_A_PID, $slice)"
}

# GPU AI 워크로드 (yolo_medium | gpt2)
start_ai_gpu() {
    local workload_type=$1; local gpu_id=$2; local slice=$3; local duration=$4
    local log_file="$LOG_DIR/${workload_type}_gpu${gpu_id}_${slice%.slice}.log"
    local inner=""
    case "$workload_type" in
        yolo_medium)
            inner="cd $WORKLOAD_DIR && source yolo_venv/bin/activate && \
END_TIME=\$((SECONDS + $duration - 5)); \
while [ \$SECONDS -lt \$END_TIME ]; do \
  yolo predict model=yolov8m.pt source=test_video.mp4 device=0 verbose=False || true; \
done"
            ;;
        gpt2)
            inner="source $WORKLOAD_DIR/yolo_venv/bin/activate && python3 $WORKLOAD_DIR/gpt2_inference.py --duration $duration"
            ;;
        llm)
            # W10: 현대 소형 LLM (기본 Qwen2.5-3B-Instruct) — WITH_LLM=1일 때만 사용
            inner="source $WORKLOAD_DIR/yolo_venv/bin/activate && python3 $WORKLOAD_DIR/llm_inference.py --duration $duration"
            ;;
    esac
    run_in_cgroup "$slice" "$log_file" WL_A_PID $duration 1 \
        env CUDA_VISIBLE_DEVICES=$gpu_id bash -c "$inner"
    log "${workload_type} 시작 (PID: $WL_A_PID, GPU${gpu_id}, $slice)"
}

# ffmpeg x264 (CPU-NonAI) — 표준 라이브러리만 사용, venv/유저 강하 불필요
start_ffmpeg() {
    local slice=$1; local duration=$2; local prefix=${3:-solo}
    run_in_cgroup "$slice" "$LOG_DIR/${prefix}_ffmpeg_${slice%.slice}.log" WL_A_PID $duration 0 \
        python3 "$WORKLOAD_DIR/ffmpeg_encode.py" --duration $duration
    log "ffmpeg 시작 (PID: $WL_A_PID, $slice)"
}

# stress-ng 메모리 (Memory-NonAI): 2 workers × 1.5GB = 3GB (4GB limit 내)
start_stress_mem() {
    local slice=$1; local duration=$2; local prefix=${3:-solo}
    run_in_cgroup "$slice" "$LOG_DIR/${prefix}_stressmem_${slice%.slice}.log" WL_B_PID $duration 0 \
        stress-ng --vm 2 --vm-bytes 1536M --vm-keep --timeout ${duration}s
    log "stress-ng 메모리 시작 (PID: $WL_B_PID, $slice, 2×1.5GB)"
}

# fio randrw (I/O-NonAI)
start_fio_randrw() {
    local slice=$1; local duration=$2; local prefix=${3:-solo}
    run_in_cgroup "$slice" "$LOG_DIR/${prefix}_fio_randrw_${slice%.slice}.log" WL_B_PID $duration 0 \
        fio --name=randrw --filename="$FIO_FILE" --size=2G \
            --rw=randrw --rwmixread=70 --bs=4k --iodepth=32 --direct=1 \
            --time_based --runtime=${duration} --output-format=json \
            --output="$LOG_DIR/${prefix}_fio_randrw.json"
    log "fio randrw 시작 (PID: $WL_B_PID, $slice, 4k/QD32/R70W30)"
}

# fio bursty (I/O-NonAI): iodepth 1 → 8 → 32 램프 (각 duration/3초) — R1#3 bursty 대응
start_fio_bursty() {
    local slice=$1; local duration=$2
    local seg=$((duration / 3))
    run_in_cgroup "$slice" "$LOG_DIR/fio_bursty_${slice%.slice}.log" WL_B_PID $((duration + 5)) 0 \
        bash -c "
            for qd in 1 8 32; do
                fio --name=burst_qd\$qd --filename=$FIO_FILE --size=2G \
                    --rw=randrw --rwmixread=70 --bs=4k --iodepth=\$qd --direct=1 \
                    --time_based --runtime=$seg --output-format=json \
                    --output=$LOG_DIR/fio_bursty_qd\${qd}.json 2>&1
            done
        "
    log "fio bursty 시작 (PID: $WL_B_PID, $slice, QD 1→8→32 × ${seg}s)"
}

# Node.js Heavy (nodejs.slice)
start_nodejs() {
    local duration=$1
    cd "$WORKLOAD_DIR"
    clear_subtree "$NODEJS_CGROUP"
    ( if ! attach_self "$NODEJS_CGROUP"; then
          echo "[FATAL] nodejs.slice attach 실패 — Node.js가 cgroup 밖에서 실행됨"
          echo "-- 진단: subtree_control=[$(cat $NODEJS_CGROUP/cgroup.subtree_control 2>&1)]"
          echo "-- cpus.effective=[$(cat $NODEJS_CGROUP/cpuset.cpus.effective 2>&1)]"
          echo "-- type=[$(cat $NODEJS_CGROUP/cgroup.type 2>&1)] procs=[$(cat $NODEJS_CGROUP/cgroup.procs 2>&1 | tr '\n' ' ')]"
          echo "-- children=[$(ls -d $NODEJS_CGROUP/*/ 2>/dev/null | tr '\n' ' ')]"
          exit 1
      fi
      exec node "server_heavy.js" ) > "$LOG_DIR/nodejs_server.log" 2>&1 &
    NODE_PID=$!
    sleep 2
    if ! kill -0 $NODE_PID 2>/dev/null; then
        warn "Node.js 시작 실패! $LOG_DIR/nodejs_server.log 확인"
    fi
    log "Node.js 서버 시작 (PID: $NODE_PID, nodejs.slice)"

    # Heavy 부하 (curl은 cgroup 밖 — 외부 클라이언트 역할)
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
# 로거
########################################
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

########################################
# 정리
########################################
stop_workloads() {
    [ -n "$WL_A_PID" ] && kill $WL_A_PID 2>/dev/null; WL_A_PID=""
    [ -n "$WL_B_PID" ] && kill $WL_B_PID 2>/dev/null; WL_B_PID=""
    [ -n "$CURL_PID" ] && kill $CURL_PID 2>/dev/null; CURL_PID=""
    [ -n "$NODE_PID" ] && kill $NODE_PID 2>/dev/null; NODE_PID=""
    pkill -f "node.*server"       2>/dev/null || true
    pkill -f "resnet18_inference" 2>/dev/null || true
    pkill -f "gpt2_inference"     2>/dev/null || true
    pkill -f "llm_inference"      2>/dev/null || true
    pkill -f "yolo predict"       2>/dev/null || true
    pkill -f "ffmpeg_encode"      2>/dev/null || true
    pkill -f "ffmpeg.*testsrc"    2>/dev/null || true
    pkill -f "stress-ng"          2>/dev/null || true
    pkill -f "fio --name"         2>/dev/null || true
    sleep 2
}

drop_caches() {
    sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    log "Page cache dropped"
}

cleanup() { stop_workloads; }
trap cleanup EXIT

########################################
# 스모크 테스트 — 본 실험 전 각 워크로드 시험 가동 (~2분)
# 하나라도 실패하면 즉시 중단 → 30분짜리 무효 run 방지
########################################
smoke_check() {  # $1=로그파일 $2=성공마커 $3=이름
    if grep -q "FileNotFoundError\|Traceback\|FATAL\|Job failed" "$1" 2>/dev/null; then
        warn "  ✗ $3 실패 (에러 발견) → $1"
        return 1
    fi
    if ! grep -q "$2" "$1" 2>/dev/null; then
        warn "  ✗ $3 실패 (성공 마커 '$2' 없음) → $1"
        return 1
    fi
    log "  ✓ $3 OK"
    return 0
}

smoke_test() {
    phase "Phase S: 워크로드 스모크 테스트 (~2분) — 실패 시 즉시 중단"
    local fail=0

    info "S1: ResNet-CPU (yolo.slice, 15s)"
    start_resnet_cpu "yolo.slice" 15
    sleep 15; stop_workloads
    smoke_check "$LOG_DIR/resnet_cpu_yolo.log" "\[ResNet18\]" "ResNet-CPU" || fail=1

    info "S2: YOLO (GPU0, yolo.slice, 20s)"
    start_ai_gpu "yolo_medium" 0 "yolo.slice" 20
    sleep 20; stop_workloads
    smoke_check "$LOG_DIR/yolo_medium_gpu0_yolo.log" "Ultralytics" "YOLO" || fail=1

    info "S3: GPT2 (GPU0, yolo.slice, 25s)"
    start_ai_gpu "gpt2" 0 "yolo.slice" 25
    sleep 25; stop_workloads
    smoke_check "$LOG_DIR/gpt2_gpu0_yolo.log" "\[GPT-2\]" "GPT2" || fail=1

    info "S4: ffmpeg (yolo.slice, 12s)"
    start_ffmpeg "yolo.slice" 12 "smoke"
    sleep 12; stop_workloads
    smoke_check "$LOG_DIR/smoke_ffmpeg_yolo.log" "\[ffmpeg\] 시작" "ffmpeg" || fail=1

    info "S5: stress-ng (nodejs.slice, 10s)"
    start_stress_mem "nodejs.slice" 10 "smoke"
    sleep 10; stop_workloads
    smoke_check "$LOG_DIR/smoke_stressmem_nodejs.log" "stress-ng" "stress-ng" || fail=1

    info "S6: fio randrw (nodejs.slice, 10s)"
    start_fio_randrw "nodejs.slice" 10 "smoke"
    sleep 12; stop_workloads
    [ -s "$LOG_DIR/smoke_fio_randrw.json" ] && log "  ✓ fio OK" || { warn "  ✗ fio 실패 (json 출력 없음)"; fail=1; }

    if [ "${WITH_LLM:-0}" = "1" ]; then
        info "S6b: 최신 LLM Qwen2.5-3B (GPU0, yolo.slice, 30s — 캐시 사전 필수)"
        start_ai_gpu "llm" 0 "yolo.slice" 30
        sleep 30; stop_workloads
        smoke_check "$LOG_DIR/llm_gpu0_yolo.log" "\[LLM\]" "LLM" || fail=1
    fi

    info "S7: Node.js (nodejs.slice, 12s)"
    start_nodejs 12
    sleep 5
    if curl -s --max-time 3 "http://localhost:3000/" >/dev/null 2>&1 \
       && [ -n "$(cat "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null)" ]; then
        log "  ✓ Node.js OK (응답 + nodejs.slice 등록 확인)"
    else
        warn "  ✗ Node.js 실패 → $LOG_DIR/nodejs_server.log"
        fail=1
    fi
    sleep 7; stop_workloads

    if [ "$fail" -ne 0 ]; then
        echo ""
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}스모크 테스트 실패 — 본 실험을 시작하지 않습니다.${NC}"
        echo -e "${RED}위 로그를 확인하고 문제 해결 후 재실행하세요.${NC}"
        echo -e "${RED}========================================${NC}"
        exit 1
    fi
    log "스모크 테스트 전체 통과 — 본 실험 시작"
    drop_caches
    sleep $COOLDOWN
}

########################################
# 메인
########################################
phase "Phase 4: 워크로드 확장 실험 — Run ${RUN_NUM}"
echo -e "${MAGENTA}신규 4종 solo + bursty + 신규 concurrent 4쌍${NC}"
echo -e "${MAGENTA}출력: $LOG_DIR${NC}"

check_prerequisites

# 이전 run 잔재 정리 — 반드시 setup 전에
reset_slice "yolo.slice"
reset_slice "nodejs.slice"

set_cpu_fixed
setup_cgroups_equal

mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

# 실험 설정 기록 (논문 재현성 명세의 근거 — R2#4)
cat > "$LOG_DIR/config.txt" << EOF
===== Phase 4: Workload Expansion Experiment =====
Date: $(date)
Run: ${RUN_NUM}

cgroup allocation (equal, 2 cores / 4GB / cpu.max 200% each):
  yolo.slice   → cpuset 0-1, 4GB  (Workload A)
  nodejs.slice → cpuset 2-3, 4GB  (Workload B)
CPU frequency: fixed 3.6GHz, turbo off, performance governor
Execution: direct cgroup.procs registration (no systemd-run)

New workloads:
  W5 ResNet-18 CPU inference : torchvision resnet18, batch=32, 3x224x224, device=cpu
  W7 ffmpeg x264 encode      : lavfi testsrc 1920x1080@30fps -> null, preset medium
  W8 stress-ng memory        : --vm 2 --vm-bytes 1536M --vm-keep (3GB total)
  W9 fio randrw              : bs=4k iodepth=32 rwmixread=70 direct=1 file=2GB NVMe
  W9b fio bursty             : same, iodepth ramp 1 -> 8 -> 32 (30s each)

test_video.mp4 md5: $(md5sum "$WORKLOAD_DIR/test_video.mp4" | cut -d' ' -f1)

Solo phases: solo_resnet_cpu / solo_ffmpeg / solo_stressmem / solo_fio_randrw /
             solo_fio_bursty / solo_nodejs / solo_yolo(GPU0) / solo_gpt2(GPU0)
Concurrent pairs:
  C1 resnetcpu_nodejs : ResNet-CPU(yolo.slice) + Node.js(nodejs.slice)
  C2 ffmpeg_nodejs    : ffmpeg(yolo.slice) + Node.js(nodejs.slice)
  C3 yolo_fio         : YOLO(GPU0,yolo.slice) + fio(nodejs.slice)
  C4 gpt2_stressmem   : GPT2(GPU0,yolo.slice) + stress(nodejs.slice)

Hardware: Alienware Aurora R12 (i7-11700KF 8c/16t, RTX 3060 x2, 32GB DDR4,
          Samsung SSD 980 500GB NVMe)
Observation: ${WORKLOAD_DURATION}s per phase, first/last 10s trimmed in analysis
EOF
chown $REAL_UID:$REAL_GID "$LOG_DIR/config.txt"

# 본 실험 전 스모크 테스트 — 실패 시 여기서 중단
smoke_test

EXPERIMENT_START=$SECONDS

########################################
# Phase 0: Baseline
########################################
phase "Phase 0: Baseline (Idle) - ${BASELINE_DURATION}s"
start_loggers "baseline" $BASELINE_DURATION
wait_loggers
drop_caches; sleep $COOLDOWN

########################################
# Solo phases
########################################
phase "Solo 1/8: ResNet-CPU (yolo.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_resnet_cpu" $WORKLOAD_DURATION
sleep 2
start_resnet_cpu "yolo.slice" $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Solo 2/8: ffmpeg (yolo.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_ffmpeg" $WORKLOAD_DURATION
sleep 2
start_ffmpeg "yolo.slice" $WORKLOAD_DURATION "solo"
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Solo 3/8: stress-ng memory (nodejs.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_stressmem" $WORKLOAD_DURATION
sleep 2
start_stress_mem "nodejs.slice" $WORKLOAD_DURATION "solo"
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Solo 4/8: fio randrw (nodejs.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_fio_randrw" $WORKLOAD_DURATION
sleep 2
start_fio_randrw "nodejs.slice" $WORKLOAD_DURATION "solo"
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Solo 5/8: fio bursty QD1→8→32 (nodejs.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_fio_bursty" $WORKLOAD_DURATION
sleep 2
start_fio_bursty "nodejs.slice" $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Solo 6/8: Node.js Heavy (nodejs.slice) - ${WORKLOAD_DURATION}s"
start_nodejs $WORKLOAD_DURATION
start_loggers "solo_nodejs" $WORKLOAD_DURATION
sleep 2
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Solo 7/8: YOLO (GPU0, yolo.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_yolo" $WORKLOAD_DURATION
sleep 2
start_ai_gpu "yolo_medium" 0 "yolo.slice" $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Solo 8/8: GPT2 (GPU0, yolo.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_gpt2" $WORKLOAD_DURATION
sleep 2
start_ai_gpu "gpt2" 0 "yolo.slice" $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

# W10 (옵션): 현대 소형 LLM — WITH_LLM=1 sudo -E ./run_experiment_phase4.sh 로 활성화
if [ "${WITH_LLM:-0}" = "1" ]; then
    phase "Solo 9: 최신 LLM Qwen2.5-3B (GPU0, yolo.slice) - ${WORKLOAD_DURATION}s"
    start_loggers "solo_llm" $WORKLOAD_DURATION
    sleep 2
    start_ai_gpu "llm" 0 "yolo.slice" $WORKLOAD_DURATION
    wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN
fi

########################################
# Concurrent pairs
########################################
phase "Pair C1: ResNet-CPU + Node.js — CPU를 AI/NonAI가 분할"
start_nodejs $WORKLOAD_DURATION
start_loggers "C1_resnetcpu_nodejs" $WORKLOAD_DURATION
sleep 2
start_resnet_cpu "yolo.slice" $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Pair C2: ffmpeg + Node.js — CPU-NonAI 쌍"
start_nodejs $WORKLOAD_DURATION
start_loggers "C2_ffmpeg_nodejs" $WORKLOAD_DURATION
sleep 2
start_ffmpeg "yolo.slice" $WORKLOAD_DURATION "C2"
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Pair C3: YOLO(GPU0) + fio randrw — GPU + I/O"
start_loggers "C3_yolo_fio" $WORKLOAD_DURATION
sleep 2
start_ai_gpu "yolo_medium" 0 "yolo.slice" $WORKLOAD_DURATION
start_fio_randrw "nodejs.slice" $WORKLOAD_DURATION "C3"
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Pair C4: GPT2(GPU0) + stress-ng memory — GPU + Memory"
start_loggers "C4_gpt2_stressmem" $WORKLOAD_DURATION
sleep 2
start_ai_gpu "gpt2" 0 "yolo.slice" $WORKLOAD_DURATION
start_stress_mem "nodejs.slice" $WORKLOAD_DURATION "C4"
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

# W10 (옵션): 최신 LLM + Node.js — 현대 LLM의 concurrent 귀속 검증
if [ "${WITH_LLM:-0}" = "1" ]; then
    phase "Pair C5: LLM Qwen2.5-3B(GPU0) + Node.js — 최신 LLM + NonAI"
    start_nodejs $WORKLOAD_DURATION
    start_loggers "C5_llm_nodejs" $WORKLOAD_DURATION
    sleep 2
    start_ai_gpu "llm" 0 "yolo.slice" $WORKLOAD_DURATION
    wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN
fi

########################################
# 완료
########################################
ELAPSED=$((SECONDS - EXPERIMENT_START))
phase "Phase 4 실험 완료 — Run ${RUN_NUM}"
log "총 실험 시간: ${ELAPSED}초 (~$((ELAPSED / 60))분)"
echo ""
log "생성된 파일:"
ls -la "$LOG_DIR"
echo ""
log "다음 단계:"
echo "  1. RPICT 로깅 종료 → data/raw/rpict/phase4_expand_run${RUN_NUM}.csv 저장"
echo "  2. 5회 반복: sudo -E $0 $((RUN_NUM + 1))"
echo "  3. 분석: 9-워크로드 에너지 구조 표 + 신규 쌍 귀속 오차 (extract_phase4_data.py)"
echo ""
log "실험 완료: phase4_expand_run${RUN_NUM}"
