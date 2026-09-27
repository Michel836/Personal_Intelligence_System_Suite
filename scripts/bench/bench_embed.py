# ruff: noqa
"""Embedding GPU pipeline benchmark: batch-size sweep and GPU utilisation.

Runs each (model, batch_size) with a background nvidia-smi sampler so GPU
starvation / idle gaps are visible. Models are loaded once each and freed.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bench.common import ResourceSampler, json_print, load_conditions  # noqa: E402

WORDS = ("contrat service confidentialite paiement facture credit pret hypotheque "
         "notaire avocat tribunal accord clause document rapport analyse projet "
         "budget client fournisseur livraison logiciel systeme donnees reseau").split()


def make_texts(n: int, words_per_text: int = 80) -> list[str]:
    rng = random.Random(7)
    return [" ".join(rng.choice(WORDS) for _ in range(words_per_text)) for _ in range(n)]


class GpuSampler:
    def __init__(self, interval: float = 0.25):
        self.interval = interval
        self.samples: list[tuple[float, int]] = []
        self._stop = threading.Event()
        self._thread = None

    def _loop(self):
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5, check=False).stdout.strip()
                if out:
                    parts = [p.strip() for p in out.splitlines()[0].split(",")]
                    self.samples.append((time.perf_counter(), int(parts[0]), int(parts[1])))
            except Exception:
                pass
            self._stop.wait(self.interval)

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def benchmark_model(model_key: str, batch_sizes: list[int], n_texts: int) -> dict:
    import torch
    from src.intelligence.embeddings import EmbeddingGenerator

    os.environ["PIS_EMBEDDING_MODEL"] = model_key
    t0 = time.perf_counter()
    gen = EmbeddingGenerator(model_name=model_key)
    load_s = time.perf_counter() - t0
    if not gen.is_available():
        return {"model": model_key, "available": False, "load_s": round(load_s, 2)}
    dim = gen.embedding_dim
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    texts = make_texts(n_texts)
    results = []
    gpu = GpuSampler()
    for bs in batch_sizes:
        gen.model.encode(texts[: min(bs, len(texts))])  # warmup
        gpu.start()
        with ResourceSampler() as s:
            emb = gen.generate_batch_embeddings(texts, batch_size=bs, show_progress=False)
        gpu.stop()
        valid = sum(1 for e in emb if e is not None)
        gpu_utils = [x[1] for x in gpu.samples]
        vram = [x[2] for x in gpu.samples]
        results.append({
            "batch_size": bs,
            "texts": len(texts),
            "valid": valid,
            "wall_s": round(s.sample.wall, 3),
            "embeddings_per_sec": round(valid / s.sample.wall, 1) if s.sample.wall else 0,
            "cpu_pct": round(s.sample.cpu_pct, 1),
            "rss_mb": round(s.sample.rss_mb, 1),
            "gpu_util_avg": round(sum(gpu_utils) / len(gpu_utils), 1) if gpu_utils else 0,
            "gpu_util_min": min(gpu_utils) if gpu_utils else 0,
            "gpu_samples": len(gpu_utils),
            "vram_peak_mb": max(vram) if vram else 0,
        })
        gpu.samples = []
    peak = round(torch.cuda.max_memory_allocated() / 1e6, 1) if torch.cuda.is_available() else 0
    out = {"model": model_key, "available": True, "dim": dim, "load_s": round(load_s, 2),
           "torch_peak_mb": peak, "results": results}
    del gen
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="all-MiniLM-L6-v2")
    ap.add_argument("--batches", default="8,16,32,64,128,256")
    ap.add_argument("--texts", type=int, default=512)
    args = ap.parse_args()
    report = {"conditions": load_conditions(), "models": []}
    for m in [x.strip() for x in args.models.split(",") if x.strip()]:
        report["models"].append(
            benchmark_model(m, [int(b) for b in args.batches.split(",")], args.texts)
        )
    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
