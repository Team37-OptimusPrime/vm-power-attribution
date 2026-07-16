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
# cgroup 자원 설정 (phase3와 동일: 2코어/4GB 씩)
########################################
setup_cgroups_equal() {
    echo "+cpuset +memory +cpu +io" > "$CGROUP_ROOT/cgroup.subtree_control" 2>/dev/null || true

    echo "0"          > "$YOLO_CGROUP/cpuset.mems" 2>/dev/null || true
    echo "0-1"        > "$YOLO_CGROUP/cpuset.cpus" 2>/dev/null || true
    echo "4294967296" > "$YOLO_CGROUP/memory.max"  2>/dev/null || true

    echo "0"          > "$NODEJS_CGROUP/cpuset.mems" 2>/dev/null || true
    echo "2-3"        > "$NODEJS_CGROUP/cpuset.cpus" 2>/dev/null || true
    echo "4294967296" > "$NODEJS_CGROUP/memory.max"  2>/dev/null || true

    log "cgroup 설정: yolo.slice(0-1, 4GB) | nodejs.slice(2-3, 4GB)"
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
# 워크로드 시작 함수들
########################################

# ResNet-18 CPU 추론 (CPU-AI)
start_resnet_cpu() {
    local slice=$1; local duration=$2
    local log_file="$LOG_DIR/resnet_cpu_${slice%.slice}.log"
    timeout $((duration + 10)) \
        systemd-run --scope --slice=$slice --uid=$REAL_UID --gid=$REAL_GID \
        bash -c "
            export CUDA_VISIBLE_DEVICES=''
            source $WORKLOAD_DIR/yolo_venv/bin/activate
            python3 $WORKLOAD_DIR/resnet18_inference.py --duration $duration --device cpu 2>&1
        " > "$log_file" 2>&1 &
    WL_A_PID=$!
    log "ResNet-CPU 시작 (PID: $WL_A_PID, $slice)"
}

# GPU AI 워크로드 (yolo_medium | gpt2) — phase3와 동일 패턴
start_ai_gpu() {
    local workload_type=$1; local gpu_id=$2; local slice=$3; local duration=$4
    local log_file="$LOG_DIR/${workload_type}_gpu${gpu_id}_${slice%.slice}.log"
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
        gpt2)
            timeout $((duration + 10)) \
                systemd-run --scope --slice=$slice --uid=$REAL_UID --gid=$REAL_GID \
                bash -c "
                    export CUDA_VISIBLE_DEVICES=$gpu_id
                    source $WORKLOAD_DIR/yolo_venv/bin/activate
                    python3 $WORKLOAD_DIR/gpt2_inference.py --duration $duration 2>&1
                " > "$log_file" 2>&1 &
            ;;
    esac
    WL_A_PID=$!
    log "${workload_type} 시작 (PID: $WL_A_PID, GPU${gpu_id}, $slice)"
}

# ffmpeg x264 (CPU-NonAI)
start_ffmpeg() {
    local slice=$1; local duration=$2
    local log_file="$LOG_DIR/ffmpeg_${slice%.slice}.log"
    timeout $((duration + 10)) \
        systemd-run --scope --slice=$slice --uid=$REAL_UID --gid=$REAL_GID \
        bash -c "
            source $WORKLOAD_DIR/yolo_venv/bin/activate
            python3 $WORKLOAD_DIR/ffmpeg_encode.py --duration $duration 2>&1
        " > "$log_file" 2>&1 &
    WL_A_PID=$!
    log "ffmpeg 시작 (PID: $WL_A_PID, $slice)"
}

# stress-ng 메모리 (Memory-NonAI): 2 workers × 1.5GB = 3GB (4GB limit 내)
start_stress_mem() {
    local slice=$1; local duration=$2
    local log_file="$LOG_DIR/stressmem_${slice%.slice}.log"
    timeout $((duration + 10)) \
        systemd-run --scope --slice=$slice --uid=$REAL_UID --gid=$REAL_GID \
        stress-ng --vm 2 --vm-bytes 1536M --vm-keep --timeout ${duration}s \
        > "$log_file" 2>&1 &
    WL_B_PID=$!
    log "stress-ng 메모리 시작 (PID: $WL_B_PID, $slice, 2×1.5GB)"
}

# fio randrw (I/O-NonAI)
start_fio_randrw() {
    local slice=$1; local duration=$2
    local log_file="$LOG_DIR/fio_randrw_${slice%.slice}.log"
    timeout $((duration + 10)) \
        systemd-run --scope --slice=$slice --uid=$REAL_UID --gid=$REAL_GID \
        fio --name=randrw --filename="$FIO_FILE" --size=2G \
            --rw=randrw --rwmixread=70 --bs=4k --iodepth=32 --direct=1 \
            --time_based --runtime=${duration} --output-format=json \
            --output="$LOG_DIR/fio_randrw_${slice%.slice}.json" \
        > "$log_file" 2>&1 &
    WL_B_PID=$!
    log "fio randrw 시작 (PID: $WL_B_PID, $slice, 4k/QD32/R70W30)"
}

