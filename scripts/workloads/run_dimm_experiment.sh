#!/bin/bash
# Phase 2.0a: DIMM 물리 실험 - Memory 에너지 파라미터 도출
#
# 목적: 32GB(2 DIMM) vs 16GB(1 DIMM) idle 전력 비교로 Memory_per_DIMM(W) 도출
#
# 실험 절차:
#   Step 1: 현재 상태(32GB) idle 측정 → run_dimm_experiment.sh 32gb
#   Step 2: BIOS에서 DIMM 1개 비활성화 (또는 물리 제거)
#   Step 3: 16GB 상태 idle 측정   → run_dimm_experiment.sh 16gb
#   Step 4: (선택) DIMM 복구 후 재측정 → run_dimm_experiment.sh 32gb_verify
#
# 분석:
#   Memory_per_DIMM = Wall(32GB) - Wall(16GB)
#   Memory_per_GB   = Memory_per_DIMM / 16
#
# Usage:
#   sudo -E ./run_dimm_experiment.sh 32gb
#   sudo -E ./run_dimm_experiment.sh 16gb
#   sudo -E ./run_dimm_experiment.sh 32gb_verify

set +e

if [ "$EUID" -ne 0 ]; then
    echo "Error: sudo로 실행하세요."
    echo "Usage: sudo -E $0 {32gb|16gb|32gb_verify}"
    exit 1
fi

REAL_UID=${SUDO_UID:-$(id -u)}
REAL_GID=${SUDO_GID:-$(id -g)}

# 인자 확인
DIMM_CONFIG=${1:-""}
if [ -z "$DIMM_CONFIG" ]; then
    echo "Usage: sudo -E $0 {32gb|16gb|32gb_verify}"
    echo ""
    echo "  32gb         - 현재 상태(32GB) idle 측정"
    echo "  16gb         - DIMM 1개 비활성화 후 idle 측정"
    echo "  32gb_verify  - DIMM 복구 후 재측정 (재현성 검증)"
    exit 1
fi

# 설정
BASE_DIR="$HOME/vm-power-attribution"
LOG_DIR="$BASE_DIR/data/raw/alienware/phase2.0_dimm"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"

# 시간 설정
WARMUP=60        # 부팅 후 안정화 시간 (이미 기다렸다면 줄여도 됨)
MEASURE=300      # 측정 시간 (5분 - 정밀 측정)
REPEAT=3         # 반복 횟수

# 색상
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
phase() { echo -e "\n${CYAN}========================================${NC}"; echo -e "${CYAN}$1${NC}"; echo -e "${CYAN}========================================${NC}"; }

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

# 시스템 정보 수집
collect_system_info() {
    local prefix=$1
    local info_file="$LOG_DIR/${prefix}_system_info.txt"

    echo "=== DIMM Experiment: $prefix ===" > "$info_file"
    echo "Date: $(date)" >> "$info_file"
    echo "" >> "$info_file"

    echo "--- Memory ---" >> "$info_file"
    free -h >> "$info_file" 2>&1
    echo "" >> "$info_file"

    echo "--- DIMM Info (dmidecode) ---" >> "$info_file"
    dmidecode -t memory 2>/dev/null | grep -A 10 "Memory Device" >> "$info_file" 2>&1
    echo "" >> "$info_file"

    echo "--- CPU Info ---" >> "$info_file"
    lscpu | head -20 >> "$info_file" 2>&1
    echo "" >> "$info_file"

    echo "--- Temperatures ---" >> "$info_file"
    sensors 2>/dev/null >> "$info_file" 2>&1
    echo "" >> "$info_file"

    echo "--- Fan Speeds ---" >> "$info_file"
    cat /sys/class/hwmon/hwmon*/fan*_input 2>/dev/null >> "$info_file" 2>&1
    echo "" >> "$info_file"

    # 실제 메모리 크기 확인
    local mem_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    local mem_gb=$((mem_kb / 1024 / 1024))
    echo "--- Detected RAM: ${mem_gb}GB ---" >> "$info_file"
    echo "" >> "$info_file"

    log "시스템 정보 저장: $info_file"
    log "감지된 RAM: ${mem_gb}GB"

    # 설정 검증
    case "$prefix" in
        32gb|32gb_verify)
            if [ "$mem_gb" -lt 28 ]; then
                warn "RAM이 ${mem_gb}GB로 감지됨 - 32GB가 아닙니다!"
                warn "BIOS에서 DIMM 설정을 확인하세요."
                read -p "계속 진행하시겠습니까? (y/N): " confirm
                [ "$confirm" != "y" ] && exit 1
            fi
            ;;
        16gb)
            if [ "$mem_gb" -gt 20 ]; then
                warn "RAM이 ${mem_gb}GB로 감지됨 - 16GB가 아닙니다!"
                warn "BIOS에서 DIMM 1개를 비활성화했는지 확인하세요."
                read -p "계속 진행하시겠습니까? (y/N): " confirm
                [ "$confirm" != "y" ] && exit 1
            fi
            ;;
    esac
}

