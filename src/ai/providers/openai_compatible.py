"""Generic OpenAI-compatible remote providers (chat + embeddings).

One implementation serves any OpenAI-compatible endpoint (hosted APIs, LM Studio,
vLLM, llama.cpp server, ...). No vendor-specific behaviour is assumed beyond the
documented protocol. HTTP is performed with ``requests`` and is fully mockable in
tests; a real API key is never required by the test suite.
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator, Optional, Sequence

import requests

from .base import (
    AIProviderError,
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMResult,
    ModelInfo,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_DEFAULT_TIMEOUT = 60.0
_DEFAULT_RETRIES = 3
_MAX_BACKOFF = 8.0


def redact(text: str, api_key: Optional[str]) -> str:
    """Remove an API key from a string before it can be logged."""
    if not api_key:
        return text
    return text.replace(api_key, "***")


class _OpenAICompatibleBase:
    remote = True

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_RETRIES,
        session: Optional[requests.Session] = None,
    ):
        self.model = model
        self.base_url = (base_url or "").rstrip("/")
        self._api_key = api_key
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self._session = session or requests.Session()

    # -- helpers -----------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _backoff(self, attempt: int) -> None:
        time.sleep(min(_MAX_BACKOFF, 0.25 * (2 ** attempt)))

    def _post(self, path: str, payload: dict[str, Any], *, stream: bool = False):
        """POST with bounded exponential backoff; normalises all failures.

        Never includes the API key in any error message.
        """
        if not self.base_url:
            raise ProviderUnavailableError("API base URL is not configured")
        url = self._url(path)
        last: AIProviderError = ProviderUnavailableError("no attempt made")
        for attempt in range(self.max_retries + 1):
            try:
                response = self._session.post(
                    url, headers=self._headers(), json=payload, timeout=self.timeout, stream=stream
                )
            except requests.Timeout as exc:
                last = ProviderTimeoutError(redact(str(exc), self._api_key))
            except requests.ConnectionError as exc:
                last = ProviderUnavailableError(redact(str(exc), self._api_key))
            except requests.RequestException as exc:
                last = ProviderResponseError(redact(str(exc), self._api_key))
            else:
                if response.status_code in (401, 403):
                    raise ProviderAuthError(f"HTTP {response.status_code}: authentication failed")
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    last = ProviderRateLimitError("HTTP 429: rate limited")
                    if attempt < self.max_retries:
                        try:
                            time.sleep(min(_MAX_BACKOFF, float(retry_after)))
                        except (TypeError, ValueError):
                            self._backoff(attempt)
                        continue
                    raise last
                if response.status_code >= 500:
                    last = ProviderResponseError(f"HTTP {response.status_code}: upstream error")
                elif response.status_code >= 400:
                    raise ProviderResponseError(
                        f"HTTP {response.status_code}: {redact(response.text[:200], self._api_key)}"
                    )
                else:
                    return response
            if attempt < self.max_retries:
                self._backoff(attempt)
        raise last


class OpenAICompatibleLLMProvider(_OpenAICompatibleBase, LLMProvider):
    name = "openai_compatible"
    backend = "openai_compatible"

    def is_available(self) -> bool:
        return bool(self.base_url and self.model and self._api_key)

    def model_info(self) -> ModelInfo:
        return ModelInfo(provider=self.name, model=self.model, remote=True)

    @staticmethod
    def _usage(data: dict[str, Any]) -> dict[str, int]:
        usage = data.get("usage") or {}
        out = {}
        for src, dst in (("prompt_tokens", "prompt_tokens"),
                         ("completion_tokens", "completion_tokens"),
                         ("total_tokens", "total_tokens")):
            if isinstance(usage.get(src), int):
                out[dst] = usage[src]
        return out

    def chat(self, messages: Sequence[dict[str, str]], *, options: Optional[dict[str, Any]] = None) -> LLMResult:
        payload: dict[str, Any] = {"model": self.model, "messages": list(messages)}
        for key in ("temperature", "top_p", "max_tokens", "num_predict"):
            if options and key in options:
                target = "max_tokens" if key == "num_predict" else key
                payload[target] = options[key]
        response = self._post("/chat/completions", payload)
        try:
            data = response.json()
            choice = data["choices"][0]
            text = (choice.get("message") or {}).get("content") or ""
            return LLMResult(text=text, provider=self.name, model=self.model,
                             usage=self._usage(data), finish_reason=choice.get("finish_reason"),
                             raw=data)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProviderResponseError(f"malformed chat response: {type(exc).__name__}") from exc

    def stream_chat(self, messages: Sequence[dict[str, str]], *, options: Optional[dict[str, Any]] = None) -> Iterator[str]:
        payload: dict[str, Any] = {"model": self.model, "messages": list(messages), "stream": True}
        if options:
            for key in ("temperature", "top_p"):
                if key in options:
                    payload[key] = options[key]
        response = self._post("/chat/completions", payload, stream=True)
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if chunk == "[DONE]":
                    break
                try:
                    data = json.loads(chunk)
                    delta = (data["choices"][0].get("delta") or {}).get("content")
                except (KeyError, IndexError, ValueError):
                    continue
                if delta:
                    yield delta
        finally:
            response.close()


class OpenAICompatibleEmbeddingProvider(_OpenAICompatibleBase, EmbeddingProvider):
    name = "openai_compatible_embeddings"
    backend = "openai_compatible"

    def __init__(self, *, model: str, base_url: str, api_key: Optional[str] = None,
                 dim: Optional[int] = None, timeout: float = _DEFAULT_TIMEOUT,
                 max_retries: int = _DEFAULT_RETRIES, session: Optional[requests.Session] = None):
        super().__init__(model=model, base_url=base_url, api_key=api_key, timeout=timeout,
                         max_retries=max_retries, session=session)
        self._dim = int(dim) if dim else 0

    def is_available(self) -> bool:
        return bool(self.base_url and self.model and self._api_key)

    def dimension(self) -> int:
        if self._dim:
            return self._dim
        if not self.is_available():
            return 0
        try:
            result = self.embed_batch(["dimension probe"])
            self._dim = result.dim
        except AIProviderError:
            return 0
        return self._dim

    def model_info(self) -> ModelInfo:
        return ModelInfo(provider=self.name, model=self.model, remote=True,
                         dimension=self._dim or None)

    def embed_batch(self, texts: Sequence[str], *, batch_size: Optional[int] = None) -> EmbeddingResult:
        chunk = max(1, int(batch_size)) if batch_size else len(texts) or 1
        vectors: list[list[float]] = []
        prompt_tokens = 0
        for i in range(0, len(texts), chunk):
            batch = list(texts[i:i + chunk])
            response = self._post("/embeddings", {"model": self.model, "input": batch})
            try:
                data = response.json()
                items = sorted(data["data"], key=lambda d: d.get("index", 0))
                vectors.extend([list(map(float, item["embedding"])) for item in items])
                usage = data.get("usage") or {}
                if isinstance(usage.get("prompt_tokens"), int):
                    prompt_tokens += usage["prompt_tokens"]
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                raise ProviderResponseError(f"malformed embeddings response: {type(exc).__name__}") from exc
        dim = len(vectors[0]) if vectors else 0
        if self._dim and dim and self._dim != dim:
            raise ProviderResponseError(f"embedding dimension changed: {self._dim} -> {dim}")
        if dim:
            self._dim = dim
        return EmbeddingResult(vectors=vectors, provider=self.name, model=self.model, dim=dim,
                               usage={"prompt_tokens": prompt_tokens} if prompt_tokens else {})
