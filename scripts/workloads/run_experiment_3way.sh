#!/bin/bash
# 3-way 동시실행 실험 (Three-Workload Concurrent Experiment)
#
# 목적: 2-way에서 3-way로 확장했을 때 에너지 귀속 모델의 일반성 검증
#       "조합을 다 해보기보다 한두 케이스 정도로 별 차이 없다는 정도면 족함" — 교수님
#
# 실험 케이스 (3가지):
#   Case 1: YOLO(GPU0) + ResNet(GPU1) + Node.js(CPU)  — AI+AI+NonAI (3-way)
#   Case 2: YOLO(GPU0) + GPT2(GPU1)   + ffmpeg(CPU)   — AI+AI+NonAI (3-way, 다른 NonAI)
#   Case 3: YOLO(GPU0) + GPT2(GPU1) + Node.js(CPU) + ffmpeg(CPU) — 4-way
#           (교수님 3월 메일: "3개 혹은 4개의 워크로드를 동시에")
#
# cgroup 구성:
#   yolo.slice    → Workload A (AI, GPU0): cpuset 0-1, 4GB
#   nodejs.slice  → Workload B (AI, GPU1): cpuset 2-3, 4GB
#   work.slice    → Workload C (NonAI, CPU only): cpuset 4-5, 4GB   ← 신규 생성
#   work2.slice   → Workload D (NonAI, CPU only): cpuset 6-7, 4GB   ← 4-way용
#
# Usage:
#   sudo -E ./run_experiment_3way.sh [RUN_NUM]
#   예) sudo -E ./run_experiment_3way.sh 1    → phase3_3way_run1

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
LOG_DIR="${INTEGRATED_LOG_DIR:-$BASE_DIR/data/raw/alienware/phase3_3way_run${RUN_NUM}}"
SCRIPT_DIR="$BASE_DIR/scripts/measurement"
WORKLOAD_DIR="$BASE_DIR/scripts/workloads"

CGROUP_ROOT="/sys/fs/cgroup"
YOLO_CGROUP="$CGROUP_ROOT/yolo.slice"      # Workload A (AI)
NODEJS_CGROUP="$CGROUP_ROOT/nodejs.slice"   # Workload B (AI in 3-way)
WORK_CGROUP="$CGROUP_ROOT/work.slice"       # Workload C (NonAI) — 신규
WORK2_CGROUP="$CGROUP_ROOT/work2.slice"     # Workload D (NonAI) — 4-way Case 3용

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
# work.slice cgroup 생성 및 설정
########################################
setup_work_cgroup() {
    log "work.slice cgroup 설정 중..."

    # work.slice 디렉토리 생성
    if [ ! -d "$WORK_CGROUP" ]; then
        mkdir -p "$WORK_CGROUP"
        log "work.slice 생성: $WORK_CGROUP"
    fi

    # cgroup v2 컨트롤러 활성화
    local parent_cgroup="$CGROUP_ROOT"
    if ! grep -q "cpuset" "$parent_cgroup/cgroup.controllers" 2>/dev/null; then
        warn "cpuset 컨트롤러가 루트에 없습니다."
    fi

    # subtree_control 활성화 (부모에서)
    echo "+cpuset +memory +cpu +io" > "$parent_cgroup/cgroup.subtree_control" 2>/dev/null || true

    # work.slice 설정: cpuset 4-5 (2코어), 4GB, cpu.max 200% (setup_cgroups.sh와 동일)
    echo "0"         > "$WORK_CGROUP/cpuset.mems"   2>/dev/null || warn "cpuset.mems 설정 실패"
    echo "4-5"       > "$WORK_CGROUP/cpuset.cpus"   2>/dev/null || warn "cpuset.cpus 설정 실패"
    echo "4294967296" > "$WORK_CGROUP/memory.max"   2>/dev/null || warn "memory.max 설정 실패 (4GB)"
    echo "200000 100000" > "$WORK_CGROUP/cpu.max"   2>/dev/null || warn "cpu.max 설정 실패"
    # memory.max = 4 * 1024^3 = 4294967296

    sleep 1
    log "work.slice 설정 완료:"
    log "  cpuset.cpus = $(cat $WORK_CGROUP/cpuset.cpus 2>/dev/null || echo 'N/A')"
    log "  memory.max  = $(cat $WORK_CGROUP/memory.max  2>/dev/null || echo 'N/A')"
}

