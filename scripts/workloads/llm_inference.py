#!/usr/bin/env python3
"""Modern LLM Inference — 오픈웨이트 LLM 배치 생성 반복 (W10)

GPT-2(2019, 124M) 대비 현대적 소형 LLM의 에너지 프로파일 확보용.
기본 모델: Qwen/Qwen2.5-3B-Instruct (FP16 ~6GB, RTX 3060 12GB 적합,
HF 게이팅 없음). --model로 교체 가능.

최초 실행 시 모델(~6GB)을 다운로드하므로, 실험 전에 미리 1회 실행해
캐시를 데워둘 것:
    python3 llm_inference.py --duration 30

Usage:
    python3 llm_inference.py --duration 90
    python3 llm_inference.py --duration 90 --model Qwen/Qwen2.5-3B-Instruct
"""

import argparse
import time


def main():
    parser = argparse.ArgumentParser(description="Modern LLM inference workload")
    parser.add_argument("--duration", type=int, default=90,
                        help="Duration in seconds (default: 90)")
    parser.add_argument("--model", default="Qwen/Qwen2.5-3B-Instruct",
                        help="HF model id (default: Qwen/Qwen2.5-3B-Instruct)")
    parser.add_argument("--max-new-tokens", type=int, default=128,
                        help="Tokens generated per iteration (default: 128)")
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not torch.cuda.is_available():
        print("ERROR: CUDA is not available")
        return

    device = torch.device("cuda:0")
    print(f"[LLM] Loading {args.model} on {device} (fp16)")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.float16).to(device)
    model.eval()

    prompts = [
        "Explain the difference between processes and threads in operating systems.",
        "Summarize the key ideas behind energy-aware scheduling in data centers.",
        "Write a short story about a robot learning to paint.",
        "What are the trade-offs between virtualization and containerization?",
    ]
    inputs = [tokenizer(p, return_tensors="pt").to(device) for p in prompts]

    # Warm-up
    with torch.no_grad():
        model.generate(**inputs[0], max_new_tokens=8,
                       do_sample=False, pad_token_id=tokenizer.eos_token_id)
    torch.cuda.synchronize()
    print(f"[LLM] Starting: max_new_tokens={args.max_new_tokens}, "
          f"duration={args.duration}s")

    count, tokens = 0, 0
    end_time = time.time() + args.duration
    with torch.no_grad():
        while time.time() < end_time:
            enc = inputs[count % len(inputs)]
            out = model.generate(**enc, max_new_tokens=args.max_new_tokens,
                                 do_sample=False,
                                 pad_token_id=tokenizer.eos_token_id)
            torch.cuda.synchronize()
            tokens += out.shape[1] - enc["input_ids"].shape[1]
            count += 1

    print(f"[LLM] Done: {count} generations, {tokens} new tokens in "
          f"{args.duration}s ({tokens / args.duration:.1f} tok/s)")


if __name__ == "__main__":
    main()