# Idle 측정 실행
run_idle_measurement() {
    local prefix=$1
    local run_num=$2
    local duration=$3

    local host_file="$LOG_DIR/${prefix}_run${run_num}_host.csv"

    log "측정 시작: ${prefix} run${run_num} (${duration}초)"

    python3 "$SCRIPT_DIR/host_logger.py" \
        -o "$host_file" \
        -d "$duration" \
        -i 1 &
    local HOST_PID=$!

    wait $HOST_PID 2>/dev/null

    chown $REAL_UID:$REAL_GID "$host_file"
    log "측정 완료: $host_file"
}

########################################
# 메인
########################################

phase "Phase 2.0a: DIMM 실험 - ${DIMM_CONFIG}"

# 시스템 정보 수집
collect_system_info "$DIMM_CONFIG"

# 안정화 대기
info "시스템 안정화 대기 중... (${WARMUP}초)"
info "Tip: 부팅 직후라면 기다리세요. 이미 안정화됐으면 Ctrl+C로 건너뛸 수 있습니다."

WARMUP_INTERRUPTED=false
( sleep $WARMUP ) &
SLEEP_PID=$!
trap "kill $SLEEP_PID 2>/dev/null; WARMUP_INTERRUPTED=true" INT
wait $SLEEP_PID 2>/dev/null
trap - INT

if [ "$WARMUP_INTERRUPTED" = true ]; then
    log "안정화 대기 건너뜀"
else
    log "안정화 완료"
fi

# 반복 측정
for run in $(seq 1 $REPEAT); do
    phase "측정 ${run}/${REPEAT}: ${DIMM_CONFIG} idle"

    run_idle_measurement "$DIMM_CONFIG" "$run" "$MEASURE"

    if [ "$run" -lt "$REPEAT" ]; then
        log "다음 측정까지 30초 대기..."
        sleep 30
    fi
done

########################################
# 요약
########################################
phase "측정 완료: ${DIMM_CONFIG}"

log "생성된 파일:"
ls -la "$LOG_DIR/${DIMM_CONFIG}"* 2>/dev/null

echo ""
info "다음 단계:"
case "$DIMM_CONFIG" in
    32gb)
        echo "  1. 시스템 종료: sudo shutdown -h now"
        echo "  2. BIOS 진입 → DIMM 1개 비활성화 (또는 물리 제거)"
        echo "     - Alienware: F2로 BIOS 진입"
        echo "     - Memory Configuration → 슬롯 비활성화"
        echo "     - 또는 DIMM 물리적으로 제거 (전원 완전 차단 후)"
        echo "  3. 부팅 후 16GB 확인: free -h"
        echo "  4. 측정 실행: sudo -E $0 16gb"
        ;;
    16gb)
        echo "  1. (선택) DIMM 복구 후 재측정:"
        echo "     sudo -E $0 32gb_verify"
        echo "  2. 분석 실행:"
        echo "     python3 scripts/analysis/dimm_analysis.py"
        ;;
    32gb_verify)
        echo "  분석 실행:"
        echo "  python3 scripts/analysis/dimm_analysis.py"
        ;;
esac

echo ""
log "RPICT 데이터도 동시에 수집해야 합니다!"
log "Raspberry Pi에서: python3 rpict_logger.py -o rpict_dimm_${DIMM_CONFIG}.csv"
