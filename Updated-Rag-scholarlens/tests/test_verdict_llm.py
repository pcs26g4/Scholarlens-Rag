import time
from unittest.mock import Mock

import pytest
import requests

from llm_verdict import verdict_llm


def _http_error(status_code):
    resp = Mock()
    resp.status_code = status_code
    return requests.exceptions.HTTPError(response=resp)


def test_request_with_retry_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(verdict_llm.time, "sleep", lambda s: None)  # skip real waiting

    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(429)
        return {"ok": True}

    result = verdict_llm._request_with_retry(_flaky)
    assert result == {"ok": True}
    assert calls["n"] == 3  # failed twice, succeeded on the third try


def test_request_with_retry_does_not_retry_non_retryable_status(monkeypatch):
    monkeypatch.setattr(verdict_llm.time, "sleep", lambda s: None)

    calls = {"n": 0}

    def _bad_request():
        calls["n"] += 1
        raise _http_error(401)  # auth error -- retrying can't help

    with pytest.raises(requests.exceptions.HTTPError):
        verdict_llm._request_with_retry(_bad_request)
    assert calls["n"] == 1  # never retried


def test_request_with_retry_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(verdict_llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(verdict_llm, "RETRY_MAX_RETRIES", 2)

    calls = {"n": 0}

    def _always_rate_limited():
        calls["n"] += 1
        raise _http_error(429)

    with pytest.raises(requests.exceptions.HTTPError):
        verdict_llm._request_with_retry(_always_rate_limited)
    assert calls["n"] == 3  # initial attempt + 2 retries


def test_request_with_retry_retries_on_malformed_json_body(monkeypatch):
    # Observed in practice: OpenRouter occasionally returns a 200-level
    # response with an unparseable body (no HTTPError raised at all, since
    # the status was fine) -- there's no status code to gate on here, so
    # this must always be retried rather than falling straight through.
    monkeypatch.setattr(verdict_llm.time, "sleep", lambda s: None)

    calls = {"n": 0}

    def _garbled_then_fine():
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.exceptions.JSONDecodeError("Expecting value", "", 0)
        return {"ok": True}

    result = verdict_llm._request_with_retry(_garbled_then_fine)
    assert result == {"ok": True}
    assert calls["n"] == 2


def test_request_with_retry_gives_up_on_json_error_after_max_retries(monkeypatch):
    monkeypatch.setattr(verdict_llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(verdict_llm, "RETRY_MAX_RETRIES", 2)

    calls = {"n": 0}

    def _always_garbled():
        calls["n"] += 1
        raise requests.exceptions.JSONDecodeError("Expecting value", "", 0)

    with pytest.raises(requests.exceptions.JSONDecodeError):
        verdict_llm._request_with_retry(_always_garbled)
    assert calls["n"] == 3  # initial attempt + 2 retries


def test_call_llm_raises_on_hard_timeout(monkeypatch):
    # Simulate a provider that hangs -- e.g. OpenRouter trickling keep-alive
    # bytes while the model is still generating, which defeats requests' own
    # per-read timeout (see LLM_CALL_TIMEOUT_SECONDS docstring).
    def _slow_provider(prompt, *, model, api_key, base_url, temperature=None):
        time.sleep(2)
        return verdict_llm.LLMCallResult(
            text="too late",
            usage=verdict_llm.LLMUsage(1, 1, 2, "provider"),
            provider="openrouter",
            model=model,
        )

    monkeypatch.setattr(verdict_llm, "_PROVIDERS", {"openrouter": _slow_provider})
    monkeypatch.setattr(verdict_llm, "LLM_CALL_TIMEOUT_SECONDS", 0.2)

    start = time.perf_counter()
    with pytest.raises(verdict_llm.LLMTimeoutError) as exc_info:
        verdict_llm.call_llm("prompt", provider="openrouter", model="test-model", api_key="key")
    elapsed = time.perf_counter() - start

    # Must fail fast off the 0.2s deadline, not wait for the 2s slow call.
    assert elapsed < 1.0
    assert exc_info.value.provider == "openrouter"
    assert exc_info.value.model == "test-model"
    assert exc_info.value.timeout_seconds == 0.2


def test_call_llm_succeeds_within_timeout(monkeypatch):
    def _fast_provider(prompt, *, model, api_key, base_url, temperature=None):
        return verdict_llm.LLMCallResult(
            text="ok",
            usage=verdict_llm.LLMUsage(1, 1, 2, "provider"),
            provider="openrouter",
            model=model,
        )

    monkeypatch.setattr(verdict_llm, "_PROVIDERS", {"openrouter": _fast_provider})
    monkeypatch.setattr(verdict_llm, "LLM_CALL_TIMEOUT_SECONDS", 5)

    result = verdict_llm.call_llm("prompt", provider="openrouter", model="test-model", api_key="key")
    assert result.text == "ok"
    assert result.duration_seconds >= 0
