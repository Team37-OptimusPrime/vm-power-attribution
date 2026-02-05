#!/bin/bash
# Phase 1.5 실험: cgroup v2 기반 응용별 리소스 분리 측정
#
# 교수님 요구사항 완전 충족:
# - cgroup으로 CPU/메모리 동일 할당
# - 응용별 CPU/IO 사용량 개별 측정
# - 동시 실행 시 상호 간섭 측정
#
# 사전 요구사항:
#   1. sudo ./setup_cgroups.sh 실행 완료
#   2. YOLO venv 설정 완료
#   3. Node.js, npm install express 완료
#
# Usage:
#   ./run_experiment_v3.sh [experiment_name]
#
# 예시:
#   ./run_experiment_v3.sh phase1.5_test1

set -e

# 설정
EXP_NAME=${1:-"phase1.5_$(date +%Y%m%d_%H%M%S)"}
BASE_DIR="$HOME/vm-power-attribution"
LOG_DIR="$BASE_DIR/data/raw/phase1.5/$EXP_NAME"
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
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
phase() { echo -e "\n${CYAN}========================================${NC}"; echo -e "${CYAN}$1${NC}"; echo -e "${CYAN}========================================${NC}"; }

# 전처리 체크
check_prerequisites() {
    log "사전 요구사항 확인 중..."

    # cgroup 존재 확인
    if [ ! -d "$YOLO_CGROUP" ]; then
        error "yolo.slice cgroup이 없습니다. 'sudo ./setup_cgroups.sh' 먼저 실행하세요."
        exit 1
    fi

    if [ ! -d "$NODEJS_CGROUP" ]; then
        error "nodejs.slice cgroup이 없습니다. 'sudo ./setup_cgroups.sh' 먼저 실행하세요."
        exit 1
    fi

    # YOLO venv 확인
    if [ ! -d "$WORKLOAD_DIR/yolo_venv" ]; then
        warn "yolo_venv가 없습니다. YOLO 테스트 시 문제가 발생할 수 있습니다."
    fi

    # Node.js 확인
    if ! command -v node &> /dev/null; then
        error "Node.js가 설치되어 있지 않습니다."
        exit 1
    fi

    # 권한 확인 (cgroup 쓰기 권한)
    if [ ! -w "$YOLO_CGROUP/cgroup.procs" ]; then
        warn "cgroup 쓰기 권한이 없습니다. sudo로 실행하거나 권한을 확인하세요."
    fi

    log "사전 요구사항 확인 완료"
}

# 프로세스를 cgroup에 할당하는 헬퍼 함수
run_in_cgroup() {
    local cgroup_path=$1
    shift
    local cmd="$@"

    # 현재 쉘을 cgroup에 할당 후 명령 실행
    echo $$ > "$cgroup_path/cgroup.procs" 2>/dev/null || {
        warn "cgroup 할당 실패, 일반 실행으로 대체"
    }
    eval "$cmd"
}

# cleanup 함수
cleanup() {
    log "정리 중..."
    # 백그라운드 프로세스 종료
    jobs -p | xargs -r kill 2>/dev/null || true

    # Node.js 서버 종료
    pkill -f "node.*server.js" 2>/dev/null || true

    # cgroup에서 프로세스 제거 (자동으로 됨)
    log "정리 완료"
}

trap cleanup EXIT

########################################
# 메인 시작
########################################

phase "Phase 1.5 실험 시작: cgroup 기반 응용별 리소스 분리"

check_prerequisites

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"
log "실험명: $EXP_NAME"
log "로그 디렉토리: $LOG_DIR"

# 실험 설정 저장
cat > "$LOG_DIR/config.txt" << EOF
Experiment: $EXP_NAME
Date: $(date)
Type: Phase 1.5 - cgroup based resource isolation

cgroup Configuration:
- YOLO: $YOLO_CGROUP
  - cpuset.cpus: $(cat $YOLO_CGROUP/cpuset.cpus 2>/dev/null || echo "N/A")
  - cpu.max: $(cat $YOLO_CGROUP/cpu.max 2>/dev/null || echo "N/A")
  - memory.max: $(cat $YOLO_CGROUP/memory.max 2>/dev/null || echo "N/A")

