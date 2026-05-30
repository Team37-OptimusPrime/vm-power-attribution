#!/bin/bash
# =============================================================================
# 통합 실험 스크립트
# alienware (master) + rpict (slave) 동시 실행
#
# 역할:
#   alienware: 워크로드 실행 + host_logger + cgroup_logger (기존 실험 스크립트)
#   rpict:     SSH로 rpict_logger.py 원격 실행 → CSV 수집 후 alienware로 전송
#
# Usage:
#   sudo -E ./run_integrated_experiment.sh [옵션]
#
# 옵션:
#   --experiment  phase3 | phase3_nopt | asymmetric | 3way   (기본: phase3)
#   --rpict-host  rpict의 IP 또는 hostname                   (기본: rpict.local)
#   --rpict-user  rpict SSH 사용자                           (기본: pi)
#   --rpict-port  rpict SSH 포트                             (기본: 22)
#   --run-id      실행 식별자 (기본: 자동 생성 타임스탬프)
#   --dry-run     rpict 연결 없이 alienware만 실행 (테스트용)
#   --skip-rpict  rpict 로깅 없이 실험만 실행
#
# 예시:
#   sudo -E ./run_integrated_experiment.sh
#   sudo -E ./run_integrated_experiment.sh --experiment phase3 --rpict-host 192.168.1.42
#   sudo -E ./run_integrated_experiment.sh --skip-rpict  # rpict 없이 alienware만
# =============================================================================

set +e

# =============================================================================
# 기본값 설정
# =============================================================================
EXPERIMENT="phase3"
RPICT_HOST="192.168.0.3"
RPICT_USER="rainyforest23"
RPICT_PORT="22"
RUN_ID=$(date +%Y%m%d_%H%M%S)
DRY_RUN=false
SKIP_RPICT=false

# =============================================================================
# 인자 파싱
# =============================================================================
while [[ $# -gt 0 ]]; do
    case $1 in
        --experiment)  EXPERIMENT="$2";  shift 2 ;;
        --rpict-host)  RPICT_HOST="$2";  shift 2 ;;
        --rpict-user)  RPICT_USER="$2";  shift 2 ;;
        --rpict-port)  RPICT_PORT="$2";  shift 2 ;;
        --run-id)      RUN_ID="$2";      shift 2 ;;
        --dry-run)     DRY_RUN=true;     shift ;;
        --skip-rpict)  SKIP_RPICT=true;  shift ;;
        *)
            echo "알 수 없는 옵션: $1"
            echo "Usage: sudo -E $0 [--experiment phase3] [--rpict-host HOST] [--dry-run] [--skip-rpict]"
            exit 1
            ;;
    esac
done

# =============================================================================
# sudo 권한 확인
# =============================================================================
if [ "$EUID" -ne 0 ]; then
    echo "Error: sudo로 실행해야 합니다."
    echo "Usage: sudo -E $0"
    exit 1
fi

REAL_UID=${SUDO_UID:-$(id -u)}
REAL_GID=${SUDO_GID:-$(id -g)}
REAL_USER=${SUDO_USER:-$(whoami)}

# =============================================================================
# 경로 설정
# =============================================================================
BASE_DIR="$HOME/vm-power-attribution"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"
MEASUREMENT_DIR="$BASE_DIR/scripts/measurement"

# 실험별 스크립트 매핑
declare -A EXPERIMENT_SCRIPTS=(
    ["phase3"]="run_experiment_phase3.sh"
    ["phase3_nopt"]="run_experiment_phase3_nopt.sh"
    ["asymmetric"]="run_experiment_asymmetric.sh"
    ["3way"]="run_experiment_3way.sh"
)

EXPERIMENT_SCRIPT="${EXPERIMENT_SCRIPTS[$EXPERIMENT]}"
if [ -z "$EXPERIMENT_SCRIPT" ]; then
    echo "Error: 알 수 없는 실험 유형: $EXPERIMENT"
    echo "가능한 값: ${!EXPERIMENT_SCRIPTS[@]}"
    exit 1
fi

