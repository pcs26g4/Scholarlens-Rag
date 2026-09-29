"""
Local, approximate prompt-token counting.

CAVEAT: this module uses `tiktoken`, which tokenizes the way OpenAI's GPT models do. It does
NOT exactly match the tokenizer used by every model reachable via OpenRouter (Gemini, Qwen,
Llama, ...) or Gemini's native API -- there is no single tokenizer library covering all of
them. Every count here is an ESTIMATE for relative comparison / rough budgeting only. Wherever
a provider response includes real usage/usageMetadata (see LLMUsage in verdict_llm.py), that
exact figure should be preferred for anything requiring precision.
"""
from dataclasses import dataclass
from typing import Dict

import tiktoken

_FALLBACK_ENCODING = "cl100k_base"
_encoding_cache = {}


def _resolve_encoding(model_name: str):
    bare_name = (model_name or "").split("/")[-1]  # "openai/gpt-4.1" -> "gpt-4.1"
    if bare_name in _encoding_cache:
        return _encoding_cache[bare_name]
    try:
        encoding = tiktoken.encoding_for_model(bare_name)
    except KeyError:
        encoding = tiktoken.get_encoding(_FALLBACK_ENCODING)
    _encoding_cache[bare_name] = encoding
    return encoding


def count_tokens(text: str, model_name: str) -> int:
    if not text:
        return 0
    return len(_resolve_encoding(model_name).encode(text))


@dataclass
class PromptTokenBreakdown:
    sections: Dict[str, int]
    prompt_total_approx: int
    model_name: str
    encoding_used: str


def count_prompt_sections(sections: Dict[str, str], model_name: str) -> PromptTokenBreakdown:
    counts = {name: count_tokens(text, model_name) for name, text in sections.items()}
    return PromptTokenBreakdown(
        sections=counts,
        prompt_total_approx=sum(counts.values()),
        model_name=model_name,
        encoding_used=_resolve_encoding(model_name).name,
    )
