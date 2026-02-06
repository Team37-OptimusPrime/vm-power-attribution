#!/bin/bash
# Phase 1.6 실험: 4개 워크로드 비교
#
# 워크로드:
#   A1: YOLO Nano (yolov8n.pt) - 경량 AI
#   A2: YOLO Medium (yolov8m.pt) - 보편 AI
#   B1: Node.js Light - 경량 Non-AI
#   B2: Node.js Heavy - 고부하 Non-AI
#
# Usage:
#   sudo -E ./run_experiment_4workloads.sh [experiment_name]

# set -e 제거 - 개별 명령 실패해도 계속 진행
set +e

# sudo 권한 확인
if [ "$EUID" -ne 0 ]; then
    echo "Error: 이 스크립트는 sudo로 실행해야 합니다."
    echo "Usage: sudo -E $0 [experiment_name]"
    exit 1
fi

# 실제 사용자 UID/GID (sudo 전 사용자)
REAL_UID=${SUDO_UID:-$(id -u)}
REAL_GID=${SUDO_GID:-$(id -g)}
REAL_USER=${SUDO_USER:-$(whoami)}

# 설정
EXP_NAME=${1:-"phase1.6_4workloads_$(date +%Y%m%d_%H%M%S)"}
BASE_DIR="$HOME/vm-power-attribution"
LOG_DIR="$BASE_DIR/data/raw/phase1.6/$EXP_NAME"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"

# cgroup 경로
CGROUP_ROOT="/sys/fs/cgroup"
YOLO_CGROUP="$CGROUP_ROOT/yolo.slice"
NODEJS_CGROUP="$CGROUP_ROOT/nodejs.slice"

# 시간 설정 (초)
BASELINE_DURATION=30
WORKLOAD_DURATION=60
COOLDOWN=15

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

# 전처리 체크
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

    log "사전 요구사항 확인 완료"
}

# cleanup 함수
cleanup() {
    log "정리 중..."
    jobs -p | xargs -r kill 2>/dev/null || true
    pkill -f "node.*server" 2>/dev/null || true
    log "정리 완료"
}

trap cleanup EXIT

# 전역 PID 변수
YOLO_PID=""
CURL_PID=""
NODE_PID=""

# YOLO 실행 함수 (PID를 전역 변수에 저장)
start_yolo() {
    local model=$1  # yolov8n.pt or yolov8m.pt
    local duration=$2

    YOLO_PID=""
    if [ -d "$WORKLOAD_DIR/yolo_venv" ]; then
        timeout $((duration + 10)) \
            sudo systemd-run --scope --slice=yolo.slice --uid=$REAL_UID --gid=$REAL_GID \
            bash -c "
                source $WORKLOAD_DIR/yolo_venv/bin/activate
                END_TIME=\$((SECONDS + $duration - 5))
                while [ \$SECONDS -lt \$END_TIME ]; do
                    yolo predict model=$model source=test_video.mp4 device=0 verbose=False 2>/dev/null || true
                done
            " &
        YOLO_PID=$!
        log "YOLO 시작 (PID: $YOLO_PID, model: $model)"
    else
        warn "yolo_venv 없음, YOLO 스킵"
    fi
}

# Node.js Light 부하 생성
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

# Node.js Heavy 부하 생성
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

# Node.js 서버 시작
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

# 워크로드 정리
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
# 메인 시작
########################################

phase "Phase 1.6 실험: 4개 워크로드 비교"
echo -e "${MAGENTA}A1: YOLO Nano    A2: YOLO Medium${NC}"
echo -e "${MAGENTA}B1: Node.js Light    B2: Node.js Heavy${NC}"

check_prerequisites

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"
log "실험명: $EXP_NAME"
log "로그 디렉토리: $LOG_DIR"

# 실험 설정 저장
cat > "$LOG_DIR/config.txt" << EOF
Experiment: $EXP_NAME
Date: $(date)
Type: Phase 1.6 - 4 Workloads Comparison

Workloads:
- A1: YOLO Nano (yolov8n.pt) - yolo.slice
- A2: YOLO Medium (yolov8m.pt) - yolo.slice
- B1: Node.js Light (server_light.js) - nodejs.slice
- B2: Node.js Heavy (server_heavy.js) - nodejs.slice

cgroup Configuration:
- YOLO slice: cpuset.cpus=$(cat $YOLO_CGROUP/cpuset.cpus 2>/dev/null || echo "N/A")
- Node.js slice: cpuset.cpus=$(cat $NODEJS_CGROUP/cpuset.cpus 2>/dev/null || echo "N/A")

Timing:
- Baseline: ${BASELINE_DURATION}s
- Each Workload: ${WORKLOAD_DURATION}s
- Cooldown: ${COOLDOWN}s
EOF

########################################
# Phase 0: Baseline (Idle)
########################################
phase "Phase 0: Baseline (Idle) - ${BASELINE_DURATION}s"

