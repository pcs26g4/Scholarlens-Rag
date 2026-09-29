import concurrent.futures
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv
import requests

load_dotenv()

logger = logging.getLogger(__name__)

LLM_CALL_TIMEOUT_SECONDS = float(os.getenv("LLM_CALL_TIMEOUT_SECONDS", 150))

RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_MAX_RETRIES = 5
RETRY_BASE_DELAY_SECONDS = 1.0
RETRY_MAX_DELAY_SECONDS = 30.0


def _request_with_retry(make_request):
    """Run `make_request()` (a zero-arg callable performing one HTTP attempt,
    raising requests.exceptions.HTTPError via resp.raise_for_status() on a
    non-2xx response), retrying on transient failures.

    Retries on:
      - 429 (rate limit -- hit repeatedly during heavy testing) and 5xx
        (server-side) status codes. Anything else (auth errors, bad
        requests) is never retried, since retrying those can't succeed.
      - requests.exceptions.JSONDecodeError -- observed in practice: a
        request can come back with an apparently-successful status but a
        malformed/truncated body (no HTTPError raised at all, since the
        status was fine). There's no status code to gate on here; any
        unparseable body on an otherwise-successful request is inherently
        worth one more try.

    Uses exponential backoff with full jitter (a random delay between 0 and
    the computed cap, not the cap itself) so that many requests failing at
    once don't all retry in lockstep and hit the server again simultaneously.
    """
    for attempt in range(RETRY_MAX_RETRIES + 1):
        try:
            return make_request()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            retryable = status in RETRY_STATUS_CODES
            error = e
        except requests.exceptions.JSONDecodeError as e:
            status = "invalid-json"
            retryable = True
            error = e

        if not retryable or attempt == RETRY_MAX_RETRIES:
            raise error

        delay = min(RETRY_MAX_DELAY_SECONDS, RETRY_BASE_DELAY_SECONDS * (2 ** attempt))
        sleep = random.uniform(0, delay)
        logger.warning(
            "Retry %d/%d (status=%s) in %.2fs", attempt + 1, RETRY_MAX_RETRIES, status, sleep,
        )
        time.sleep(sleep)


class LLMTimeoutError(Exception):
    """An LLM call exceeded LLM_CALL_TIMEOUT_SECONDS of real wall-clock time.

    requests' own `timeout=` only resets each time a byte arrives from the
    server -- if a provider trickles keep-alive data while the model is still
    generating, a call can run far longer than that without ever raising on
    its own (observed in practice: a call ran 6+ minutes past a 120s
    requests-level timeout with no error). This wraps every call in an
    independent wall-clock deadline that fires regardless of what the
    network layer is doing underneath.
    """

    def __init__(self, provider, model, timeout_seconds):
        self.provider = provider
        self.model = model
        self.timeout_seconds = timeout_seconds
        super().__init__(f"{provider}/{model} did not respond within {timeout_seconds:.0f}s")


@dataclass
class LLMUsage:
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    source: str  # "provider" if the API reported usage, else "unavailable"
    thinking_tokens: Optional[int] = None  # Gemini "thinking" models only -- see compute_cost()


@dataclass
class LLMCallResult:
    text: str
    usage: LLMUsage
    provider: str
    model: str
    duration_seconds: float = 0.0


def _post_openrouter(prompt, *, model, api_key, base_url, temperature=None):
    base_url = base_url or "https://openrouter.ai/api/v1"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt}
        ]
    }
    if temperature is not None:
        payload["temperature"] = temperature

    def _attempt():
        resp = requests.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        return resp.json()

    data = _request_with_retry(_attempt)
    usage_raw = data.get("usage") or {}
    usage = LLMUsage(
        prompt_tokens=usage_raw.get("prompt_tokens"),
        completion_tokens=usage_raw.get("completion_tokens"),
        total_tokens=usage_raw.get("total_tokens"),
        source="provider" if usage_raw else "unavailable",
    )
    return LLMCallResult(
        text=data["choices"][0]["message"]["content"],
        usage=usage,
        provider="openrouter",
        model=model,
    )


def _post_gemini(prompt, *, model, api_key, base_url=None, temperature=None):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": api_key,
    }
    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }
    if temperature is not None:
        payload["generationConfig"] = {"temperature": temperature}

    def _attempt():
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()

    data = _request_with_retry(_attempt)
    usage_raw = data.get("usageMetadata") or {}
    usage = LLMUsage(
        prompt_tokens=usage_raw.get("promptTokenCount"),
        completion_tokens=usage_raw.get("candidatesTokenCount"),
        total_tokens=usage_raw.get("totalTokenCount"),
        source="provider" if usage_raw else "unavailable",
        # "Thinking" models (e.g. gemini-2.5-pro) generate internal reasoning
        # tokens billed at the completion rate but reported separately from
        # candidatesTokenCount (which is visible-output only) -- see
        # compute_cost() in pricing.py for where this actually gets billed.
        thinking_tokens=usage_raw.get("thoughtsTokenCount"),
    )
    return LLMCallResult(
        text=data["candidates"][0]["content"]["parts"][0]["text"],
        usage=usage,
        provider="gemini",
        model=model,
    )


