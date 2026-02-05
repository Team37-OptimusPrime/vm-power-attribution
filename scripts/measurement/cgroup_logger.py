#!/usr/bin/env python3
"""
cgroup v2 리소스 사용량 로거
응용별 CPU, 메모리, IO 사용량을 측정하여 CSV로 출력

Usage:
    python3 cgroup_logger.py                          # 기본 cgroup 모니터링
    python3 cgroup_logger.py -c yolo.slice nodejs.slice  # 특정 cgroup 지정
    python3 cgroup_logger.py -o cgroup_stats.csv -d 60   # 파일 출력, 60초 동안
"""

import argparse
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


CGROUP_ROOT = Path("/sys/fs/cgroup")


class CgroupReader:
    """cgroup v2 통계 읽기"""

    def __init__(self, cgroup_name: str):
        self.name = cgroup_name
        self.path = CGROUP_ROOT / cgroup_name
        self.prev_cpu_usage = None
        self.prev_time = None
        self.prev_io_read = None
        self.prev_io_write = None

    def exists(self) -> bool:
        return self.path.exists()

    def read_cpu_stat(self) -> Dict:
        """cpu.stat 읽기 - CPU 사용량 (마이크로초)"""
        stat_file = self.path / "cpu.stat"
        result = {
            'usage_usec': 0,
            'user_usec': 0,
            'system_usec': 0,
            'cpu_percent': 0.0,
        }

        if not stat_file.exists():
            return result

        try:
            content = stat_file.read_text()
            for line in content.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 2:
                    key, value = parts[0], int(parts[1])
                    if key == 'usage_usec':
                        result['usage_usec'] = value
                    elif key == 'user_usec':
                        result['user_usec'] = value
                    elif key == 'system_usec':
                        result['system_usec'] = value

            # CPU 사용률 계산 (델타 기반)
            current_time = time.time()
            if self.prev_cpu_usage is not None and self.prev_time is not None:
                dt = current_time - self.prev_time
                if dt > 0:
                    delta_usage = result['usage_usec'] - self.prev_cpu_usage
                    # 마이크로초 -> 초, 그리고 백분율로 변환
                    # 100% = 1 코어 풀 사용
                    result['cpu_percent'] = (delta_usage / 1_000_000) / dt * 100

            self.prev_cpu_usage = result['usage_usec']
            self.prev_time = current_time

        except Exception as e:
            pass

        return result

    def read_memory(self) -> Dict:
        """메모리 사용량 읽기"""
        result = {
            'memory_bytes': 0,
            'memory_mb': 0.0,
            'memory_max_bytes': 0,
        }

        # 현재 메모리 사용량
        current_file = self.path / "memory.current"
        if current_file.exists():
            try:
                result['memory_bytes'] = int(current_file.read_text().strip())
                result['memory_mb'] = result['memory_bytes'] / 1024 / 1024
            except:
                pass

        # 최대 제한
        max_file = self.path / "memory.max"
        if max_file.exists():
            try:
                val = max_file.read_text().strip()
                if val != 'max':
                    result['memory_max_bytes'] = int(val)
            except:
                pass

        return result

    def read_io_stat(self) -> Dict:
        """io.stat 읽기 - 디스크 IO"""
        result = {
            'io_read_bytes': 0,
            'io_write_bytes': 0,
            'io_read_kbs': 0.0,
            'io_write_kbs': 0.0,
        }

        stat_file = self.path / "io.stat"
        if not stat_file.exists():
            return result

        try:
            content = stat_file.read_text()
            total_read = 0
            total_write = 0

            for line in content.strip().split('\n'):
                if not line:
                    continue
                # 형식: major:minor rbytes=X wbytes=Y rios=Z wios=W
                parts = line.split()
                for part in parts:
                    if part.startswith('rbytes='):
                        total_read += int(part.split('=')[1])
                    elif part.startswith('wbytes='):
                        total_write += int(part.split('=')[1])

            result['io_read_bytes'] = total_read
            result['io_write_bytes'] = total_write

            # IO 속도 계산 (델타 기반)
            current_time = time.time()
            if self.prev_io_read is not None and self.prev_io_write is not None:
                dt = current_time - (self.prev_time or current_time)
                if dt > 0:
                    result['io_read_kbs'] = (total_read - self.prev_io_read) / 1024 / dt
                    result['io_write_kbs'] = (total_write - self.prev_io_write) / 1024 / dt

            self.prev_io_read = total_read
            self.prev_io_write = total_write

        except Exception as e:
            pass

        return result

    def read_procs(self) -> int:
        """cgroup 내 프로세스 수"""
        procs_file = self.path / "cgroup.procs"
        if not procs_file.exists():
            return 0

        try:
            content = procs_file.read_text().strip()
            if not content:
                return 0
            return len(content.split('\n'))
        except:
            return 0

    def read_all(self) -> Dict:
        """모든 통계 읽기"""
        cpu = self.read_cpu_stat()
        mem = self.read_memory()
        io = self.read_io_stat()
        procs = self.read_procs()

        return {
            'cgroup': self.name,
            'cpu_percent': cpu['cpu_percent'],
            'cpu_usage_usec': cpu['usage_usec'],
            'memory_mb': mem['memory_mb'],
            'memory_bytes': mem['memory_bytes'],
            'io_read_kbs': io['io_read_kbs'],
            'io_write_kbs': io['io_write_kbs'],
            'io_read_bytes': io['io_read_bytes'],
            'io_write_bytes': io['io_write_bytes'],
            'num_procs': procs,
        }


