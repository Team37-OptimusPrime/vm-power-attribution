#!/usr/bin/env python3
"""ResNet18 Inference — ImageNet 분류 모델 배치 추론 반복

torchvision.models.resnet18(pretrained)을 로드하고,
랜덤 이미지 배치(batch=32, 3×224×224)로 추론을 반복한다.

Usage:
    python resnet18_inference.py --duration 90
"""

import argparse
import time

import torch
import torchvision.models as models


def main():
    parser = argparse.ArgumentParser(description="ResNet18 inference workload")
    parser.add_argument("--duration", type=int, default=90,
                        help="Duration in seconds (default: 90)")
    parser.add_argument("--batch-size", type=int, default=32,
                        help="Batch size (default: 32)")
    args = parser.parse_args()

    if not torch.cuda.is_available():
        print("ERROR: CUDA is not available")
        return

    device = torch.device("cuda:0")
    print(f"[ResNet18] Loading model on {device}")

    # 모델 로드 (사전 다운로드된 가중치 사용)
    model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
    model = model.to(device)
    model.eval()

    batch_size = args.batch_size
    print(f"[ResNet18] Starting: batch_size={batch_size}, duration={args.duration}s")

    # 입력 텐서 미리 할당
    dummy_input = torch.randn(batch_size, 3, 224, 224, device=device)

    # Warm-up
    with torch.no_grad():
        for _ in range(5):
            _ = model(dummy_input)
    torch.cuda.synchronize()

    count = 0
    end_time = time.time() + args.duration
    with torch.no_grad():
        while time.time() < end_time:
            _ = model(dummy_input)
            torch.cuda.synchronize()
            count += 1

    total_images = count * batch_size
    print(f"[ResNet18] Done: {count} batches ({total_images} images) in {args.duration}s "
          f"({total_images / args.duration:.1f} img/s)")


if __name__ == "__main__":
    main()
