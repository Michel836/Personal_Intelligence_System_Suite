"""OpenAI-compatible provider tests with mocked HTTP (M012-A). No real keys."""
from __future__ import annotations

import pytest
import requests

from src.ai.providers.base import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from src.ai.providers.openai_compatible import (
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleLLMProvider,
    redact,
)
from tests.ai_fakes import FakeResponse, FakeSession

KEY = "sk-secret-value-123"


def _llm(session, **kw):
    return OpenAICompatibleLLMProvider(model="gpt-test", base_url="https://api.example/v1",
                                       api_key=KEY, session=session, **kw)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("src.ai.providers.openai_compatible.time.sleep", lambda *_: None)


def test_chat_success_headers_usage():
    session = FakeSession([FakeResponse(200, {
        "choices": [{"message": {"content": "bonjour"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    })])
    result = _llm(session).chat([{"role": "user", "content": "hi"}])
    assert result.text == "bonjour"
    assert result.usage == {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
    assert result.finish_reason == "stop"
    call = session.calls[0]
    assert call["url"] == "https://api.example/v1/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"


def test_auth_error_normalized_and_key_not_leaked():
    session = FakeSession([FakeResponse(401, text="unauthorized")])
    with pytest.raises(ProviderAuthError) as exc:
        _llm(session).chat([{"role": "user", "content": "hi"}])
    assert KEY not in str(exc.value)


def test_rate_limit_retries_then_succeeds():
    session = FakeSession([
        FakeResponse(429, headers={"Retry-After": "0"}),
        FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
    ])
    result = _llm(session, max_retries=2).chat([{"role": "user", "content": "hi"}])
    assert result.text == "ok"
    assert len(session.calls) == 2


def test_rate_limit_exhausted_raises():
    session = FakeSession([FakeResponse(429), FakeResponse(429)])
    with pytest.raises(ProviderRateLimitError):
        _llm(session, max_retries=1).chat([{"role": "user", "content": "hi"}])


def test_server_error_retries_bounded():
    session = FakeSession([FakeResponse(503)] * 3)
    with pytest.raises(ProviderResponseError):
        _llm(session, max_retries=2).chat([{"role": "user", "content": "hi"}])
    assert len(session.calls) == 3  # initial + 2 retries


def test_client_error_not_retried():
    session = FakeSession([FakeResponse(400, text="bad request")])
    with pytest.raises(ProviderResponseError):
        _llm(session, max_retries=3).chat([{"role": "user", "content": "hi"}])
    assert len(session.calls) == 1


def test_timeout_normalized():
    class TimeoutSession:
        def post(self, *a, **k):
            raise requests.Timeout("timed out")

    with pytest.raises(ProviderTimeoutError):
        _llm(TimeoutSession(), max_retries=1).chat([{"role": "user", "content": "hi"}])


def test_connection_error_normalized():
    class DownSession:
        def post(self, *a, **k):
            raise requests.ConnectionError("connection refused")

    with pytest.raises(ProviderUnavailableError):
        _llm(DownSession(), max_retries=0).chat([{"role": "user", "content": "hi"}])


def test_malformed_response_normalized():
    session = FakeSession([FakeResponse(200, {"unexpected": True})])
    with pytest.raises(ProviderResponseError):
        _llm(session).chat([{"role": "user", "content": "hi"}])


def test_stream_chat_parses_sse():
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "data: [DONE]",
    ]
    session = FakeSession([FakeResponse(200, lines=lines)])
    chunks = list(_llm(session).stream_chat([{"role": "user", "content": "hi"}]))
    assert chunks == ["Hel", "lo"]


def test_embeddings_sorted_by_index_and_dim():
    session = FakeSession([FakeResponse(200, {
        "data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}],
        "usage": {"prompt_tokens": 4, "total_tokens": 4},
    })])
    provider = OpenAICompatibleEmbeddingProvider(model="emb", base_url="https://api.example/v1",
                                                 api_key=KEY, session=session)
    result = provider.embed_batch(["a", "b"])
    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert result.dim == 2
    assert result.usage["prompt_tokens"] == 4
    assert provider.dimension() == 2


def test_unavailable_without_key_or_url():
    assert not OpenAICompatibleLLMProvider(model="m", base_url="", api_key=KEY).is_available()
    assert not OpenAICompatibleLLMProvider(model="m", base_url="https://x", api_key=None).is_available()


def test_redact_removes_key():
    assert KEY not in redact(f"failed calling {KEY}", KEY)


def test_key_not_leaked_in_error_body():
    session = FakeSession([FakeResponse(400, text=f"bad request api_key={KEY}")])
    with pytest.raises(ProviderResponseError) as exc:
        _llm(session).chat([{"role": "user", "content": "hi"}])
    assert KEY not in str(exc.value)


def test_zero_retries_makes_single_call():
    session = FakeSession([FakeResponse(503)])
    with pytest.raises(ProviderResponseError):
        _llm(session, max_retries=0).chat([{"role": "user", "content": "hi"}])
    assert len(session.calls) == 1