- Node.js: $NODEJS_CGROUP
  - cpuset.cpus: $(cat $NODEJS_CGROUP/cpuset.cpus 2>/dev/null || echo "N/A")
  - cpu.max: $(cat $NODEJS_CGROUP/cpu.max 2>/dev/null || echo "N/A")
  - memory.max: $(cat $NODEJS_CGROUP/memory.max 2>/dev/null || echo "N/A")

Timing:
- Baseline: ${BASELINE_DURATION}s
- Workload: ${WORKLOAD_DURATION}s
- Cooldown: ${COOLDOWN}s

Workloads:
- AI: YOLOv8 Nano (yolo.slice cgroup)
- Non-AI: Node.js Express + curl (nodejs.slice cgroup)
EOF

info "설정이 $LOG_DIR/config.txt에 저장됨"

########################################
# Phase 0: Baseline (Idle)
########################################
phase "Phase 0: Baseline (Idle) - ${BASELINE_DURATION}s"

# Host 로거 + cgroup 로거 동시 시작
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/baseline_host.csv" -d $BASELINE_DURATION -i 1 &
HOST_LOGGER_PID=$!

python3 "$SCRIPT_DIR/cgroup_logger.py" -o "$LOG_DIR/baseline_cgroup.csv" -d $BASELINE_DURATION -i 1 --include-system-io &
CGROUP_LOGGER_PID=$!

wait $HOST_LOGGER_PID $CGROUP_LOGGER_PID 2>/dev/null || true

log "Baseline 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 1: YOLO Solo (AI)
########################################
phase "Phase 1: YOLO Solo (AI) - ${WORKLOAD_DURATION}s"
info "cgroup: yolo.slice (코어 0-1, 4GB)"

# 로거 시작
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/yolo_solo_host.csv" -d $WORKLOAD_DURATION -i 1 &
HOST_LOGGER_PID=$!

python3 "$SCRIPT_DIR/cgroup_logger.py" -o "$LOG_DIR/yolo_solo_cgroup.csv" -d $WORKLOAD_DURATION -i 1 --include-system-io &
CGROUP_LOGGER_PID=$!

sleep 2  # 로거 안정화

# YOLO 실행 (cgroup 내에서)
cd "$WORKLOAD_DIR"
if [ -d "yolo_venv" ]; then
    log "YOLO 추론 시작 (yolo.slice cgroup)..."

    # systemd-run을 사용하여 모든 자식 프로세스를 cgroup에 포함
    # --scope: 일시적 scope unit 생성
    # --slice=yolo.slice: yolo.slice cgroup에 할당
    # 이 방식은 yolo가 생성하는 모든 자식 프로세스도 cgroup에 포함시킴
    sudo systemd-run --scope --slice=yolo.slice --uid=$(id -u) --gid=$(id -g) \
        bash -c "
            source $WORKLOAD_DIR/yolo_venv/bin/activate
            END_TIME=\$((SECONDS + $WORKLOAD_DURATION - 5))
            while [ \$SECONDS -lt \$END_TIME ]; do
                yolo predict model=yolov8n.pt source=test_video.mp4 device=0 verbose=False 2>/dev/null || true
            done
        " &
    YOLO_PID=$!

    wait $YOLO_PID 2>/dev/null || true
else
    warn "yolo_venv 없음, YOLO 스킵"
    sleep $WORKLOAD_DURATION
fi

wait $HOST_LOGGER_PID $CGROUP_LOGGER_PID 2>/dev/null || true

log "YOLO Solo 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 2: Node.js Solo (Non-AI)
########################################
phase "Phase 2: Node.js Solo (Non-AI) - ${WORKLOAD_DURATION}s"
info "cgroup: nodejs.slice (코어 2-3, 4GB)"

# Node.js 서버 시작 (cgroup 내에서)
cd "$WORKLOAD_DIR"
(
    echo $$ > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null || true
    exec node server.js
) &
NODE_PID=$!
sleep 2

# 로거 시작
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/nodejs_solo_host.csv" -d $WORKLOAD_DURATION -i 1 &
HOST_LOGGER_PID=$!

python3 "$SCRIPT_DIR/cgroup_logger.py" -o "$LOG_DIR/nodejs_solo_cgroup.csv" -d $WORKLOAD_DURATION -i 1 --include-system-io &
CGROUP_LOGGER_PID=$!

sleep 2

