#!/bin/bash
# Phase 2.0: 컴포넌트 물리 분리 실험 — Others 완전 분해
#
# 목적: GPU/DIMM 물리 조합 4가지로 각 컴포넌트의 idle 전력을 분리
#
# ┌──────────┬───────────────┬──────────────────────────────┐
# │  Config  │   하드웨어    │         분리 가능 항목       │
# ├──────────┼───────────────┼──────────────────────────────┤
# │    A     │ 2GPU + 2DIMM  │ Full baseline                │
# │    B     │ 2GPU + 1DIMM  │ Memory_per_DIMM = A - B      │
# │    C     │ 1GPU + 1DIMM  │ GPU_idle_per_card = B - C     │
# │    D     │ 1GPU + 2DIMM  │ Cross-validation (D - C = DIMM)│
# └──────────┴───────────────┴──────────────────────────────┘
#
# 물리 변경 순서 (1회 변경/단계):
#   A: 현재 상태 (변경 없음)
#   B: DIMM 1개 제거
#   C: GPU 1개 제거  (DIMM은 그대로 1개)
#   D: DIMM 재장착   (GPU는 그대로 1개)
#   (선택) A_verify: GPU 재장착 → 원래 상태 복원 검증
#
# 결과:
#   Memory_per_DIMM   = (A - B) 및 (D - C) 로 교차 검증
#   GPU_idle_per_card = (A - D) 및 (B - C) 로 교차 검증
#   Fixed_Others      = Wall - CPU(RAPL) - GPU(nvidia) - Memory - Storage_idle
#
# Usage:
#   sudo -E ./run_component_isolation.sh A    # 2GPU + 2DIMM
#   sudo -E ./run_component_isolation.sh B    # 2GPU + 1DIMM
#   sudo -E ./run_component_isolation.sh C    # 1GPU + 1DIMM
#   sudo -E ./run_component_isolation.sh D    # 1GPU + 2DIMM
#   sudo -E ./run_component_isolation.sh A_verify  # 복원 검증

set +e

if [ "$EUID" -ne 0 ]; then
    echo "Error: sudo로 실행하세요."
    echo "Usage: sudo -E $0 {A|B|C|D|A_verify}"
    exit 1
fi

REAL_UID=${SUDO_UID:-$(id -u)}
REAL_GID=${SUDO_GID:-$(id -g)}

CONFIG=${1:-""}
if [ -z "$CONFIG" ]; then
    echo "Usage: sudo -E $0 {A|B|C|D|A_verify}"
    echo ""
    echo "  A         2GPU + 2DIMM (32GB)   ← 시작점"
    echo "  B         2GPU + 1DIMM (16GB)   ← DIMM 1개 제거"
    echo "  C         1GPU + 1DIMM (16GB)   ← GPU 1개 제거"
    echo "  D         1GPU + 2DIMM (32GB)   ← DIMM 재장착"
    echo "  A_verify  2GPU + 2DIMM (32GB)   ← GPU 재장착, 복원 검증"
    exit 1
fi

# 기대 하드웨어 구성
declare -A EXPECT_GPU EXPECT_MEM CONFIG_DESC
EXPECT_GPU=( [A]=2 [B]=2 [C]=1 [D]=1 [A_verify]=2 )
EXPECT_MEM=( [A]=32 [B]=16 [C]=16 [D]=32 [A_verify]=32 )
CONFIG_DESC=( [A]="2GPU+2DIMM(32GB)" [B]="2GPU+1DIMM(16GB)" [C]="1GPU+1DIMM(16GB)" [D]="1GPU+2DIMM(32GB)" [A_verify]="2GPU+2DIMM(32GB) verify" )

if [ -z "${EXPECT_GPU[$CONFIG]}" ]; then
    echo "Error: 유효하지 않은 config: $CONFIG"
    echo "유효한 값: A, B, C, D, A_verify"
    exit 1
fi

# 설정
BASE_DIR="$HOME/vm-power-attribution"
LOG_DIR="$BASE_DIR/data/raw/alienware/phase2.0_component"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"

WARMUP=60
MEASURE=300      # 5분
REPEAT=3
INTERVAL=1

# 색상
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