# 데이터 디렉토리 (실험 스크립트의 LOG_DIR과 병렬 구조)
ALIENWARE_DATA_DIR="$BASE_DIR/data/raw/alienware/${EXPERIMENT}_integrated_${RUN_ID}"
RPICT_DATA_DIR="$BASE_DIR/data/raw/rpict/${EXPERIMENT}_integrated_${RUN_ID}"
RPICT_REMOTE_DIR="/home/${RPICT_USER}/rpict_logs"
RPICT_REMOTE_FILE="${RPICT_REMOTE_DIR}/rpict_${EXPERIMENT}_${RUN_ID}.csv"

# =============================================================================
# 색상 출력
# =============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

log()     { echo -e "${GREEN}[$(date +%H:%M:%S)] [MASTER]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; }
section() { echo -e "\n${CYAN}══════════════════════════════════════════${NC}"; echo -e "${CYAN}  $1${NC}"; echo -e "${CYAN}══════════════════════════════════════════${NC}"; }

# =============================================================================
# SSH 헬퍼
# =============================================================================
# sudo로 실행 시 root가 아닌 실제 유저의 SSH 키를 사용
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
SSH_KEY="${REAL_HOME}/.ssh/id_ed25519"
if [ ! -f "$SSH_KEY" ]; then
    SSH_KEY="${REAL_HOME}/.ssh/id_rsa"
fi
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes -p ${RPICT_PORT} -i ${SSH_KEY}"

ssh_rpict() {
    ssh $SSH_OPTS "${RPICT_USER}@${RPICT_HOST}" "$@"
}

scp_from_rpict() {
    local remote_path="$1"
    local local_path="$2"
    scp -P "${RPICT_PORT}" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        "${RPICT_USER}@${RPICT_HOST}:${remote_path}" "${local_path}"
}

# =============================================================================
# rpict 연결 확인
# =============================================================================
check_rpict_connection() {
    if $SKIP_RPICT || $DRY_RUN; then
        warn "rpict 로깅 비활성화 (--skip-rpict 또는 --dry-run)"
        return 0
    fi

    log "rpict SSH 연결 확인 중... (${RPICT_USER}@${RPICT_HOST}:${RPICT_PORT})"

    if ! ssh_rpict "echo 'SSH OK'" > /dev/null 2>&1; then
        error "rpict SSH 연결 실패: ${RPICT_USER}@${RPICT_HOST}:${RPICT_PORT}"
        echo ""
        echo "  다음을 확인하세요:"
        echo "  1. rpict 전원 및 네트워크 연결"
        echo "  2. SSH 키 설정: ssh-copy-id ${RPICT_USER}@${RPICT_HOST}"
        echo "  3. rpict 호스트명/IP 확인"
        echo ""
        echo "  rpict 없이 실행하려면 --skip-rpict 옵션 사용"
        exit 1
    fi
    log "rpict 연결 성공"

    # rpict에 rpict_logger.py 존재 여부 확인
    local RPICT_SCRIPT_REMOTE="/home/${RPICT_USER}/vm-power-attribution/scripts/measurement/rpict_logger.py"
    if ! ssh_rpict "test -f ${RPICT_SCRIPT_REMOTE}"; then
        warn "rpict에 rpict_logger.py 없음: ${RPICT_SCRIPT_REMOTE}"
        warn "로컬 스크립트를 rpict로 복사합니다..."
        ssh_rpict "mkdir -p /home/${RPICT_USER}/vm-power-attribution/scripts/measurement"
        scp -P "${RPICT_PORT}" -o StrictHostKeyChecking=no \
            "${MEASUREMENT_DIR}/rpict_logger.py" \
            "${RPICT_USER}@${RPICT_HOST}:${RPICT_SCRIPT_REMOTE}"
        log "rpict_logger.py 복사 완료"
    fi

    # 로그 디렉토리 생성
    ssh_rpict "mkdir -p ${RPICT_REMOTE_DIR}"
}

# =============================================================================
# rpict 로거 시작
# =============================================================================
RPICT_PID_REMOTE=""

start_rpict_logger() {
    if $SKIP_RPICT || $DRY_RUN; then return 0; fi

    local RPICT_SCRIPT="/home/${RPICT_USER}/vm-power-attribution/scripts/measurement/rpict_logger.py"

    log "rpict 로거 시작 중..."
    log "  출력 파일: ${RPICT_USER}@${RPICT_HOST}:${RPICT_REMOTE_FILE}"

    # nohup으로 백그라운드 실행, PID를 파일에 저장
    ssh_rpict "nohup python3 ${RPICT_SCRIPT} -o ${RPICT_REMOTE_FILE} > ${RPICT_REMOTE_DIR}/rpict_stdout_${RUN_ID}.log 2>&1 & echo \$! > ${RPICT_REMOTE_DIR}/rpict_pid_${RUN_ID}.txt"

    sleep 2

    # PID 확인
    RPICT_PID_REMOTE=$(ssh_rpict "cat ${RPICT_REMOTE_DIR}/rpict_pid_${RUN_ID}.txt 2>/dev/null" 2>/dev/null)
    if [ -z "$RPICT_PID_REMOTE" ]; then
        warn "rpict PID를 가져오지 못했습니다. 로거가 실행 중인지 확인하세요."
    else
        log "rpict 로거 실행 중 (PID: ${RPICT_PID_REMOTE})"
    fi

    # 실제로 데이터가 들어오는지 짧게 확인 (3초 대기)
    sleep 3
    local line_count
    line_count=$(ssh_rpict "wc -l < ${RPICT_REMOTE_FILE} 2>/dev/null" 2>/dev/null || echo "0")
    if [ "${line_count:-0}" -gt 1 ]; then
        log "rpict 데이터 수신 중 (${line_count}줄)"
    else
        warn "rpict 데이터가 아직 없습니다. lcl-run이 정상 동작하는지 확인하세요."
    fi
}

# =============================================================================
# rpict 로거 종료 및 CSV 회수
# =============================================================================
stop_rpict_logger() {
    if $SKIP_RPICT || $DRY_RUN; then return 0; fi

    log "rpict 로거 종료 중..."

    # PID로 종료
    if [ -n "$RPICT_PID_REMOTE" ]; then
        ssh_rpict "kill ${RPICT_PID_REMOTE} 2>/dev/null || true"
    fi
    # 혹시 남은 프로세스 정리
    ssh_rpict "pkill -f rpict_logger.py 2>/dev/null || true"

    sleep 1

    # CSV 회수
    log "rpict CSV 파일 가져오는 중..."
    mkdir -p "$RPICT_DATA_DIR"
    chown "$REAL_UID:$REAL_GID" "$RPICT_DATA_DIR"

    if scp_from_rpict "${RPICT_REMOTE_FILE}" "${RPICT_DATA_DIR}/rpict.csv" 2>/dev/null; then
        local lines
        lines=$(wc -l < "${RPICT_DATA_DIR}/rpict.csv" 2>/dev/null || echo "0")
        log "rpict.csv 저장 완료 (${lines}줄) → ${RPICT_DATA_DIR}/rpict.csv"
        chown "$REAL_UID:$REAL_GID" "${RPICT_DATA_DIR}/rpict.csv"
    else
        warn "rpict CSV 전송 실패. 수동으로 가져오세요:"
        warn "  scp ${RPICT_USER}@${RPICT_HOST}:${RPICT_REMOTE_FILE} ${RPICT_DATA_DIR}/rpict.csv"
    fi

    # stdout 로그도 회수
    scp_from_rpict "${RPICT_REMOTE_DIR}/rpict_stdout_${RUN_ID}.log" \
        "${RPICT_DATA_DIR}/rpict_stdout.log" 2>/dev/null || true
}

# =============================================================================
# 실험 스크립트 실행 (LOG_DIR을 오버라이드)
# =============================================================================
EXPERIMENT_PID=""

start_experiment() {
    local script_path="${WORKLOAD_DIR}/${EXPERIMENT_SCRIPT}"

    if [ ! -f "$script_path" ]; then
        error "실험 스크립트 없음: $script_path"
        exit 1
    fi

    section "실험 시작: ${EXPERIMENT} (RUN_ID: ${RUN_ID})"
    log "스크립트: $script_path"
    log "데이터 → ${ALIENWARE_DATA_DIR}"

    # 실험 스크립트의 LOG_DIR을 환경 변수로 오버라이드
    # (각 실험 스크립트는 LOG_DIR이 설정되어 있으면 그것을 사용하도록 수정 필요)
    # 현재는 실험 스크립트를 직접 실행하되, 출력을 tee로 저장
    mkdir -p "$ALIENWARE_DATA_DIR"
    chown -R "$REAL_UID:$REAL_GID" "$ALIENWARE_DATA_DIR"

    export INTEGRATED_LOG_DIR="$ALIENWARE_DATA_DIR"
    export INTEGRATED_RUN_ID="$RUN_ID"

    bash "$script_path"
    local exit_code=$?

    if [ $exit_code -ne 0 ]; then
        warn "실험 스크립트가 비정상 종료됨 (exit code: $exit_code)"
    else
        log "실험 스크립트 정상 완료"
    fi

    return $exit_code
}

# =============================================================================
# run_info.json 생성 (Streamlit용 메타데이터)
# =============================================================================
save_run_info() {
    local info_file="$BASE_DIR/data/raw/run_info_${RUN_ID}.json"

    cat > "$info_file" << EOF
{
  "run_id": "${RUN_ID}",
  "experiment": "${EXPERIMENT}",
  "timestamp": "$(date -Iseconds)",
  "alienware_data_dir": "${ALIENWARE_DATA_DIR}",
  "rpict_data_dir": "${RPICT_DATA_DIR}",
  "rpict_host": "${RPICT_HOST}",
  "rpict_skipped": ${SKIP_RPICT},
  "experiment_script": "${EXPERIMENT_SCRIPT}"
}
EOF
    chown "$REAL_UID:$REAL_GID" "$info_file"
    log "실행 정보 저장: $info_file"
}

# =============================================================================
# 전체 cleanup (Ctrl+C 등 인터럽트 시)
# =============================================================================
cleanup() {
    echo ""
    warn "인터럽트 감지 — 정리 중..."

    # rpict 로거 종료 및 회수
    stop_rpict_logger

    # run_info 저장
    save_run_info

    log "정리 완료"
}

trap cleanup EXIT INT TERM

# =============================================================================
# 메인 흐름
# =============================================================================
section "통합 실험 시작"
echo -e "${MAGENTA}  실험:        ${EXPERIMENT}${NC}"
echo -e "${MAGENTA}  RUN_ID:      ${RUN_ID}${NC}"
echo -e "${MAGENTA}  rpict:       ${RPICT_USER}@${RPICT_HOST}:${RPICT_PORT}${NC}"
if $SKIP_RPICT; then
    echo -e "${YELLOW}  rpict 로깅:  비활성화 (--skip-rpict)${NC}"
elif $DRY_RUN; then
    echo -e "${YELLOW}  rpict 로깅:  비활성화 (--dry-run)${NC}"
else
    echo -e "${MAGENTA}  rpict 로깅:  활성화${NC}"
fi
echo ""

# 1. rpict 연결 확인
check_rpict_connection

# 2. rpict 로거 시작
start_rpict_logger

if ! $SKIP_RPICT && ! $DRY_RUN; then
    log "rpict 로거 워밍업 대기 (3초)..."
    sleep 3
fi

# 3. 실험 실행
start_experiment
EXPERIMENT_EXIT=$?

# 4. rpict 종료 + CSV 회수 (trap에서도 호출되지만 정상 종료 시도 먼저)
stop_rpict_logger

# 5. 메타데이터 저장
save_run_info

# =============================================================================
# 완료 요약
# =============================================================================
section "실험 완료"
log "RUN_ID:          ${RUN_ID}"
log "Alienware 데이터: ${ALIENWARE_DATA_DIR}"
if ! $SKIP_RPICT && ! $DRY_RUN; then
    log "RPICT 데이터:     ${RPICT_DATA_DIR}/rpict.csv"
fi
echo ""
info "다음 단계:"
echo "  1. 분석:   python3 scripts/analysis/extract_phase3_data.py"
echo "  2. 대시보드: streamlit run scripts/dashboard/app.py  (향후)"
echo ""

exit $EXPERIMENT_EXIT
