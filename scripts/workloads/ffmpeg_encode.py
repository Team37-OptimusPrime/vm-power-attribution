#!/usr/bin/env python3
"""ffmpeg x264 Video Encoding — CPU 집약적 비디오 인코딩 반복

lavfi 테스트 패턴(1920x1080, 30fps)을 x264로 인코딩하여 CPU를 집중 활용한다.
출력을 /dev/null로 보내 디스크 I/O를 최소화한다.

J Kim et al. 논문 워크로드 참조 (CPU-dominant, ~35% CPU util, ~99W wall)

Usage:
    python ffmpeg_encode.py --duration 90
    python ffmpeg_encode.py --duration 90 --preset fast --resolution 1280x720
"""

import argparse
import subprocess
import sys
import time


def check_ffmpeg():
    """ffmpeg 설치 여부 확인"""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except FileNotFoundError:
        print("ERROR: ffmpeg가 설치되어 있지 않습니다.")
        print("  설치: sudo apt install ffmpeg")
        sys.exit(1)


def encode_once(segment_duration: int, resolution: str, preset: str) -> bool:
    """단일 인코딩 세그먼트 실행. 성공 시 True 반환."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"testsrc2=size={resolution}:rate=30",
        "-vcodec", "libx264",
        "-preset", preset,
        "-crf", "23",
        "-t", str(segment_duration),
        "-an",          # 오디오 트랙 없음
        "-f", "null",   # 컨테이너 없이 인코딩만
        "/dev/null",
    ]
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=segment_duration + 15,
            check=False,
        )
        return True
    except subprocess.TimeoutExpired:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="ffmpeg x264 CPU encoding workload (CPU-dominant)"
    )
    parser.add_argument(
        "--duration", type=int, default=90,
        help="총 실행 시간(초), 기본값: 90"
    )
    parser.add_argument(
        "--preset", default="medium",
        choices=["ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow"],
        help="x264 인코딩 preset (느릴수록 CPU 부하 증가, 기본값: medium)"
    )
    parser.add_argument(
        "--resolution", default="1920x1080",
        help="입력 해상도 (기본값: 1920x1080)"
    )
    parser.add_argument(
        "--segment", type=int, default=20,
        help="각 인코딩 세그먼트 길이(초), 기본값: 20"
    )
    args = parser.parse_args()

    check_ffmpeg()

    end_time = time.time() + args.duration - 3  # 3초 여유
    iteration = 0

    print(
        f"[ffmpeg] 시작: resolution={args.resolution}, "
        f"preset={args.preset}, total={args.duration}s",
        flush=True,
    )

    while time.time() < end_time:
        iteration += 1
        remaining = int(end_time - time.time())
        segment_duration = min(args.segment, remaining)
        if segment_duration <= 0:
            break

        ok = encode_once(segment_duration, args.resolution, args.preset)
        status = "OK" if ok else "TIMEOUT"
        print(
            f"[ffmpeg] iter={iteration} duration={segment_duration}s [{status}]",
            flush=True,
        )

    print(f"[ffmpeg] 종료: 총 {iteration}회 반복", flush=True)


if __name__ == "__main__":
    main()
