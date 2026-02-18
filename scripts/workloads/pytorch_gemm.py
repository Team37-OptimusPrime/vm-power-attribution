#!/usr/bin/env python3
"""PyTorch Large GEMM — 대규모 행렬곱 반복 (GPU 집약적 연산)

4096×4096 행렬 2개를 torch.mm()로 반복 곱셈하여 GPU를 집중 활용한다.
CUDA synchronize로 GPU 파이프라인 완료를 대기하여 정확한 GPU 부하를 유지한다.

Usage:
    python pytorch_gemm.py --duration 90
"""

import argparse
import time

import torch


def main():
    parser = argparse.ArgumentParser(description="PyTorch Large GEMM workload")
    parser.add_argument("--duration", type=int, default=90,
                        help="Duration in seconds (default: 90)")
    parser.add_argument("--size", type=int, default=4096,
                        help="Matrix size NxN (default: 4096)")
    args = parser.parse_args()

    if not torch.cuda.is_available():
        print("ERROR: CUDA is not available")
        return

    device = torch.device("cuda:0")
    N = args.size
    print(f"[GEMM] Starting: {N}x{N} matrix multiplication on {device}")
    print(f"[GEMM] Duration: {args.duration}s")

    # 행렬 미리 할당 (GPU 메모리)
    A = torch.randn(N, N, device=device, dtype=torch.float32)
    B = torch.randn(N, N, device=device, dtype=torch.float32)

    # Warm-up (GPU 초기화 지연 제거)
    for _ in range(3):
        _ = torch.mm(A, B)
    torch.cuda.synchronize()

    count = 0
    end_time = time.time() + args.duration
    while time.time() < end_time:
        C = torch.mm(A, B)
        torch.cuda.synchronize()
        count += 1

    print(f"[GEMM] Done: {count} multiplications in {args.duration}s "
          f"({count / args.duration:.1f} ops/s)")


if __name__ == "__main__":
    main()