class SystemIOReader:
    """시스템 전체 IO 읽기 (vmstat 대체)"""

    def __init__(self):
        self.prev_stats = None
        self.prev_time = None

    def read(self) -> Dict:
        """시스템 전체 디스크 IO"""
        result = {
            'sys_io_read_kbs': 0.0,
            'sys_io_write_kbs': 0.0,
        }

        try:
            current_time = time.time()
            read_bytes = 0
            write_bytes = 0

            with open('/proc/diskstats', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 14:
                        device = parts[2]
                        # 주요 디스크만 (sda, nvme0n1 등)
                        if (device.startswith('sd') and device[-1].isalpha()) or \
                           (device.startswith('nvme') and 'p' not in device):
                            read_bytes += int(parts[5]) * 512
                            write_bytes += int(parts[9]) * 512

            if self.prev_stats is not None and self.prev_time is not None:
                dt = current_time - self.prev_time
                if dt > 0:
                    prev_read, prev_write = self.prev_stats
                    result['sys_io_read_kbs'] = (read_bytes - prev_read) / 1024 / dt
                    result['sys_io_write_kbs'] = (write_bytes - prev_write) / 1024 / dt

            self.prev_stats = (read_bytes, write_bytes)
            self.prev_time = current_time

        except Exception as e:
            pass

        return result


def signal_handler(sig, frame):
    print("\n[INFO] Logging stopped by user")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description='cgroup v2 Resource Logger')
    parser.add_argument('-c', '--cgroups', nargs='+',
                        default=['yolo.slice', 'nodejs.slice'],
                        help='cgroup 이름 목록')
    parser.add_argument('-o', '--output', type=str, default=None,
                        help='출력 CSV 파일 경로')
    parser.add_argument('-d', '--duration', type=int, default=0,
                        help='측정 시간 (초, 0=무제한)')
    parser.add_argument('-i', '--interval', type=float, default=1.0,
                        help='샘플링 간격 (초)')
    parser.add_argument('--include-system-io', action='store_true',
                        help='시스템 전체 IO도 측정')
    args = parser.parse_args()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # cgroup 리더 초기화
    readers = []
    for cg_name in args.cgroups:
        reader = CgroupReader(cg_name)
        if reader.exists():
            readers.append(reader)
            print(f"[INFO] Monitoring cgroup: {cg_name}")
        else:
            print(f"[WARN] cgroup not found: {cg_name}")

    if not readers:
        print("[ERROR] No valid cgroups to monitor")
        sys.exit(1)

    sys_io = SystemIOReader() if args.include_system_io else None

    # 첫 번째 읽기 (델타 계산용)
    for reader in readers:
        reader.read_all()
    if sys_io:
        sys_io.read()
    time.sleep(0.1)

    # CSV 헤더
    header = "timestamp,cgroup,cpu_percent,memory_mb,io_read_kbs,io_write_kbs,num_procs"
    if args.include_system_io:
        header += ",sys_io_read_kbs,sys_io_write_kbs"

    outfile = None
    if args.output:
        outfile = open(args.output, 'w')
        outfile.write(header + '\n')
        outfile.flush()
        print(f"[INFO] Logging to: {args.output}")

    print(f"[INFO] Interval: {args.interval}s, Duration: {'unlimited' if args.duration == 0 else f'{args.duration}s'}")
    print(f"[INFO] Starting... (Ctrl+C to stop)")
    print(header)

    start_time = time.time()
    line_count = 0

    try:
        while True:
            # Duration 체크
            if args.duration > 0:
                elapsed = time.time() - start_time
                if elapsed >= args.duration:
                    print(f"\n[INFO] Duration {args.duration}s reached")
                    break

            timestamp = datetime.now().isoformat(timespec='milliseconds')

            # 시스템 IO 읽기
            sys_io_data = sys_io.read() if sys_io else {}

            # 각 cgroup 읽기
            for reader in readers:
                stats = reader.read_all()

                csv_line = (
                    f"{timestamp},{stats['cgroup']},"
                    f"{stats['cpu_percent']:.1f},{stats['memory_mb']:.1f},"
                    f"{stats['io_read_kbs']:.1f},{stats['io_write_kbs']:.1f},"
                    f"{stats['num_procs']}"
                )

                if args.include_system_io:
                    csv_line += f",{sys_io_data.get('sys_io_read_kbs', 0):.1f}"
                    csv_line += f",{sys_io_data.get('sys_io_write_kbs', 0):.1f}"

                print(csv_line)

                if outfile:
                    outfile.write(csv_line + '\n')
                    outfile.flush()

                line_count += 1

            time.sleep(args.interval)

    finally:
        if outfile:
            outfile.close()
            print(f"\n[INFO] Saved {line_count} records to {args.output}")


if __name__ == '__main__':
    main()