# fio bursty (I/O-NonAI): iodepth 1 → 8 → 32 램프 (각 30s) — R1#3 bursty 대응
start_fio_bursty() {
    local slice=$1; local duration=$2
    local seg=$((duration / 3))
    local log_file="$LOG_DIR/fio_bursty_${slice%.slice}.log"
    timeout $((duration + 15)) \
        systemd-run --scope --slice=$slice --uid=$REAL_UID --gid=$REAL_GID \
        bash -c "
            for qd in 1 8 32; do
                fio --name=burst_qd\$qd --filename=$FIO_FILE --size=2G \
                    --rw=randrw --rwmixread=70 --bs=4k --iodepth=\$qd --direct=1 \
                    --time_based --runtime=$seg --output-format=json \
                    --output=$LOG_DIR/fio_bursty_qd\${qd}.json 2>&1
            done
        " > "$log_file" 2>&1 &
    WL_B_PID=$!
    log "fio bursty 시작 (PID: $WL_B_PID, $slice, QD 1→8→32 × ${seg}s)"
}

# Node.js Heavy (nodejs.slice) — phase3와 동일 패턴
start_nodejs() {
    local duration=$1
    cd "$WORKLOAD_DIR"
    ( echo $$ > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null || true
      exec node "server_heavy.js" 2>/dev/null ) &
    NODE_PID=$!
    sleep 2
    log "Node.js 서버 시작 (PID: $NODE_PID, nodejs.slice)"

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
# 메인
########################################
phase "Phase 4: 워크로드 확장 실험 — Run ${RUN_NUM}"
echo -e "${MAGENTA}신규 4종 solo + bursty + 신규 concurrent 4쌍${NC}"
echo -e "${MAGENTA}출력: $LOG_DIR${NC}"

check_prerequisites
set_cpu_fixed
setup_cgroups_equal

mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

# 실험 설정 기록 (논문 재현성 명세의 근거 — R2#4)
cat > "$LOG_DIR/config.txt" << EOF
===== Phase 4: Workload Expansion Experiment =====
Date: $(date)
Run: ${RUN_NUM}

cgroup allocation (equal, 2 cores / 4GB each):
  yolo.slice   → cpuset 0-1, 4GB  (Workload A)
  nodejs.slice → cpuset 2-3, 4GB  (Workload B)
CPU frequency: fixed 3.6GHz, turbo off, performance governor

New workloads:
  W5 ResNet-18 CPU inference : torchvision resnet18, batch=32, 3x224x224, device=cpu
  W7 ffmpeg x264 encode      : lavfi testsrc 1920x1080@30fps -> null, preset default
  W8 stress-ng memory        : --vm 2 --vm-bytes 1536M --vm-keep (3GB total)
  W9 fio randrw              : bs=4k iodepth=32 rwmixread=70 direct=1 file=2GB NVMe
  W9b fio bursty             : same, iodepth ramp 1 -> 8 -> 32 (30s each)

Solo phases (reference for validation):
  solo_resnet_cpu / solo_ffmpeg / solo_stressmem / solo_fio_randrw / solo_fio_bursty
  solo_nodejs / solo_yolo(GPU0) / solo_gpt2(GPU0)

Concurrent pairs:
  C1 resnetcpu_nodejs : ResNet-CPU(yolo.slice) + Node.js(nodejs.slice) — CPU 분할(AI vs NonAI)
  C2 ffmpeg_nodejs    : ffmpeg(yolo.slice) + Node.js(nodejs.slice)    — CPU 분할(NonAI 쌍)
  C3 yolo_fio         : YOLO(GPU0,yolo.slice) + fio(nodejs.slice)     — GPU + I/O
  C4 gpt2_stressmem   : GPT2(GPU0,yolo.slice) + stress(nodejs.slice)  — GPU + Memory

Purpose:
  Expand workload set 4 -> 9 (with existing GEMM data: phase3_fixed PT* phases)
  Cover 5 resource categories: GPU-AI / CPU-AI / CPU-NonAI / Memory / I/O
  Validate attribution accuracy on new resource-category pairs

Hardware: Alienware Aurora R12 (i7-11700KF 8c/16t, RTX 3060 x2, 32GB DDR4,
          Samsung SSD 980 500GB NVMe)
Observation: ${WORKLOAD_DURATION}s per phase, first/last 10s trimmed in analysis
EOF
chown $REAL_UID:$REAL_GID "$LOG_DIR/config.txt"

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
start_ffmpeg "yolo.slice" $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Solo 3/8: stress-ng memory (nodejs.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_stressmem" $WORKLOAD_DURATION
sleep 2
start_stress_mem "nodejs.slice" $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Solo 4/8: fio randrw (nodejs.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_fio_randrw" $WORKLOAD_DURATION
sleep 2
start_fio_randrw "nodejs.slice" $WORKLOAD_DURATION
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
start_ffmpeg "yolo.slice" $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Pair C3: YOLO(GPU0) + fio randrw — GPU + I/O"
start_loggers "C3_yolo_fio" $WORKLOAD_DURATION
sleep 2
start_ai_gpu "yolo_medium" 0 "yolo.slice" $WORKLOAD_DURATION
start_fio_randrw "nodejs.slice" $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

phase "Pair C4: GPT2(GPU0) + stress-ng memory — GPU + Memory"
start_loggers "C4_gpt2_stressmem" $WORKLOAD_DURATION
sleep 2
start_ai_gpu "gpt2" 0 "yolo.slice" $WORKLOAD_DURATION
start_stress_mem "nodejs.slice" $WORKLOAD_DURATION
wait_loggers; stop_workloads; drop_caches; sleep $COOLDOWN

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
