"""
Live per-model $ pricing, fetched from OpenRouter's public /models endpoint and
cached in-process. Works automatically for any model reachable through
OpenRouter -- no per-model table to maintain here.

Known gap: if a provider is switched to native Gemini (not via OpenRouter),
the model id format won't always match OpenRouter's own listing convention
(e.g. native "gemini-2.5-pro" vs. OpenRouter's "google/gemini-2.5-pro"). A
best-effort "google/{model}" fallback lookup is attempted in that case; if
still not found, cost comes back unpriced rather than wrong.
"""
import time
from dataclasses import dataclass
from typing import Dict, Optional

import requests

from llm_verdict.verdict_llm import LLMUsage

_MODELS_URL = "https://openrouter.ai/api/v1/models"
_CACHE_TTL_SECONDS = 3600

_cache: Dict[str, Dict[str, float]] = {}
_cache_fetched_at: Optional[float] = None


def _fetch_pricing_table() -> Dict[str, Dict[str, float]]:
    resp = requests.get(_MODELS_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    table = {}
    for m in data.get("data", []):
        pricing = m.get("pricing") or {}
        try:
            table[m["id"]] = {
                "prompt": float(pricing.get("prompt", 0) or 0),
                "completion": float(pricing.get("completion", 0) or 0),
            }
        except (TypeError, ValueError):
            continue
    return table


def _get_pricing_table() -> Dict[str, Dict[str, float]]:
    global _cache, _cache_fetched_at
    now = time.time()
    if _cache_fetched_at is None or (now - _cache_fetched_at) > _CACHE_TTL_SECONDS:
        _cache = _fetch_pricing_table()
        _cache_fetched_at = now
    return _cache


def get_model_pricing(model_id: str, provider: str) -> Optional[Dict[str, float]]:
    """Return {"prompt": $/token, "completion": $/token} for model_id, or None if unpriced."""
    table = _get_pricing_table()
    if model_id in table:
        return table[model_id]
    if provider == "gemini":
        fallback_id = f"google/{model_id}"
        if fallback_id in table:
            return table[fallback_id]
    return None


@dataclass
class CostBreakdown:
    prompt_cost_usd: Optional[float]
    completion_cost_usd: Optional[float]
    total_cost_usd: Optional[float]
    priced: bool
    pricing_source: str  # "openrouter_live" | "unpriced"


def compute_cost(usage: LLMUsage, model_id: str, provider: str) -> CostBreakdown:
    pricing = get_model_pricing(model_id, provider)
    if pricing is None or usage.prompt_tokens is None or usage.completion_tokens is None:
        return CostBreakdown(
            prompt_cost_usd=None,
            completion_cost_usd=None,
            total_cost_usd=None,
            priced=False,
            pricing_source="unpriced",
        )
    # Gemini "thinking" models bill internal reasoning tokens at the same
    # rate as visible completion tokens (confirmed: "response pricing is the
    # sum of output tokens and thinking tokens" -- Google's own docs), but
    # report them in a separate field (thoughtsTokenCount) from
    # candidatesTokenCount. Bill both; usage.completion_tokens stays
    # visible-output-only elsewhere so it still reflects what the response
    # actually said.
    billed_completion_tokens = usage.completion_tokens + (usage.thinking_tokens or 0)
    prompt_cost = usage.prompt_tokens * pricing["prompt"]
    completion_cost = billed_completion_tokens * pricing["completion"]
    return CostBreakdown(
        prompt_cost_usd=prompt_cost,
        completion_cost_usd=completion_cost,
        total_cost_usd=prompt_cost + completion_cost,
        priced=True,
        pricing_source="openrouter_live",
    )