# curl 부하 생성 (nodejs cgroup에서)
log "curl 부하 생성 시작 (nodejs.slice cgroup)..."
(
    echo $$ > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null || true
    END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
    while [ $SECONDS -lt $END_TIME ]; do
        CURL_PIDS=""
        for i in {1..20}; do
            curl -s --max-time 2 http://localhost:3000/ > /dev/null &
            CURL_PIDS="$CURL_PIDS $!"
        done
        sleep 0.5
        for pid in $CURL_PIDS; do
            wait $pid 2>/dev/null || true
        done
    done
) &
CURL_GEN_PID=$!

wait $CURL_GEN_PID 2>/dev/null || true
wait $HOST_LOGGER_PID $CGROUP_LOGGER_PID 2>/dev/null || true
kill $NODE_PID 2>/dev/null || true

log "Node.js Solo 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 3: Concurrent (YOLO + Node.js)
########################################
phase "Phase 3: Concurrent (YOLO + Node.js) - ${WORKLOAD_DURATION}s"
info "YOLO: yolo.slice (코어 0-1)"
info "Node.js: nodejs.slice (코어 2-3)"

# Node.js 서버 시작
cd "$WORKLOAD_DIR"
(
    echo $$ > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null || true
    exec node server.js
) &
NODE_PID=$!
sleep 2

# 로거 시작
python3 "$SCRIPT_DIR/host_logger.py" -o "$LOG_DIR/concurrent_host.csv" -d $WORKLOAD_DURATION -i 1 &
HOST_LOGGER_PID=$!

python3 "$SCRIPT_DIR/cgroup_logger.py" -o "$LOG_DIR/concurrent_cgroup.csv" -d $WORKLOAD_DURATION -i 1 --include-system-io &
CGROUP_LOGGER_PID=$!

sleep 2

# YOLO 시작 (yolo.slice)
if [ -d "yolo_venv" ]; then
    log "YOLO 추론 시작 (concurrent, yolo.slice cgroup)..."

    sudo systemd-run --scope --slice=yolo.slice --uid=$(id -u) --gid=$(id -g) \
        bash -c "
            source $WORKLOAD_DIR/yolo_venv/bin/activate
            END_TIME=\$((SECONDS + $WORKLOAD_DURATION - 5))
            while [ \$SECONDS -lt \$END_TIME ]; do
                yolo predict model=yolov8n.pt source=test_video.mp4 device=0 verbose=False 2>/dev/null || true
            done
        " &
    YOLO_PID=$!
fi

# curl 부하 (nodejs.slice)
(
    echo $$ > "$NODEJS_CGROUP/cgroup.procs" 2>/dev/null || true
    END_TIME=$((SECONDS + WORKLOAD_DURATION - 5))
    while [ $SECONDS -lt $END_TIME ]; do
        CURL_PIDS=""
        for i in {1..20}; do
            curl -s --max-time 2 http://localhost:3000/ > /dev/null &
            CURL_PIDS="$CURL_PIDS $!"
        done
        sleep 0.5
        for pid in $CURL_PIDS; do
            wait $pid 2>/dev/null || true
        done
    done
) &
CURL_GEN_PID=$!

# 모든 워크로드 완료 대기
wait $YOLO_PID 2>/dev/null || true
wait $CURL_GEN_PID 2>/dev/null || true
wait $HOST_LOGGER_PID $CGROUP_LOGGER_PID 2>/dev/null || true

kill $NODE_PID 2>/dev/null || true

########################################
# 완료
########################################
phase "실험 완료"

log "결과 파일:"
ls -la "$LOG_DIR"

echo ""
info "생성된 파일:"
echo "  Host 측정 (RAPL, GPU, CPU%):"
echo "    - baseline_host.csv"
echo "    - yolo_solo_host.csv"
echo "    - nodejs_solo_host.csv"
echo "    - concurrent_host.csv"
echo ""
echo "  cgroup 측정 (응용별 CPU/메모리/IO):"
echo "    - baseline_cgroup.csv"
echo "    - yolo_solo_cgroup.csv"
echo "    - nodejs_solo_cgroup.csv"
echo "    - concurrent_cgroup.csv"
echo ""
echo "  설정:"
echo "    - config.txt"

echo ""
log "다음 단계:"
echo "  1. RPICT 데이터와 병합 (타임스탬프 기준)"
echo "  2. python3 scripts/analysis/comprehensive_analysis.py 실행"
echo "  3. 결과 시각화 및 보고서 생성"

echo ""
log "실험 완료: $EXP_NAME"
