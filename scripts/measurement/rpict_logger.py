#!/usr/bin/env python3
"""
RPICT4V3 Data Logger
Raspberry Pi에서 실행하여 RPICT 데이터를 타임스탬프와 함께 CSV로 저장

Usage:
    python3 rpict_logger.py                    # 기본 출력 파일
    python3 rpict_logger.py -o mylog.csv       # 지정 파일
    python3 rpict_logger.py -d 60              # 60초 동안 기록
    python3 rpict_logger.py --no-file          # 화면 출력만
"""

import subprocess
import sys
import signal
import argparse
from datetime import datetime
from pathlib import Path


def signal_handler(sig, frame):
    print("\n[INFO] Logging stopped by user")
    sys.exit(0)


def parse_rpict_line(line: str) -> dict | None:
    """RPICT 출력 라인을 파싱하여 딕셔너리로 반환"""
    parts = line.strip().split()

    # 첫 줄이 baud rate인 경우 스킵
    if len(parts) == 1 and parts[0].isdigit():
        return None

    # 최소 필드 수 확인 (NodeID + 최소 데이터)
    if len(parts) < 5:
        return None

    try:
        # RPICT4V3 V6 기본 포맷 (예상):
        # NodeID Power1 Power2 Power3 I1 I2 I3 I4 Vrms PF1 PF2
        data = {
            'node_id': int(parts[0]),
            'power1_w': abs(float(parts[1])),  # 절대값 사용 (CT 방향 무관)
            'power2_w': abs(float(parts[2])),
            'power3_w': abs(float(parts[3])),
            'current1_a': float(parts[4]),
            'current2_a': float(parts[5]) if len(parts) > 5 else 0,
            'current3_a': float(parts[6]) if len(parts) > 6 else 0,
            'current4_a': float(parts[7]) if len(parts) > 7 else 0,
            'voltage_v': float(parts[8]) if len(parts) > 8 else 0,
            'pf1': float(parts[9]) if len(parts) > 9 else 0,
            'pf2': float(parts[10]) if len(parts) > 10 else 0,
        }
        return data
    except (ValueError, IndexError) as e:
        return None


def main():
    parser = argparse.ArgumentParser(description='RPICT4V3 Data Logger')
    parser.add_argument('-o', '--output', type=str,
                        default=f"rpict_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        help='Output CSV file path')
    parser.add_argument('-d', '--duration', type=int, default=0,
                        help='Recording duration in seconds (0 = unlimited)')
    parser.add_argument('--no-file', action='store_true',
                        help='Print to stdout only, no file')
    args = parser.parse_args()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # CSV 헤더
    header = "timestamp,node_id,power1_w,power2_w,power3_w,current1_a,current2_a,current3_a,current4_a,voltage_v,pf1,pf2"

    outfile = None
    if not args.no_file:
        outfile = open(args.output, 'w')
        outfile.write(header + '\n')
        outfile.flush()
        print(f"[INFO] Logging to: {args.output}")

    print(f"[INFO] Starting RPICT logger... (Ctrl+C to stop)")
    print(header)

    start_time = datetime.now()
    line_count = 0

    try:
        # lcl-run 실행 (전체 경로 사용)
        proc = subprocess.Popen(
            ['/usr/local/bin/lcl-run'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        for line in proc.stdout:
            # Duration 체크
            if args.duration > 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= args.duration:
                    print(f"\n[INFO] Duration {args.duration}s reached")
                    break

            data = parse_rpict_line(line)
            if data is None:
                continue

            timestamp = datetime.now().isoformat(timespec='milliseconds')

            csv_line = (
                f"{timestamp},{data['node_id']},"
                f"{data['power1_w']:.2f},{data['power2_w']:.2f},{data['power3_w']:.2f},"
                f"{data['current1_a']:.3f},{data['current2_a']:.3f},"
                f"{data['current3_a']:.3f},{data['current4_a']:.3f},"
                f"{data['voltage_v']:.2f},{data['pf1']:.2f},{data['pf2']:.2f}"
            )

            print(csv_line)

            if outfile:
                outfile.write(csv_line + '\n')
                outfile.flush()

            line_count += 1

        proc.terminate()

    except FileNotFoundError:
        print("[ERROR] lcl-run not found. Is lcl-rpict-package installed?")
        sys.exit(1)
    finally:
        if outfile:
            outfile.close()
            print(f"\n[INFO] Saved {line_count} records to {args.output}")


if __name__ == '__main__':
    main()