_PROVIDERS = {
    "openrouter": _post_openrouter,
    "gemini": _post_gemini,
}


def call_llm(prompt: str, *, provider: str, model: str, api_key: str, base_url: str = None, temperature: float = None) -> LLMCallResult:
    try:
        fn = _PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"Unknown LLM provider: {provider}")

    start = time.perf_counter()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn, prompt, model=model, api_key=api_key, base_url=base_url, temperature=temperature)
    try:
        result = future.result(timeout=LLM_CALL_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        # wait=False: don't block here waiting for the still-running background
        # call. Python can't forcibly kill a thread, so it may keep running
        # until the socket itself gives up, but the caller isn't stuck on it.
        executor.shutdown(wait=False)
        raise LLMTimeoutError(provider, model, LLM_CALL_TIMEOUT_SECONDS) from None
    executor.shutdown(wait=False)
    result.duration_seconds = time.perf_counter() - start
    return result


def _resolve_verdict_config():
    provider = os.getenv("LLM_PROVIDER", "openrouter")
    model = os.getenv("LLM_MODEL", "openai/gpt-3.5-turbo-1106")
    base_url = os.getenv("LLM_PROVIDER_BASE_URL", "https://openrouter.ai/api/v1")
    api_key = os.getenv("OPENROUTER_API_KEY") if provider == "openrouter" else os.getenv("GEMINI_API_KEY")
    temperature = float(os.getenv("LLM_TEMPERATURE", 0))
    return provider, model, base_url, api_key, temperature


def _resolve_eval_config():
    provider = os.getenv("EVAL_LLM_PROVIDER") or os.getenv("LLM_PROVIDER", "openrouter")
    model = os.getenv("EVAL_LLM_MODEL") or os.getenv("LLM_MODEL", "openai/gpt-3.5-turbo-1106")
    base_url = os.getenv("EVAL_LLM_PROVIDER_BASE_URL") or os.getenv("LLM_PROVIDER_BASE_URL", "https://openrouter.ai/api/v1")
    if provider == "openrouter":
        api_key = os.getenv("EVAL_OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    else:
        api_key = os.getenv("EVAL_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    temperature = float(os.getenv("EVAL_LLM_TEMPERATURE") or os.getenv("LLM_TEMPERATURE", 0))
    return provider, model, base_url, api_key, temperature


def generate_verdict_response(prompt: str) -> LLMCallResult:
    provider, model, base_url, api_key, temperature = _resolve_verdict_config()
    return call_llm(prompt, provider=provider, model=model, base_url=base_url, api_key=api_key, temperature=temperature)


def generate_eval_response(prompt: str) -> LLMCallResult:
    provider, model, base_url, api_key, temperature = _resolve_eval_config()
    return call_llm(prompt, provider=provider, model=model, base_url=base_url, api_key=api_key, temperature=temperature)


def _resolve_summary_config():
    # Deliberately does NOT fall back to LLM_PROVIDER/LLM_MODEL like
    # _resolve_eval_config() does -- this is a distinct "summarization
    # model" role, defaulting to GPT-4o via OpenRouter regardless of
    # whichever verdict/eval model is currently configured.
    provider = os.getenv("SUMMARY_LLM_PROVIDER", "openrouter")
    model = os.getenv("SUMMARY_LLM_MODEL", "openai/gpt-4o")
    base_url = os.getenv("SUMMARY_LLM_PROVIDER_BASE_URL", "https://openrouter.ai/api/v1")
    if provider == "openrouter":
        api_key = os.getenv("SUMMARY_OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    else:
        api_key = os.getenv("SUMMARY_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    temperature = float(os.getenv("SUMMARY_LLM_TEMPERATURE", 0))
    return provider, model, base_url, api_key, temperature


def generate_summary_response(prompt: str) -> LLMCallResult:
    provider, model, base_url, api_key, temperature = _resolve_summary_config()
    return call_llm(prompt, provider=provider, model=model, base_url=base_url, api_key=api_key, temperature=temperature)


def get_llm_verdict(prompt: str) -> str:
    """Back-compat shim: returns just the text, no usage data.

    Prefer generate_verdict_response() for new code that needs token usage.
    """
    return generate_verdict_response(prompt).text