log()   { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
phase() { echo -e "\n${CYAN}========================================${NC}"; echo -e "${CYAN}$1${NC}"; echo -e "${CYAN}========================================${NC}"; }

mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

########################################
# 하드웨어 검증
########################################
verify_hardware() {
    phase "하드웨어 검증: Config $CONFIG = ${CONFIG_DESC[$CONFIG]}"

    # GPU 수 확인
    local gpu_count=0
    if command -v nvidia-smi &>/dev/null; then
        gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
        gpu_count=$(echo "$gpu_count" | tr -d ' ')
    fi

    # RAM 크기 확인
    local mem_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    local mem_gb=$((mem_kb / 1024 / 1024))

    local expected_gpu=${EXPECT_GPU[$CONFIG]}
    local expected_mem=${EXPECT_MEM[$CONFIG]}

    log "감지된 GPU: ${gpu_count}개 (기대: ${expected_gpu}개)"
    log "감지된 RAM: ${mem_gb}GB (기대: ${expected_mem}GB)"

    local hw_ok=true

    if [ "$gpu_count" -ne "$expected_gpu" ]; then
        warn "GPU 수 불일치! 감지=${gpu_count}, 기대=${expected_gpu}"
        hw_ok=false
    fi

    # 메모리는 ±4GB 허용 (OS 예약 등)
    local mem_diff=$((mem_gb - expected_mem))
    if [ "$mem_diff" -lt -4 ] || [ "$mem_diff" -gt 4 ]; then
        warn "RAM 크기 불일치! 감지=${mem_gb}GB, 기대=${expected_mem}GB"
        hw_ok=false
    fi

    if [ "$hw_ok" = false ]; then
        echo ""
        warn "하드웨어가 Config $CONFIG 기대값과 다릅니다."
        read -p "계속 진행하시겠습니까? (y/N): " confirm
        [ "$confirm" != "y" ] && exit 1
    else
        log "하드웨어 검증 통과!"
    fi
}

########################################
# CPU 주파수 고정 (DVFS 제어)
########################################
lock_cpu_frequency() {
    phase "CPU 주파수 고정 (idle 실험 일관성 보장)"

    # 현재 governor 확인
    local current_gov=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)
    log "현재 CPU governor: $current_gov"

    # powersave governor 설정 (최저 주파수 고정)
    local changed=0
    for gov_file in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        if [ -f "$gov_file" ]; then
            echo "powersave" > "$gov_file" 2>/dev/null && changed=$((changed+1))
        fi
    done
    log "CPU governor -> powersave: ${changed}개 코어 설정"

    # Turbo Boost 비활성화
    if [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
        echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null
        log "Intel Turbo Boost: 비활성화"
    fi

    # 확인: 실제 주파수 읽기
    sleep 1
    local freq_khz=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null)
    local freq_mhz=$((freq_khz / 1000))
    log "현재 CPU0 주파수: ${freq_mhz}MHz"

    local min_freq=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq 2>/dev/null)
    local min_mhz=$((min_freq / 1000))
    log "최소 주파수: ${min_mhz}MHz"

    if [ "$freq_khz" -le $((min_freq + 200000)) ]; then
        log "CPU 주파수 고정 확인: 최저 근처에서 안정"
    else
        warn "CPU 주파수가 예상보다 높음 (${freq_mhz}MHz). 측정에 영향 가능"
    fi
}

