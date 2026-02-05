#!/bin/bash
# cgroup v2 설정 스크립트: YOLO와 Node.js 응용 분리
#
# 사용법:
#   sudo ./setup_cgroups.sh         # cgroup 생성 및 설정
#   sudo ./setup_cgroups.sh cleanup # cgroup 삭제
#
# 요구사항:
#   - cgroup v2가 마운트되어 있어야 함 (/sys/fs/cgroup)
#   - root 권한 필요

set -e

CGROUP_ROOT="/sys/fs/cgroup"
YOLO_SLICE="yolo.slice"
NODEJS_SLICE="nodejs.slice"

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_cgroup_v2() {
    if [ ! -f "$CGROUP_ROOT/cgroup.controllers" ]; then
        error "cgroup v2가 마운트되어 있지 않습니다."
        echo "다음 명령으로 확인하세요: mount | grep cgroup"
        exit 1
    fi
    log "cgroup v2 확인됨: $CGROUP_ROOT"
}

enable_controllers() {
    log "컨트롤러 활성화 중..."

    # 사용 가능한 컨트롤러 확인
    AVAILABLE=$(cat "$CGROUP_ROOT/cgroup.controllers")
    log "사용 가능한 컨트롤러: $AVAILABLE"

    # subtree_control에 컨트롤러 추가
    # cpuset이 없을 수 있으므로 개별 추가
    for ctrl in cpu memory io cpuset; do
        if echo "$AVAILABLE" | grep -q "$ctrl"; then
            echo "+$ctrl" > "$CGROUP_ROOT/cgroup.subtree_control" 2>/dev/null || true
        fi
    done

    ENABLED=$(cat "$CGROUP_ROOT/cgroup.subtree_control")
    log "활성화된 컨트롤러: $ENABLED"
}

create_cgroup() {
    local name=$1
    local cpus=$2
    local mem_bytes=$3

    local path="$CGROUP_ROOT/$name"

    if [ -d "$path" ]; then
        warn "$name 이미 존재함, 설정만 업데이트"
    else
        log "$name cgroup 생성 중..."
        mkdir -p "$path"
    fi

    # CPU 설정
    if [ -f "$path/cpuset.cpus" ]; then
        echo "$cpus" > "$path/cpuset.cpus"
        log "  cpuset.cpus = $cpus"
    fi

    # cpuset.mems 설정 (NUMA 노드, 보통 0)
    if [ -f "$path/cpuset.mems" ]; then
        echo "0" > "$path/cpuset.mems"
        log "  cpuset.mems = 0"
    fi

    # CPU 쿼터 설정 (200% = 2코어 full)
    # cpu.max: quota period (마이크로초)
    # 200000 100000 = 200ms quota per 100ms period = 200%
    if [ -f "$path/cpu.max" ]; then
        echo "200000 100000" > "$path/cpu.max"
        log "  cpu.max = 200000 100000 (200%)"
    fi

    # 메모리 제한
    if [ -f "$path/memory.max" ]; then
        echo "$mem_bytes" > "$path/memory.max"
        local mem_gb=$((mem_bytes / 1024 / 1024 / 1024))
        log "  memory.max = ${mem_gb}GB"
    fi

    # IO 가중치 (기본값 100)
    if [ -f "$path/io.weight" ]; then
        echo "100" > "$path/io.weight" 2>/dev/null || true
    fi
}

setup() {
    log "=== cgroup v2 설정 시작 ==="

    check_cgroup_v2
    enable_controllers

    # YOLO cgroup: 코어 0-1, 4GB
    create_cgroup "$YOLO_SLICE" "0-1" "4294967296"

    # Node.js cgroup: 코어 2-3, 4GB
    create_cgroup "$NODEJS_SLICE" "2-3" "4294967296"

    log "=== cgroup 설정 완료 ==="
    echo ""
    log "확인:"
    echo "  YOLO:    ls -la $CGROUP_ROOT/$YOLO_SLICE/"
    echo "  Node.js: ls -la $CGROUP_ROOT/$NODEJS_SLICE/"
    echo ""
    log "프로세스 할당 방법:"
    echo "  echo \$PID | sudo tee $CGROUP_ROOT/$YOLO_SLICE/cgroup.procs"
    echo "  또는 스크립트 내에서:"
    echo "  echo \$\$ > $CGROUP_ROOT/$YOLO_SLICE/cgroup.procs && exec command"
}

cleanup() {
    log "=== cgroup 정리 시작 ==="

    for slice in "$YOLO_SLICE" "$NODEJS_SLICE"; do
        local path="$CGROUP_ROOT/$slice"
        if [ -d "$path" ]; then
            # 프로세스가 있으면 먼저 종료
            if [ -f "$path/cgroup.procs" ]; then
                local pids=$(cat "$path/cgroup.procs")
                if [ -n "$pids" ]; then
                    warn "$slice에 프로세스 존재: $pids"
                    warn "프로세스를 먼저 종료하세요"
                    continue
                fi
            fi

            rmdir "$path" 2>/dev/null && log "$slice 삭제됨" || warn "$slice 삭제 실패"
        else
            log "$slice 존재하지 않음"
        fi
    done

    log "=== cgroup 정리 완료 ==="
}

show_status() {
    log "=== cgroup 상태 ==="

    for slice in "$YOLO_SLICE" "$NODEJS_SLICE"; do
        local path="$CGROUP_ROOT/$slice"
        echo ""
        echo "[$slice]"

        if [ ! -d "$path" ]; then
            echo "  (존재하지 않음)"
            continue
        fi

        [ -f "$path/cpuset.cpus" ] && echo "  cpuset.cpus: $(cat $path/cpuset.cpus)"
        [ -f "$path/cpu.max" ] && echo "  cpu.max: $(cat $path/cpu.max)"
        [ -f "$path/memory.max" ] && echo "  memory.max: $(cat $path/memory.max) bytes"
        [ -f "$path/memory.current" ] && echo "  memory.current: $(cat $path/memory.current) bytes"
        [ -f "$path/cgroup.procs" ] && echo "  프로세스: $(cat $path/cgroup.procs | wc -l)개"
    done
}

# 메인
case "${1:-setup}" in
    setup)
        setup
        ;;
    cleanup)
        cleanup
        ;;
    status)
        show_status
        ;;
    *)
        echo "사용법: $0 {setup|cleanup|status}"
        exit 1
        ;;
esac
