#!/bin/bash
# Phase 2.1: fio Storage 에너지 실험 (v2 - 교수님 피드백 반영)
#
# 목적: Storage IO에 의한 순수 에너지 파라미터(W per MB/s) 도출
#   Storage_power = Wall(RPICT) - Wall_idle(RPICT) - dCPU(RAPL) - dGPU(nvidia-smi)
#   Storage_rate  = Storage_power / Throughput(MB/s)
#
# 핵심 변경 (v1 대비):
#   - Random IO 제거 (교수님: "SSD이므로 sequential만 측정하면 됨")
#   - Config A 환경(2GPU+2DIMM)에서 실행 (동시실행 실험과 동일 환경)
#   - RPICT 동시 측정 필수 → 분석 시 CPU/GPU delta 분리
#
# 실험 구성:
#   1. Idle Baseline (워크로드 없음)
#   2. Sequential Read  (bs=1M, iodepth=32, direct=1)
#   3. Sequential Write (bs=1M, iodepth=32, direct=1)
#
# Usage:
#   sudo -E ./run_fio_experiment.sh [test_name]
#
# 주의:
#   - fio가 설치되어 있어야 함: sudo apt install fio
#   - Direct IO 사용하여 페이지 캐시 우회
#   - /tmp/fio_test 파일 사용 (4GB) → 실험 후 삭제
#   - RPICT를 반드시 동시에 수집할 것!

set +e

if [ "$EUID" -ne 0 ]; then
    echo "Error: sudo로 실행하세요."
    echo "Usage: sudo -E $0 [test_name]"
    exit 1
fi

REAL_UID=${SUDO_UID:-$(id -u)}
REAL_GID=${SUDO_GID:-$(id -g)}

# fio 설치 확인
if ! command -v fio &> /dev/null; then
    echo "Error: fio가 설치되어 있지 않습니다."
    echo "  sudo apt install fio"
    exit 1
fi

# 설정
TEST_NAME=${1:-"fio_$(date +%Y%m%d_%H%M%S)"}
BASE_DIR="$HOME/vm-power-attribution"
LOG_DIR="$BASE_DIR/data/raw/alienware/phase2.1_fio"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"

FIO_FILE="/tmp/fio_test"     # fio 테스트 파일 경로
FIO_SIZE="4G"                # 테스트 파일 크기

# 시간 설정 (초)
IDLE_DURATION=60             # Idle 측정
FIO_DURATION=60              # 각 fio 테스트
COOLDOWN=30                  # 쿨다운

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

cleanup() {
    log "정리 중..."
    # fio 프로세스 정리
    pkill -f "fio" 2>/dev/null || true
    # 테스트 파일 삭제
    rm -f "$FIO_FILE" 2>/dev/null || true
    log "정리 완료"
}

trap cleanup EXIT

# ── CPU 환경 통제 (component isolation과 동일하게) ──
PSTATE_DIR="/sys/devices/system/cpu/intel_pstate"
if [ -d "$PSTATE_DIR" ]; then
    ORIG_NO_TURBO=$(cat "$PSTATE_DIR/no_turbo" 2>/dev/null)
    echo 1 > "$PSTATE_DIR/no_turbo"
    log "no_turbo 설정: $(cat $PSTATE_DIR/no_turbo) (Turbo Boost OFF)"
else
    warn "intel_pstate 미지원 → no_turbo 설정 불가"
    ORIG_NO_TURBO=""
fi

# CPU governor → powersave (component isolation과 동일)
ORIG_GOVERNOR=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)
for cpu_dir in /sys/devices/system/cpu/cpu*/cpufreq; do
    echo "powersave" > "$cpu_dir/scaling_governor" 2>/dev/null || true
done
log "CPU governor: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)"

# GPU persistence mode (측정 안정성)
nvidia-smi -pm 1 > /dev/null 2>&1 || true

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