########################################
# work2.slice cgroup 생성 및 설정 (4-way Case 3용)
########################################
setup_work2_cgroup() {
    log "work2.slice cgroup 설정 중..."

    if [ ! -d "$WORK2_CGROUP" ]; then
        mkdir -p "$WORK2_CGROUP"
        log "work2.slice 생성: $WORK2_CGROUP"
    fi

    # work2.slice 설정: cpuset 6-7 (2코어), 4GB, cpu.max 200% (setup_cgroups.sh와 동일)
    echo "0"          > "$WORK2_CGROUP/cpuset.mems" 2>/dev/null || warn "cpuset.mems 설정 실패"
    echo "6-7"        > "$WORK2_CGROUP/cpuset.cpus" 2>/dev/null || warn "cpuset.cpus 설정 실패"
    echo "4294967296" > "$WORK2_CGROUP/memory.max"  2>/dev/null || warn "memory.max 설정 실패 (4GB)"
    echo "200000 100000" > "$WORK2_CGROUP/cpu.max"  2>/dev/null || warn "cpu.max 설정 실패"

    sleep 1
    log "work2.slice 설정 완료:"
    log "  cpuset.cpus = $(cat $WORK2_CGROUP/cpuset.cpus 2>/dev/null || echo 'N/A')"
    log "  memory.max  = $(cat $WORK2_CGROUP/memory.max  2>/dev/null || echo 'N/A')"
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
    # express 확인 (node_modules는 gitignore — fresh clone엔 없음)
    ( cd "$WORKLOAD_DIR" && node -e "require('express')" ) 2>/dev/null || {
        echo "ERROR: express 미설치 → cd $WORKLOAD_DIR && npm install express"; exit 1; }
    command -v ffmpeg &>/dev/null  || warn "ffmpeg 미설치 (Case 2 건너뜀, sudo apt install ffmpeg)"

    local gpu_count
    gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
    if [ "$gpu_count" -lt 2 ]; then
        echo "ERROR: GPU 2장 필요 (현재 ${gpu_count}장). 3-way AI+AI+NonAI 불가."
        exit 1
    fi
    log "GPU ${gpu_count}장 확인 완료"

    # YOLO 테스트 비디오 확인 (*.mp4는 .gitignore라 clone에 미포함 — 없으면 YOLO가
    # FileNotFoundError 무한 루프에 빠져 GPU가 놀게 됨. run1에서 실제 발생한 문제)
    if [ ! -f "$WORKLOAD_DIR/test_video.mp4" ]; then
        warn "test_video.mp4 없음 — 합성 비디오 자동 생성 (기존 실험 원본이 있으면 교체 권장)"
        if command -v ffmpeg &>/dev/null; then
            ffmpeg -y -f lavfi -i "testsrc=duration=60:size=1280x720:rate=30" \
                -pix_fmt yuv420p "$WORKLOAD_DIR/test_video.mp4" &>/dev/null
            chown $REAL_UID:$REAL_GID "$WORKLOAD_DIR/test_video.mp4" 2>/dev/null || true
            log "합성 test_video.mp4 생성 완료 (1280x720@30fps, 60s testsrc)"
        else
            echo "ERROR: test_video.mp4 없음 + ffmpeg 미설치 → YOLO 실행 불가"
            exit 1
        fi
    fi
    log "test_video.mp4 확인: $(md5sum "$WORKLOAD_DIR/test_video.mp4" | cut -c1-8)... ($(du -h "$WORKLOAD_DIR/test_video.mp4" | cut -f1))"
}