restore_cpu_frequency() {
    # 실험 후 원래 설정 복원
    info "CPU 설정 복원 중..."
    for gov_file in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        echo "powersave" > "$gov_file" 2>/dev/null || true
    done
    if [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
        echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || true
    fi
    log "CPU Turbo Boost 복원, governor 유지(powersave)"
}

########################################
# 시스템 정보 수집
########################################
collect_system_info() {
    local info_file="$LOG_DIR/config_${CONFIG}_system_info.txt"

    echo "=== Component Isolation: Config $CONFIG ===" > "$info_file"
    echo "Description: ${CONFIG_DESC[$CONFIG]}" >> "$info_file"
    echo "Date: $(date)" >> "$info_file"
    echo "" >> "$info_file"

    echo "--- GPU Info ---" >> "$info_file"
    nvidia-smi 2>/dev/null >> "$info_file" 2>&1
    echo "" >> "$info_file"

    echo "--- Memory ---" >> "$info_file"
    free -h >> "$info_file" 2>&1
    echo "" >> "$info_file"

    echo "--- DIMM Info ---" >> "$info_file"
    dmidecode -t memory 2>/dev/null | grep -E "(Size|Locator|Speed|Type)" >> "$info_file" 2>&1
    echo "" >> "$info_file"

    echo "--- CPU ---" >> "$info_file"
    lscpu | head -20 >> "$info_file" 2>&1
    echo "" >> "$info_file"

    echo "--- Temperatures ---" >> "$info_file"
    sensors 2>/dev/null >> "$info_file" 2>&1
    echo "" >> "$info_file"

    echo "--- CPU Governor & Frequency ---" >> "$info_file"
    echo "governor: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)" >> "$info_file"
    echo "no_turbo: $(cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null)" >> "$info_file"
    for i in 0 1 2 3; do
        local f=$(cat /sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq 2>/dev/null)
        echo "cpu${i}_freq_khz: $f" >> "$info_file"
    done
    echo "" >> "$info_file"

    echo "--- Storage ---" >> "$info_file"
    lsblk -d -o NAME,SIZE,MODEL,ROTA 2>/dev/null >> "$info_file" 2>&1
    echo "" >> "$info_file"

    chown $REAL_UID:$REAL_GID "$info_file"
    log "시스템 정보 저장: $info_file"
}

########################################
# Idle 측정
########################################
run_idle_measurement() {
    local run_num=$1
    local host_file="$LOG_DIR/config_${CONFIG}_run${run_num}_host.csv"

    log "측정 시작: Config $CONFIG run${run_num} (${MEASURE}초)"

    python3 "$SCRIPT_DIR/host_logger.py" \
        -o "$host_file" \
        -d "$MEASURE" \
        -i "$INTERVAL" &
    local HOST_PID=$!

    wait $HOST_PID 2>/dev/null

    chown $REAL_UID:$REAL_GID "$host_file"
    log "측정 완료: $host_file"

    # 간단한 요약
    if [ -f "$host_file" ]; then
        local lines=$(wc -l < "$host_file")
        log "  기록: $((lines - 1)) samples"
    fi
}

########################################
# 메인
########################################
phase "Phase 2.0: Component Isolation — Config $CONFIG"
echo -e "${CYAN}  ${CONFIG_DESC[$CONFIG]}${NC}"
echo ""

# 하드웨어 검증
verify_hardware

# CPU 주파수 고정 (4개 config 간 일관성)
lock_cpu_frequency

# 시스템 정보 (CPU 고정 후 기록)
collect_system_info

# 안정화 대기
info "시스템 안정화 대기 중... (${WARMUP}초)"
info "이미 안정화됐으면 Ctrl+C로 건너뛸 수 있습니다."

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
    phase "측정 ${run}/${REPEAT}: Config $CONFIG idle"

    run_idle_measurement "$run"

    if [ "$run" -lt "$REPEAT" ]; then
        log "다음 측정까지 30초 대기..."
        sleep 30
    fi
done

########################################
# CPU 복원 & 요약
########################################
restore_cpu_frequency

phase "Config $CONFIG 측정 완료!"

log "생성된 파일:"
ls -la "$LOG_DIR/config_${CONFIG}"* 2>/dev/null

echo ""
info "=== 다음 단계 ==="
case "$CONFIG" in
    A)
        echo -e "  ${GREEN}현재: A (2GPU + 2DIMM) 완료${NC}"
        echo ""
        echo "  다음: Config B (2GPU + 1DIMM)"
        echo "    1. sudo shutdown -h now"
        echo "    2. 전원 완전 차단 (PSU 스위치 OFF)"
        echo "    3. DIMM 1개 물리적 제거"
        echo "    4. 부팅 → free -h 로 16GB 확인"
        echo "    5. sudo -E $0 B"
        ;;
    B)
        echo -e "  ${GREEN}현재: B (2GPU + 1DIMM) 완료${NC}"
        echo ""
        echo "  다음: Config C (1GPU + 1DIMM)"
        echo "    1. sudo shutdown -h now"
        echo "    2. 전원 완전 차단"
        echo "    3. GPU 1개 물리적 제거 (DIMM은 그대로 1개)"
        echo "    4. 부팅 → nvidia-smi 로 GPU 1개 확인"
        echo "    5. sudo -E $0 C"
        ;;
    C)
        echo -e "  ${GREEN}현재: C (1GPU + 1DIMM) 완료${NC}"
        echo ""
        echo "  다음: Config D (1GPU + 2DIMM)"
        echo "    1. sudo shutdown -h now"
        echo "    2. 전원 완전 차단"
        echo "    3. DIMM 1개 재장착 (GPU는 그대로 1개)"
        echo "    4. 부팅 → free -h 로 32GB 확인"
        echo "    5. sudo -E $0 D"
        ;;
    D)
        echo -e "  ${GREEN}현재: D (1GPU + 2DIMM) 완료${NC}"
        echo ""
        echo "  (선택) 복원 검증: Config A_verify"
        echo "    1. sudo shutdown -h now"
        echo "    2. GPU 재장착 → 원래 상태"
        echo "    3. sudo -E $0 A_verify"
        echo ""
        echo "  또는 바로 분석:"
        echo "    python3 scripts/analysis/component_isolation_analysis.py"
        ;;
    A_verify)
        echo -e "  ${GREEN}모든 Config 완료!${NC}"
        echo ""
        echo "  분석 실행:"
        echo "    python3 scripts/analysis/component_isolation_analysis.py"
        ;;
esac

echo ""
log "중요: RPICT 데이터도 동시에 수집해야 합니다!"
log "Raspberry Pi: python3 rpict_logger.py -o rpict_component_${CONFIG}.csv"