# fio 실행 + 전력 측정 함수
run_fio_phase() {
    local phase_name=$1    # 예: seq_read
    local rw=$2            # read, write, randread, randwrite
    local bs=$3            # 1M, 4K 등
    local iodepth=$4       # IO depth

    local host_file="$LOG_DIR/${phase_name}_host.csv"
    local fio_json="$LOG_DIR/${phase_name}_fio.json"

    phase "fio: $phase_name (rw=$rw, bs=$bs, iodepth=$iodepth)"

    # host_logger 시작 (fio보다 먼저 시작, 나중에 종료)
    local measure_duration=$((FIO_DURATION + 10))
    python3 "$SCRIPT_DIR/host_logger.py" \
        -o "$host_file" \
        -d "$measure_duration" \
        -i 1 &
    local HOST_PID=$!

    # 3초 대기 후 fio 시작 (host_logger가 idle baseline 캡처)
    sleep 3

    log "fio 시작: $rw (bs=$bs)"

    # fio 실행
    fio --name="$phase_name" \
        --ioengine=libaio \
        --direct=1 \
        --rw="$rw" \
        --bs="$bs" \
        --iodepth="$iodepth" \
        --size="$FIO_SIZE" \
        --numjobs=1 \
        --runtime="$FIO_DURATION" \
        --time_based \
        --filename="$FIO_FILE" \
        --output-format=json \
        --output="$fio_json" \
        --group_reporting \
        2>/dev/null

    local fio_exit=$?
    if [ $fio_exit -ne 0 ]; then
        warn "fio 종료 코드: $fio_exit"
    fi

    # host_logger 종료 대기
    wait $HOST_PID 2>/dev/null

    # fio 결과 요약 출력
    if [ -f "$fio_json" ]; then
        log "fio 결과:"
        python3 -c "
import json, sys
try:
    with open('$fio_json') as f:
        data = json.load(f)
    job = data['jobs'][0]
    if 'read' in '$rw':
        bw = job['read']['bw'] / 1024  # KB/s -> MB/s
        iops = job['read']['iops']
        lat = job['read']['lat_ns']['mean'] / 1000  # ns -> us
        print(f'  Throughput: {bw:.1f} MB/s')
        print(f'  IOPS: {iops:.0f}')
        print(f'  Avg Latency: {lat:.1f} us')
    if 'write' in '$rw':
        bw = job['write']['bw'] / 1024
        iops = job['write']['iops']
        lat = job['write']['lat_ns']['mean'] / 1000
        print(f'  Throughput: {bw:.1f} MB/s')
        print(f'  IOPS: {iops:.0f}')
        print(f'  Avg Latency: {lat:.1f} us')
except Exception as e:
    print(f'  (JSON 파싱 실패: {e})')
" 2>/dev/null
    fi

    chown $REAL_UID:$REAL_GID "$host_file" "$fio_json" 2>/dev/null

    log "$phase_name 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
}

########################################
# 메인 시작
########################################

phase "Phase 2.0b: fio Storage 에너지 실험"

# 시스템 정보 저장
cat > "$LOG_DIR/config.txt" << EOF
Experiment: fio Storage Energy Measurement
Date: $(date)
Test Name: $TEST_NAME

Storage:
$(lsblk -d -o NAME,SIZE,MODEL,ROTA 2>/dev/null)

fio Settings:
  File: $FIO_FILE
  Size: $FIO_SIZE
  Duration per test: ${FIO_DURATION}s

Tests:
  1. idle_baseline  - No IO
  2. seq_read       - Sequential Read  (bs=1M, iodepth=32)
  3. seq_write      - Sequential Write (bs=1M, iodepth=32)

CPU Environment Control:
  no_turbo: $(cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || echo 'N/A')
  governor: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo 'N/A')
  max_freq: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null || echo 'N/A') kHz

GPU:
$(nvidia-smi --query-gpu=index,name,persistence_mode,power.draw --format=csv,noheader 2>/dev/null || echo '  N/A')

