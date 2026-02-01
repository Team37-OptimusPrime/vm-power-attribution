#!/usr/bin/env python3
"""
Host System Power/Metrics Logger
Alienware에서 실행하여 RAPL, GPU, CPU 메트릭을 CSV로 저장

Usage:
    python3 host_logger.py                     # 기본 출력 파일
    python3 host_logger.py -o mylog.csv        # 지정 파일
    python3 host_logger.py -d 60               # 60초 동안 기록
    python3 host_logger.py -i 0.5              # 0.5초 간격
"""

import subprocess
import sys
import signal
import argparse
import time
import os
from datetime import datetime
from pathlib import Path


class RAPLReader:
    """Intel RAPL 에너지 카운터 읽기"""

    RAPL_BASE = "/sys/class/powercap/intel-rapl"

    def __init__(self):
        self.domains = self._discover_domains()
        self.prev_energy = {}
        self.prev_time = None

    def _discover_domains(self) -> dict:
        """사용 가능한 RAPL 도메인 탐색"""
        domains = {}
        base = Path(self.RAPL_BASE)

        if not base.exists():
            print("[WARN] RAPL not available")
            return domains

        for pkg_dir in base.glob("intel-rapl:*"):
            pkg_name = (pkg_dir / "name").read_text().strip()
            energy_file = pkg_dir / "energy_uj"
            if energy_file.exists():
                domains[pkg_name] = energy_file

            # 서브도메인 (core, uncore, dram)
            for sub_dir in pkg_dir.glob("intel-rapl:*:*"):
                sub_name = (sub_dir / "name").read_text().strip()
                sub_energy = sub_dir / "energy_uj"
                if sub_energy.exists():
                    domains[f"{pkg_name}-{sub_name}"] = sub_energy

        return domains

    def read_power(self) -> dict:
        """현재 전력(W) 계산"""
        current_time = time.time()
        current_energy = {}
        power = {}

        for name, path in self.domains.items():
            try:
                energy_uj = int(path.read_text().strip())
                current_energy[name] = energy_uj
            except (PermissionError, FileNotFoundError):
                continue

        if self.prev_time is not None:
            dt = current_time - self.prev_time
            if dt > 0:
                for name, energy in current_energy.items():
                    if name in self.prev_energy:
                        delta = energy - self.prev_energy[name]
                        # 오버플로우 처리
                        if delta < 0:
                            delta += 2**32
                        power[name] = (delta / 1_000_000) / dt  # uJ -> W

        self.prev_energy = current_energy
        self.prev_time = current_time

        return power


class NvidiaReader:
    """nvidia-smi를 통한 GPU 메트릭 읽기"""

    def read(self) -> dict:
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=power.draw,temperature.gpu,utilization.gpu,utilization.memory,memory.used',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(', ')
                return {
                    'gpu_power_w': float(parts[0]),
                    'gpu_temp_c': int(parts[1]),
                    'gpu_util_pct': int(parts[2]),
                    'gpu_mem_util_pct': int(parts[3]),
                    'gpu_mem_used_mb': int(parts[4]),
                }
        except Exception as e:
            pass
        return {
            'gpu_power_w': 0,
            'gpu_temp_c': 0,
            'gpu_util_pct': 0,
            'gpu_mem_util_pct': 0,
            'gpu_mem_used_mb': 0,
        }


class CPUReader:
    """CPU 사용률 읽기"""

    def __init__(self):
        self.prev_stat = None

    def read(self) -> float:
        try:
            with open('/proc/stat', 'r') as f:
                line = f.readline()
            parts = line.split()[1:]  # 'cpu' 제외
            values = [int(x) for x in parts]

            # user, nice, system, idle, iowait, irq, softirq, steal
            idle = values[3] + values[4]  # idle + iowait
            total = sum(values)

            if self.prev_stat is not None:
                prev_idle, prev_total = self.prev_stat
                diff_idle = idle - prev_idle
                diff_total = total - prev_total
                if diff_total > 0:
                    cpu_pct = 100.0 * (1.0 - diff_idle / diff_total)
                else:
                    cpu_pct = 0.0
            else:
                cpu_pct = 0.0

            self.prev_stat = (idle, total)
            return cpu_pct
        except:
            return 0.0


def signal_handler(sig, frame):
    print("\n[INFO] Logging stopped by user")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description='Host System Power Logger')
    parser.add_argument('-o', '--output', type=str,
                        default=f"host_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        help='Output CSV file path')
    parser.add_argument('-d', '--duration', type=int, default=0,
                        help='Recording duration in seconds (0 = unlimited)')
    parser.add_argument('-i', '--interval', type=float, default=1.0,
                        help='Sampling interval in seconds')
    parser.add_argument('--no-file', action='store_true',
                        help='Print to stdout only, no file')
    args = parser.parse_args()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 리더 초기화
    rapl = RAPLReader()
    nvidia = NvidiaReader()
    cpu = CPUReader()

    # 첫 번째 읽기 (델타 계산용)
    rapl.read_power()
    cpu.read()
    time.sleep(0.1)

    # CSV 헤더
    header = "timestamp,cpu_pct,rapl_package_w,rapl_core_w,rapl_dram_w,gpu_power_w,gpu_temp_c,gpu_util_pct"

    outfile = None
    if not args.no_file:
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

            # 메트릭 수집
            cpu_pct = cpu.read()
            rapl_power = rapl.read_power()
            gpu = nvidia.read()

            # RAPL 값 추출 (없으면 0)
            pkg_w = rapl_power.get('package-0', 0)
            core_w = rapl_power.get('package-0-core', 0)
            dram_w = rapl_power.get('package-0-dram', 0)

            csv_line = (
                f"{timestamp},{cpu_pct:.1f},"
                f"{pkg_w:.2f},{core_w:.2f},{dram_w:.2f},"
                f"{gpu['gpu_power_w']:.2f},{gpu['gpu_temp_c']},{gpu['gpu_util_pct']}"
            )

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
