"""Usage accounting for AI providers (M012-A).

Counts requests, tokens and latency. Never assumes monetary pricing; an optional
operator-configured price table may be supplied to estimate cost. Exposed for
diagnostics only.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class UsageBucket:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_s: float = 0.0

    def add(self, *, prompt: int = 0, completion: int = 0, latency: float = 0.0) -> None:
        self.requests += 1
        self.prompt_tokens += max(0, int(prompt or 0))
        self.completion_tokens += max(0, int(completion or 0))
        self.total_tokens = self.prompt_tokens + self.completion_tokens
        self.latency_s += max(0.0, float(latency or 0.0))


class UsageTracker:
    """Thread-safe per-(provider, model, kind) usage accumulator."""

    def __init__(self, price_table: Optional[dict[str, tuple[float, float]]] = None):
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str, str], UsageBucket] = {}
        # Optional {(provider, model): (usd_per_1k_input, usd_per_1k_output)}
        self._prices = price_table or {}

    def record(self, provider: str, model: str, kind: str, *, usage: Optional[dict] = None,
               latency: float = 0.0) -> None:
        usage = usage or {}
        with self._lock:
            bucket = self._buckets.setdefault((provider, model, kind), UsageBucket())
            bucket.add(
                prompt=usage.get("prompt_tokens", 0),
                completion=usage.get("completion_tokens", 0),
                latency=latency,
            )

    def snapshot(self) -> dict:
        with self._lock:
            items = {f"{p}:{m}:{k}": {
                "provider": p, "model": m, "kind": k,
                "requests": b.requests, "prompt_tokens": b.prompt_tokens,
                "completion_tokens": b.completion_tokens, "total_tokens": b.total_tokens,
                "latency_s": round(b.latency_s, 4),
                "estimated_cost_usd": self._estimate(p, m, b),
            } for (p, m, k), b in self._buckets.items()}
            totals = {
                "requests": sum(b.requests for b in self._buckets.values()),
                "prompt_tokens": sum(b.prompt_tokens for b in self._buckets.values()),
                "completion_tokens": sum(b.completion_tokens for b in self._buckets.values()),
                "total_tokens": sum(b.total_tokens for b in self._buckets.values()),
            }
        return {"buckets": items, "totals": totals}

    def _estimate(self, provider: str, model: str, bucket: UsageBucket) -> Optional[float]:
        price = self._prices.get((provider, model))
        if not price:
            return None
        in_price, out_price = price
        return round(bucket.prompt_tokens / 1000 * in_price + bucket.completion_tokens / 1000 * out_price, 6)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