Environment: Config A (2GPU+2DIMM, 32GB) - 동시실행 실험과 동일
Note: Random IO 제거 (SSD sequential만 필요 - 교수님 피드백)
Note: v2 재실험 - no_turbo=1, governor=powersave 강제 (component isolation과 동일 환경)
EOF

info "Storage: $(lsblk -dn -o MODEL /dev/nvme0n1 2>/dev/null || echo 'unknown')"
info "테스트 파일: $FIO_FILE ($FIO_SIZE)"
info "각 테스트: ${FIO_DURATION}초, 쿨다운: ${COOLDOWN}초"

########################################
# Phase 0: Idle Baseline
########################################
phase "Phase 0: Idle Baseline (${IDLE_DURATION}s)"
info "IO 없는 순수 Idle 상태 측정"

python3 "$SCRIPT_DIR/host_logger.py" \
    -o "$LOG_DIR/idle_baseline_host.csv" \
    -d "$IDLE_DURATION" \
    -i 1 &
HOST_PID=$!
wait $HOST_PID 2>/dev/null

chown $REAL_UID:$REAL_GID "$LOG_DIR/idle_baseline_host.csv"
log "Idle baseline 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Pre-create: fio 테스트 파일 생성 (실제 데이터 쓰기)
########################################
phase "테스트 파일 준비"

if [ ! -f "$FIO_FILE" ]; then
    log "fio 테스트 파일 생성 중... ($FIO_SIZE) - 실제 데이터 쓰기"
    fio --name=precreate --filename="$FIO_FILE" \
        --size="$FIO_SIZE" --rw=write --bs=1M \
        --ioengine=libaio --direct=1 --iodepth=32 \
        --numjobs=1 2>/dev/null
    log "테스트 파일 생성 완료 (실제 데이터 기록됨)"
    sleep 10  # 쓰기 캐시 플러시 대기
    sync
    log "sync 완료"
else
    log "기존 테스트 파일 사용: $FIO_FILE"
fi

########################################
# Phase 1: Sequential Write (먼저 실행)
########################################
run_fio_phase "seq_write" "write" "1M" "32"

########################################
# Phase 2: Sequential Read (write 후 실행 → 실제 SSD 데이터 읽기)
# Page cache drop하여 SSD에서 직접 읽도록 보장
########################################
phase "Page cache 플러시 (seq_read 준비)"
sync
echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
log "Page cache dropped. 10초 안정화 대기..."
sleep 10

run_fio_phase "seq_read" "read" "1M" "32"

########################################
# 완료
########################################
phase "fio 실험 완료"

log "생성된 파일:"
ls -la "$LOG_DIR/"

echo ""
info "파일 목록:"
echo "  [전력 측정]"
echo "  idle_baseline_host.csv   - Idle 전력"
echo "  seq_read_host.csv        - Sequential Read 전력"
echo "  seq_write_host.csv       - Sequential Write 전력"
echo ""
echo "  [fio 결과]"
echo "  seq_read_fio.json        - Sequential Read 성능"
echo "  seq_write_fio.json       - Sequential Write 성능"

TOTAL_TIME=$((IDLE_DURATION + (FIO_DURATION + 10 + COOLDOWN) * 2 + COOLDOWN + 10))
echo ""
log "총 실험 시간: ~${TOTAL_TIME}초 (~$((TOTAL_TIME / 60))분)"

echo ""
info "다음 단계:"
echo "  1. RPICT 데이터도 동시에 수집해야 합니다!"
echo "     Raspberry Pi에서: python3 rpict_logger.py -o rpict_fio.csv"
echo "  2. 분석 스크립트 실행:"
echo "     python3 scripts/analysis/fio_analysis.py"
echo ""

# 테스트 파일 삭제 (cleanup에서 처리되지만 명시적으로도)
log "테스트 파일 삭제: $FIO_FILE"
rm -f "$FIO_FILE"