python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/baseline_host.csv" -d $BASELINE_DURATION -i 1 &
HOST_PID=$!
python3 "$SCRIPT_DIR/cgroup_logger.py" -o "$LOG_DIR/baseline_cgroup.csv" -d $BASELINE_DURATION -i 1 &
CGROUP_PID=$!

wait $HOST_PID $CGROUP_PID 2>/dev/null || true
log "Baseline 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 1: A1 - YOLO Nano Solo
########################################
phase "Phase 1: A1 - YOLO Nano Solo - ${WORKLOAD_DURATION}s"
info "Model: yolov8n.pt | cgroup: yolo.slice"

python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/A1_yolo_nano_host.csv" -d $WORKLOAD_DURATION -i 1 &
HOST_PID=$!
python3 "$SCRIPT_DIR/cgroup_logger.py" -o "$LOG_DIR/A1_yolo_nano_cgroup.csv" -d $WORKLOAD_DURATION -i 1 &
CGROUP_PID=$!

sleep 2
cd "$WORKLOAD_DIR"
start_yolo "yolov8n.pt" $WORKLOAD_DURATION

wait $HOST_PID $CGROUP_PID 2>/dev/null
stop_workloads

log "A1 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 2: A2 - YOLO Medium Solo
########################################
phase "Phase 2: A2 - YOLO Medium Solo - ${WORKLOAD_DURATION}s"
info "Model: yolov8m.pt | cgroup: yolo.slice"

python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/A2_yolo_medium_host.csv" -d $WORKLOAD_DURATION -i 1 &
HOST_PID=$!
python3 "$SCRIPT_DIR/cgroup_logger.py" -o "$LOG_DIR/A2_yolo_medium_cgroup.csv" -d $WORKLOAD_DURATION -i 1 &
CGROUP_PID=$!

sleep 2
cd "$WORKLOAD_DIR"
start_yolo "yolov8m.pt" $WORKLOAD_DURATION

wait $HOST_PID $CGROUP_PID 2>/dev/null
stop_workloads

log "A2 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 3: B1 - Node.js Light Solo
########################################
phase "Phase 3: B1 - Node.js Light Solo - ${WORKLOAD_DURATION}s"
info "Server: server_light.js | cgroup: nodejs.slice"

start_nodejs_server "server_light.js"

python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/B1_nodejs_light_host.csv" -d $WORKLOAD_DURATION -i 1 &
HOST_PID=$!
python3 "$SCRIPT_DIR/cgroup_logger.py" -o "$LOG_DIR/B1_nodejs_light_cgroup.csv" -d $WORKLOAD_DURATION -i 1 &
CGROUP_PID=$!

sleep 2
start_nodejs_light $WORKLOAD_DURATION

wait $HOST_PID $CGROUP_PID 2>/dev/null
stop_workloads

log "B1 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 4: B2 - Node.js Heavy Solo
########################################
phase "Phase 4: B2 - Node.js Heavy Solo - ${WORKLOAD_DURATION}s"
info "Server: server_heavy.js | cgroup: nodejs.slice"

start_nodejs_server "server_heavy.js"

python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/B2_nodejs_heavy_host.csv" -d $WORKLOAD_DURATION -i 1 &
HOST_PID=$!
python3 "$SCRIPT_DIR/cgroup_logger.py" -o "$LOG_DIR/B2_nodejs_heavy_cgroup.csv" -d $WORKLOAD_DURATION -i 1 &
CGROUP_PID=$!

sleep 2
start_nodejs_heavy $WORKLOAD_DURATION

wait $HOST_PID $CGROUP_PID 2>/dev/null
stop_workloads

log "B2 완료."

########################################
# 완료
########################################
phase "실험 완료"

log "결과 파일:"
ls -la "$LOG_DIR"

echo ""
info "생성된 파일:"
echo "  Baseline:"
echo "    - baseline_host.csv, baseline_cgroup.csv"
echo ""
echo "  A1 (YOLO Nano):"
echo "    - A1_yolo_nano_host.csv, A1_yolo_nano_cgroup.csv"
echo ""
echo "  A2 (YOLO Medium):"
echo "    - A2_yolo_medium_host.csv, A2_yolo_medium_cgroup.csv"
echo ""
echo "  B1 (Node.js Light):"
echo "    - B1_nodejs_light_host.csv, B1_nodejs_light_cgroup.csv"
echo ""
echo "  B2 (Node.js Heavy):"
echo "    - B2_nodejs_heavy_host.csv, B2_nodejs_heavy_cgroup.csv"

echo ""
log "다음 단계:"
echo "  1. RPICT 데이터 수집 (별도 Raspberry Pi)"
echo "  2. 분석 스크립트 실행"
echo ""
log "실험 완료: $EXP_NAME"
