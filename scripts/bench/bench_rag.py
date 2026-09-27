# ruff: noqa
"""RAG/Ollama utilization benchmark using the deployed ./api/chat contract.

Measures cold/warm load, TTFT, tokens/sec, GPU utilisation and VRAM for the
locked models, without touchimg the app's conversation state.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bench.common import json_print, load_conditions  # noqa: E402

OLLAMA = "http://localhost:11434"
FILLER = (
    "Le contrat de service prevoit une clause de confidentialite, un delai de "
    "paiement de trente jours et une clause de resiliation anticipee. "
)


class GpuSampler:
    def __init__(self, interval: float = 0.3):
        self.samples = []
        self._stop = threading.Event()
        self._thread = None
        self.interval = interval

    def _loop(self):
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5, check=False).stdout.strip()
                if out:
                    p = [x.strip() for x in out.splitlines()[0].split(",")]
                    self.samples.append((int(p[0]), int(p[1])))
            except Exception:
                pass
            self._stop.wait(self.interval)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def stop_model(model: str) -> None:
    subprocess.run(["ollama", "stop", model], capture_output=True, text=True, check=False)
    time.sleep(1.0)


def warm_prompt(num_ctx: int) -> str:
    # ~1 token per 4 chars; leave room for the answer.
    target_chars = int(num_ctx * 3.0)
    body = (FILLER * (target_chars // len(FILLER) + 1))[:target_chars]
    return f"Contexte:\n{body}\n\nQuestion: quel est le delai de paiement ? Reponds en une phrase."


def run_once(model: str, prompt: str, num_ctx: int, num_predict: int) -> dict:
    gpu = GpuSampler()
    gpu.start()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "think": False,
        "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": 0.2},
    }
    t0 = time.perf_counter()
    ttft = None
    chars = 0
    data = {}
    try:
        with requests.post(f"{OLLAMA}/api/chat", json=payload, stream=True, timeout=600) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if ttft is None and chunk.get("message", {}).get("content"):
                    ttft = time.perf_counter() - t0
                chars += len(chunk.get("message", {}).get("content", ""))
                if chunk.get("done"):
                    data = chunk
    except Exception as exc:
        gpu.stop()
        return {"model": model, "num_ctx": num_ctx, "error": str(exc)[:200]}
    total = time.perf_counter() - t0
    gpu.stop()
    eval_count = data.get("eval_count", 0)
    eval_ns = data.get("eval_duration", 0)
    util = [s[0] for s in gpu.samples]
    vram = [s[1] for s in gpu.samples]
    return {
        "model": model,
        "num_ctx": num_ctx,
        "ttft_s": round(ttft, 3) if ttft is not None else None,
        "total_s": round(total, 3),
        "load_s": round(data.get("load_duration", 0) / 1e9, 3),
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "prompt_eval_s": round(data.get("prompt_eval_duration", 0) / 1e9, 3),
        "gen_tokens": eval_count,
        "tok_per_s": round(eval_count / (eval_ns / 1e9), 2) if eval_ns else 0,
        "gpu_util_avg": round(sum(util) / len(util), 1) if util else 0,
        "vram_peak_mb": max(vram) if vram else 0,
        "chars": chars,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="ornith:9b,qwen3.8:27b-q4_K_M")
    ap.add_argument("--ctx", default="4096")
    ap.add_argument("--num-predict", type=int, default=96)
    ap.add_argument("--cold", action="store_true")
    args = ap.parse_args()
    report = {"conditions": load_conditions(), "runs": []}
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        for ctx in [int(c) for c in args.ctx.split(",") if c.strip()]:
            if args.cold:
                stop_model(model)
                report["runs"].append({"phase": "cold", **run_once(model, warm_prompt(ctx), ctx, args.num_predict)})
            report["runs"].append({"phase": "warm", **run_once(model, warm_prompt(ctx), ctx, args.num_predict)})
    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
