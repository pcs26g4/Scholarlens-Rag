import pytest

from llm_verdict import pricing
from llm_verdict.verdict_llm import LLMUsage


@pytest.fixture(autouse=True)
def fake_pricing_table(monkeypatch):
    # Avoid hitting the real OpenRouter /models endpoint in tests.
    monkeypatch.setattr(
        pricing,
        "get_model_pricing",
        lambda model_id, provider: {"prompt": 0.000002, "completion": 0.00001},
    )


def test_compute_cost_without_thinking_tokens():
    usage = LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150, source="provider")
    cost = pricing.compute_cost(usage, "some-model", "openrouter")
    assert cost.priced is True
    assert cost.prompt_cost_usd == pytest.approx(100 * 0.000002)
    assert cost.completion_cost_usd == pytest.approx(50 * 0.00001)
    assert cost.total_cost_usd == pytest.approx(100 * 0.000002 + 50 * 0.00001)


def test_compute_cost_bills_thinking_tokens_at_completion_rate():
    # Gemini "thinking" models report reasoning tokens separately
    # (thoughtsTokenCount) from visible output (candidatesTokenCount), but
    # Google bills both at the completion rate -- this must not be silently
    # dropped, or cost is understated (observed live: ~4.8x undercount).
    usage = LLMUsage(
        prompt_tokens=1347, completion_tokens=297, total_tokens=2782,
        source="provider", thinking_tokens=1138,
    )
    cost = pricing.compute_cost(usage, "gemini-2.5-pro", "gemini")
    billed_completion_tokens = 297 + 1138
    assert cost.completion_cost_usd == pytest.approx(billed_completion_tokens * 0.00001)
    assert cost.total_cost_usd == pytest.approx(1347 * 0.000002 + billed_completion_tokens * 0.00001)


def test_compute_cost_unpriced_when_pricing_missing(monkeypatch):
    monkeypatch.setattr(pricing, "get_model_pricing", lambda model_id, provider: None)
    usage = LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15, source="provider")
    cost = pricing.compute_cost(usage, "unknown-model", "openrouter")
    assert cost.priced is False
    assert cost.total_cost_usd is None
    assert cost.pricing_source == "unpriced"
