#!/usr/bin/env python3
"""GPT-2 Inference — 텍스트 생성 반복 (tokenization + inference)

transformers 라이브러리의 GPT2LMHeadModel을 사용하여
프롬프트 텍스트로 generate()를 반복 호출한다.

사전 다운로드 필요:
    python -c "from transformers import GPT2LMHeadModel, GPT2Tokenizer; \
               GPT2LMHeadModel.from_pretrained('gpt2'); \
               GPT2Tokenizer.from_pretrained('gpt2')"

Usage:
    python gpt2_inference.py --duration 90
"""

import argparse
import time

import torch
from transformers import GPT2LMHeadModel, GPT2Tokenizer


def main():
    parser = argparse.ArgumentParser(description="GPT-2 inference workload")
    parser.add_argument("--duration", type=int, default=90,
                        help="Duration in seconds (default: 90)")
    parser.add_argument("--max-length", type=int, default=200,
                        help="Max tokens to generate per call (default: 200)")
    args = parser.parse_args()

    if not torch.cuda.is_available():
        print("ERROR: CUDA is not available")
        return

    device = torch.device("cuda:0")
    print(f"[GPT-2] Loading model on {device}")

    # 모델 & 토크나이저 로드 (사전 다운로드된 캐시 사용)
    tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
    model = GPT2LMHeadModel.from_pretrained("gpt2")
    model = model.to(device)
    model.eval()

    # pad_token 설정 (GPT-2는 기본적으로 pad_token이 없음)
    tokenizer.pad_token = tokenizer.eos_token

    # 다양한 프롬프트 (반복 시 순환)
    prompts = [
        "The future of artificial intelligence is",
        "In a world where technology advances rapidly,",
        "Deep learning has revolutionized the field of",
        "The relationship between energy consumption and computing",
        "Cloud computing and virtualization enable",
    ]

    print(f"[GPT-2] Starting: max_length={args.max_length}, duration={args.duration}s")

    # Warm-up
    with torch.no_grad():
        inputs = tokenizer(prompts[0], return_tensors="pt").to(device)
        _ = model.generate(
            **inputs,
            max_length=args.max_length,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    torch.cuda.synchronize()

    count = 0
    total_tokens = 0
    end_time = time.time() + args.duration
    with torch.no_grad():
        while time.time() < end_time:
            prompt = prompts[count % len(prompts)]
            inputs = tokenizer(prompt, return_tensors="pt").to(device)
            output = model.generate(
                **inputs,
                max_length=args.max_length,
                do_sample=True,
                pad_token_id=tokenizer.eos_token_id,
            )
            torch.cuda.synchronize()
            total_tokens += output.shape[1]
            count += 1

    print(f"[GPT-2] Done: {count} generations ({total_tokens} tokens) in {args.duration}s "
          f"({total_tokens / args.duration:.1f} tok/s)")


if __name__ == "__main__":
    main()