########################################
# slice 상태 리셋 — 이전 run 잔재 제거
#
# systemd-run이 남긴 자식 scope + 활성 하위 컨트롤러가 있으면 cgroup v2의
# internal-node 규칙 때문에 slice에 프로세스를 직접 붙일 수 없다 (run2에서
# Node.js가 소리 없이 cgroup 밖에서 실행된 원인). 실험 시작 전 항상 리셋한다.
########################################
reset_slice() {
    local cg="$CGROUP_ROOT/$1"
    # systemd 유닛으로 등록돼 있으면 내림 — 주의: stop 시 systemd가 cgroup 디렉토리를
    # 함께 제거한다 (asym 재실행에서 실증). 직후 raw 디렉토리로 재생성하면
    # systemd 관리에서 완전히 벗어나 mid-run GC(빈 slice 제거)도 사라진다.
    systemctl stop "$1" 2>/dev/null || true
    sleep 0.2
    echo "+cpuset +memory +cpu +io" > "$CGROUP_ROOT/cgroup.subtree_control" 2>/dev/null || true
    mkdir -p "$cg" 2>/dev/null || true
    if [ ! -d "$cg" ]; then
        echo -e "${RED}[FATAL] cgroup 재생성 실패: $cg${NC}"
        exit 1
    fi
    local child
    for child in "$cg"/*/; do
        [ -d "$child" ] || continue
        if [ -f "$child/cgroup.procs" ]; then
            while read -r pid; do kill -9 "$pid" 2>/dev/null || true; done < "$child/cgroup.procs" 2>/dev/null
        fi
        sleep 0.3
        rmdir "$child" 2>/dev/null || warn "자식 cgroup 제거 실패: $child (프로세스 잔존?)"
    done
    # 하위 컨트롤러 비활성화 → 프로세스를 직접 붙일 수 있는 leaf 상태로 복귀
    # 켜져 있는 모든 하위 컨트롤러 해제 (pids 포함)
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
# 전역 PID
########################################
WL_A_PID=""; WL_B_PID=""; WL_C_PID=""
CURL_PID=""; NODE_PID=""
HOST_PID=""; CGROUP_PID=""

########################################
# AI 워크로드 시작 (yolo.slice 또는 nodejs.slice)
########################################
start_ai_workload() {
    local workload_type=$1  # yolo_medium | resnet18 | gpt2
    local gpu_id=$2
    local slice=$3
    local duration=$4
    local pid_var=$5
    local cg="$CGROUP_ROOT/$slice"
    local log_file="$LOG_DIR/${workload_type}_gpu${gpu_id}_${slice}.log"

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

    # systemd-run 대신 cgroup.procs 직접 등록.
    # systemd scope와 raw cgroup을 혼용하면 이전 run의 상태에 따라
    # "Job failed"(run1의 ffmpeg) 또는 attach 실패(run2의 Node.js/GPT2)가
    # 비결정적으로 발생 — 전 워크로드를 직접 등록으로 통일한다.
    # sudo -u로 uid를 되돌려도 cgroup 소속은 유지된다 (v2 상속).
    # 주의: 서브셸 안에서 $$는 메인 스크립트 PID를 반환한다 (bash 표준 동작).
    # $$를 쓰면 실험 스크립트 전체가 slice로 이동해 이후 모든 phase가 오염된다
    # (run1에서 실제 발생). 반드시 $BASHPID(서브셸 자신)를 사용한다.
    # setpriv: sudo와 달리 PAM을 타지 않아 cgroup 소속이 절대 바뀌지 않는다.
    clear_subtree "$cg"
    ( if ! attach_self "$cg"; then
          echo "[FATAL] cgroup attach 실패: $cg — reset_slice 미실행 또는 슬라이스 오염"
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
# Node.js Heavy (work.slice)
########################################
start_nodejs_3way() {
    local duration=$1

    # 서버를 work.slice에서 실행 — attach 실패를 절대 조용히 넘기지 않는다
    # (run2에서 || true 때문에 Node.js가 cgroup 밖에서 돌아 사용량이 통째로 누락됨)
    cd "$WORKLOAD_DIR"
    clear_subtree "$WORK_CGROUP"
    ( if ! attach_self "$WORK_CGROUP"; then
          echo "[FATAL] work.slice attach 실패 — Node.js가 cgroup 밖에서 실행됨"
          exit 1
      fi
      exec node "server_heavy.js" ) > "$LOG_DIR/nodejs_work.log" 2>&1 &
    NODE_PID=$!
    sleep 2
    if ! kill -0 $NODE_PID 2>/dev/null; then
        warn "Node.js 시작 실패! $LOG_DIR/nodejs_work.log 확인"
    fi
    log "Node.js 서버 시작 (PID: $NODE_PID, work.slice)"

    # Heavy 부하 (curl은 cgroup 밖에서 실행 — HTTP 클라이언트)
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
# ffmpeg Heavy (work.slice)
########################################
start_ffmpeg_3way() {
    local duration=$1
    local slice=${2:-work.slice}    # 기본 work.slice, 4-way에서는 work2.slice
    local prefix=${3:-ffmpeg}       # 로그 파일명 충돌 방지용 phase 프리픽스
    local cg="$CGROUP_ROOT/$slice"
    local log_file="$LOG_DIR/${prefix}_ffmpeg_${slice%.slice}.log"

    # systemd-run --slice는 (1) 프로세스가 직접 등록된 raw cgroup과 충돌해
    # "Job failed"로 죽고 (2) slice 재생성 시 cpuset 제한을 리셋한다 (run1에서
    # 실제 발생: work.slice 실패 + work2.slice 891% CPU).
    # → cgroup.procs 직접 등록 ($BASHPID — $$ 금지) 방식 사용.
    # ffmpeg_encode.py는 표준 라이브러리만 사용하므로 venv 불필요.
    clear_subtree "$cg"
    ( if ! attach_self "$cg"; then
          echo "[FATAL] cgroup attach 실패: $cg"
          exit 1
      fi
      exec timeout $((duration + 10)) env PYTHONUNBUFFERED=1 \
          python3 "$WORKLOAD_DIR/ffmpeg_encode.py" --duration $duration
    ) > "$log_file" 2>&1 &
    WL_C_PID=$!
    log "ffmpeg 시작 (PID: $WL_C_PID, $slice, log: $log_file)"
}

########################################
# 로거 시작 (cgroup_logger에 work.slice 포함)
########################################
start_loggers() {
    local prefix=$1
    local duration=$2
    python3 "$SCRIPT_DIR/host_logger.py" \
        -o "$LOG_DIR/${prefix}_host.csv" -d "$duration" -i 1 &
    HOST_PID=$!
    # cgroup_logger 기본값은 yolo.slice+nodejs.slice뿐이므로
    # work.slice/work2.slice를 반드시 명시해야 함 (미지정 시 3/4번째 워크로드 데이터 누락)
    python3 "$SCRIPT_DIR/cgroup_logger.py" \
        -c yolo.slice nodejs.slice work.slice work2.slice \
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
    [ -n "$WL_C_PID" ] && kill $WL_C_PID 2>/dev/null; WL_C_PID=""
    [ -n "$CURL_PID" ] && kill $CURL_PID 2>/dev/null; CURL_PID=""
    [ -n "$NODE_PID" ] && kill $NODE_PID 2>/dev/null; NODE_PID=""
    pkill -f "node.*server"       2>/dev/null || true
    pkill -f "resnet18_inference" 2>/dev/null || true
    pkill -f "gpt2_inference"     2>/dev/null || true
    pkill -f "yolo predict"       2>/dev/null || true
    pkill -f "ffmpeg_encode"      2>/dev/null || true
    pkill -f "ffmpeg.*testsrc"    2>/dev/null || true
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

    info "S1: YOLO (GPU0, yolo.slice, 20s)"
    start_ai_workload "yolo_medium" 0 "yolo.slice" 20 "WL_A_PID"
    sleep 20; stop_workloads
    smoke_check "$LOG_DIR/yolo_medium_gpu0_yolo.slice.log" "Ultralytics" "YOLO" || fail=1

    info "S2: ResNet (GPU0, yolo.slice, 15s)"
    start_ai_workload "resnet18" 0 "yolo.slice" 15 "WL_A_PID"
    sleep 15; stop_workloads
    smoke_check "$LOG_DIR/resnet18_gpu0_yolo.slice.log" "\[ResNet18\]" "ResNet" || fail=1

    info "S3: GPT2 (GPU0, yolo.slice, 25s — 모델 로드 포함)"
    start_ai_workload "gpt2" 0 "yolo.slice" 25 "WL_A_PID"
    sleep 25; stop_workloads
    smoke_check "$LOG_DIR/gpt2_gpu0_yolo.slice.log" "\[GPT-2\]" "GPT2" || fail=1

    # 주의: cgroupfs 파일은 stat 크기가 항상 0이라 [ -s ] 테스트 불가 → cat으로 판정
    info "S4: Node.js (work.slice, 12s)"
    start_nodejs_3way 12
    sleep 5
    if curl -s --max-time 3 "http://localhost:3000/" >/dev/null 2>&1 \
       && [ -n "$(cat "$WORK_CGROUP/cgroup.procs" 2>/dev/null)" ]; then
        log "  ✓ Node.js OK (응답 + work.slice 등록 확인)"
    else
        warn "  ✗ Node.js 실패 (응답 없음 또는 work.slice 미등록) → $LOG_DIR/nodejs_work.log"
        fail=1
    fi
    sleep 7; stop_workloads

    info "S5: ffmpeg (work.slice, 12s)"
    start_ffmpeg_3way 12 "work.slice" "smoke"
    sleep 3
    [ -n "$(cat "$WORK_CGROUP/cgroup.procs" 2>/dev/null)" ] || { warn "  ✗ ffmpeg work.slice 미등록"; fail=1; }
    sleep 9; stop_workloads
    smoke_check "$LOG_DIR/smoke_ffmpeg_work.log" "\[ffmpeg\] 시작" "ffmpeg" || fail=1

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
phase "3-way 동시실행 실험 — Run ${RUN_NUM}"
echo -e "${MAGENTA}Case 1: YOLO(GPU0) + ResNet(GPU1) + Node.js(CPU)${NC}"
echo -e "${MAGENTA}Case 2: YOLO(GPU0) + GPT2(GPU1)   + ffmpeg(CPU)${NC}"
echo -e "${MAGENTA}cgroup: yolo.slice(0-1) | nodejs.slice(2-3) | work.slice(4-5)${NC}"
echo -e "${MAGENTA}출력: $LOG_DIR${NC}"

check_prerequisites

# 이전 run 잔재(systemd scope 자식, 하위 컨트롤러) 정리 — 반드시 setup 전에
reset_slice "yolo.slice"
reset_slice "nodejs.slice"
reset_slice "work.slice"
reset_slice "work2.slice"

set_cpu_fixed
setup_work_cgroup
setup_work2_cgroup

mkdir -p "$LOG_DIR"
chown -R $REAL_UID:$REAL_GID "$LOG_DIR"

# 실험 설정 기록
cat > "$LOG_DIR/config.txt" << EOF
===== 3-Way Concurrent Workload Experiment =====
Date: $(date)
Run: ${RUN_NUM}

cgroup allocation (equal, 2 cores / 4GB each):
  yolo.slice   → cpuset 0-1, 4GB  (Workload A: AI, GPU0)
  nodejs.slice → cpuset 2-3, 4GB  (Workload B: AI, GPU1)
  work.slice   → cpuset 4-5, 4GB  (Workload C: NonAI, CPU only)
  work2.slice  → cpuset 6-7, 4GB  (Workload D: NonAI, CPU only, 4-way)

Cases:
  Case 1: YOLO(yolo.slice,GPU0) + ResNet(nodejs.slice,GPU1) + Node.js(work.slice)
  Case 2: YOLO(yolo.slice,GPU0) + GPT2(nodejs.slice,GPU1)   + ffmpeg(work.slice)
  Case 3: YOLO(yolo.slice,GPU0) + GPT2(nodejs.slice,GPU1)
          + Node.js(work.slice) + ffmpeg(work2.slice)        — 4-way

Purpose:
  Extend 2-way energy attribution model to 3-way and 4-way
  Verify model accuracy under 3/4-workload concurrent execution
  Expected: similar per-workload energy as in 2-way (energy profiles preserved)

Hardware: Alienware Aurora R12 (i7-11700F 8c/16t, RTX 3060 x2, 32GB DDR4)
EOF
chown $REAL_UID:$REAL_GID "$LOG_DIR/config.txt"

# 본 실험 전 스모크 테스트 — 실패 시 여기서 중단 (무효 run 방지)
smoke_test

EXPERIMENT_START=$SECONDS

########################################
# Phase 0: Baseline
########################################
phase "Phase 0: Baseline (Idle) - ${BASELINE_DURATION}s"
start_loggers "baseline" $BASELINE_DURATION
wait_loggers
drop_caches
log "Baseline 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Phase 1-3: Solo (2-way 결과와의 비교용)
########################################
phase "Phase 1: YOLO Solo (GPU0, yolo.slice) - ${WORKLOAD_DURATION}s"
info "2-way 실험 solo와 비교: 같아야 함 (에너지 프로파일 보존 확인)"
start_loggers "solo_yolo" $WORKLOAD_DURATION
sleep 2
start_ai_workload "yolo_medium" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

phase "Phase 2: ResNet Solo (GPU0, yolo.slice) - ${WORKLOAD_DURATION}s"
start_loggers "solo_resnet" $WORKLOAD_DURATION
sleep 2
start_ai_workload "resnet18" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

phase "Phase 3: Node.js Solo (work.slice) - ${WORKLOAD_DURATION}s"
start_nodejs_3way $WORKLOAD_DURATION
start_loggers "solo_nodejs" $WORKLOAD_DURATION
sleep 2
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

phase "Phase 3b: GPT2 Solo (GPU0, yolo.slice) - ${WORKLOAD_DURATION}s"
info "Case 2/3 검증용 solo 기준값 (동일 run 내 확보)"
start_loggers "solo_gpt2" $WORKLOAD_DURATION
sleep 2
start_ai_workload "gpt2" 0 "yolo.slice" $WORKLOAD_DURATION "WL_A_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

if command -v ffmpeg &>/dev/null; then
    phase "Phase 3c: ffmpeg Solo (work.slice) - ${WORKLOAD_DURATION}s"
    info "Case 2/3 검증용 solo 기준값 (동일 run 내 확보)"
    start_loggers "solo_ffmpeg" $WORKLOAD_DURATION
    sleep 2
    start_ffmpeg_3way $WORKLOAD_DURATION "work.slice" "solo"
    wait_loggers; stop_workloads; drop_caches
    sleep $COOLDOWN
fi

# GPU 디바이스 일치 solo 기준값 — concurrent에서 ResNet/GPT2는 GPU1에 배치되는데
# GPU0/GPU1은 idle·active 전력이 다르다 (run1 실측: 동일 ResNet이 GPU0 141W vs
# GPU1 163W). 검증 오차에서 디바이스 차이를 제거하려면 같은 디바이스의 solo가 필요.
phase "Phase 3d: ResNet Solo (GPU1, nodejs.slice) - ${WORKLOAD_DURATION}s"
info "Case 1 검증용: concurrent와 동일한 GPU1 배치 기준값"
start_loggers "solo_resnet_gpu1" $WORKLOAD_DURATION
sleep 2
start_ai_workload "resnet18" 1 "nodejs.slice" $WORKLOAD_DURATION "WL_B_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

phase "Phase 3e: GPT2 Solo (GPU1, nodejs.slice) - ${WORKLOAD_DURATION}s"
info "Case 2/3 검증용: concurrent와 동일한 GPU1 배치 기준값"
start_loggers "solo_gpt2_gpu1" $WORKLOAD_DURATION
sleep 2
start_ai_workload "gpt2" 1 "nodejs.slice" $WORKLOAD_DURATION "WL_B_PID"
wait_loggers; stop_workloads; drop_caches
sleep $COOLDOWN

########################################
# Case 1: YOLO + ResNet + Node.js (AI+AI+NonAI)
########################################
phase "Phase 4 [Case 1]: YOLO(GPU0) + ResNet(GPU1) + Node.js(CPU) — 3-way"
info "yolo.slice(cpuset 0-1) | nodejs.slice(cpuset 2-3) | work.slice(cpuset 4-5)"

start_nodejs_3way $WORKLOAD_DURATION
start_loggers "case1_yolo_resnet_nodejs" $WORKLOAD_DURATION
sleep 2

# Workload A: YOLO → GPU0, yolo.slice
start_ai_workload "yolo_medium" 0 "yolo.slice"   $WORKLOAD_DURATION "WL_A_PID"
# Workload B: ResNet → GPU1, nodejs.slice
start_ai_workload "resnet18"    1 "nodejs.slice"  $WORKLOAD_DURATION "WL_B_PID"
# Workload C: Node.js → CPU, work.slice (already started above)

wait_loggers
stop_workloads
drop_caches
log "Case 1 완료. Cooldown ${COOLDOWN}s..."
sleep $COOLDOWN

########################################
# Case 2: YOLO + GPT2 + ffmpeg (AI+AI+NonAI, 다른 NonAI)
########################################
if command -v ffmpeg &>/dev/null; then
    phase "Phase 5 [Case 2]: YOLO(GPU0) + GPT2(GPU1) + ffmpeg(CPU) — 3-way"
    info "yolo.slice(cpuset 0-1) | nodejs.slice(cpuset 2-3) | work.slice(cpuset 4-5)"

    start_loggers "case2_yolo_gpt2_ffmpeg" $WORKLOAD_DURATION
    sleep 2

    # Workload A: YOLO → GPU0, yolo.slice
    start_ai_workload "yolo_medium" 0 "yolo.slice"   $WORKLOAD_DURATION "WL_A_PID"
    # Workload B: GPT2 → GPU1, nodejs.slice
    start_ai_workload "gpt2"        1 "nodejs.slice"  $WORKLOAD_DURATION "WL_B_PID"
    # Workload C: ffmpeg → CPU, work.slice
    start_ffmpeg_3way $WORKLOAD_DURATION "work.slice" "case2"

    wait_loggers
    stop_workloads
    drop_caches
    log "Case 2 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
else
    warn "ffmpeg 미설치 → Case 2 (ffmpeg) 건너뜀"
    warn "  설치: sudo apt install ffmpeg 후 재실행"
fi

########################################
# Case 3: YOLO + GPT2 + Node.js + ffmpeg (4-way)
# 교수님 3월 메일: "3개 혹은 4개의 워크로드를 동시에"
########################################
if command -v ffmpeg &>/dev/null; then
    phase "Phase 6 [Case 3]: YOLO(GPU0) + GPT2(GPU1) + Node.js(CPU) + ffmpeg(CPU) — 4-way"
    info "yolo.slice(0-1) | nodejs.slice(2-3) | work.slice(4-5) | work2.slice(6-7)"

    start_nodejs_3way $WORKLOAD_DURATION
    start_loggers "case3_yolo_gpt2_nodejs_ffmpeg" $WORKLOAD_DURATION
    sleep 2

    # Workload A: YOLO → GPU0, yolo.slice
    start_ai_workload "yolo_medium" 0 "yolo.slice"   $WORKLOAD_DURATION "WL_A_PID"
    # Workload B: GPT2 → GPU1, nodejs.slice
    start_ai_workload "gpt2"        1 "nodejs.slice"  $WORKLOAD_DURATION "WL_B_PID"
    # Workload C: Node.js → CPU, work.slice (위에서 시작)
    # Workload D: ffmpeg → CPU, work2.slice
    start_ffmpeg_3way $WORKLOAD_DURATION "work2.slice" "case3"

    wait_loggers
    stop_workloads
    drop_caches
    log "Case 3 (4-way) 완료. Cooldown ${COOLDOWN}s..."
    sleep $COOLDOWN
else
    warn "ffmpeg 미설치 → Case 3 (4-way) 건너뜀"
fi

########################################
# 완료
########################################
ELAPSED=$((SECONDS - EXPERIMENT_START))
phase "3-way 실험 완료 — Run ${RUN_NUM}"
log "총 실험 시간: ${ELAPSED}초 (~$((ELAPSED / 60))분)"
echo ""
log "생성된 파일:"
ls -la "$LOG_DIR"
echo ""
log "다음 단계:"
echo "  1. RPICT 로깅 종료 → data/raw/rpict/phase3_3way_run${RUN_NUM}.csv 저장"
echo "  2. 분석:"
echo "     - Case 1 vs 2-way(YOLO+ResNet) 비교 → 3-way에서 에너지 프로파일 보존 확인"
echo "     - Case 2 vs 2-way(YOLO+GPT2) 비교   → ffmpeg 추가 시 AI 워크로드 영향 확인"
echo ""
log "실험 완료: phase3_3way_run${RUN_NUM}"
