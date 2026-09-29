import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from llm_verdict.prompt_compose import compose_prompt, INSTRUCTIONS_BOILERPLATE
from llm_verdict.verdict_parser import parse_verdict_sections, VerdictSections
from llm_verdict.eval_prompt_compose import compose_eval_prompt, EVAL_INSTRUCTIONS_BOILERPLATE
from llm_verdict.eval_parser import parse_eval_response
from llm_verdict.summary_prompt_compose import compose_summary_prompt, SUMMARY_INSTRUCTIONS_BOILERPLATE
from llm_verdict.token_accounting import count_prompt_sections, PromptTokenBreakdown
from llm_verdict.verdict_llm import (
    generate_verdict_response, generate_eval_response, generate_summary_response, LLMUsage,
)
from llm_verdict.pricing import compute_cost, CostBreakdown

logger = logging.getLogger(__name__)


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}m {secs}s"


@dataclass
class TokenAccountingPair:
    local_prompt_breakdown: PromptTokenBreakdown
    provider_usage: LLMUsage


@dataclass
class AttemptRecord:
    attempt_number: int
    verdict_text: str
    verdict_sections: VerdictSections
    verdict_token_accounting: TokenAccountingPair
    verdict_duration_seconds: float
    verdict_cost: CostBreakdown
    eval_score: float
    eval_critique: str
    eval_parse_ok: bool
    eval_token_accounting: TokenAccountingPair
    eval_duration_seconds: float
    eval_cost: CostBreakdown


@dataclass
class OrchestrationResult:
    final_verdict_text: str
    final_verdict_sections: VerdictSections
    max_marks: float
    meets_quality_threshold: bool
    best_score: float
    attempts: List[AttemptRecord]
    short_feedback: str
    summary_token_accounting: TokenAccountingPair
    summary_duration_seconds: float
    summary_cost: CostBreakdown
    total_duration_seconds: float
    total_duration_formatted: str
    total_cost_usd: Optional[float]
    cost_by_model: Optional[Dict[str, float]]
    total_token_usage: Optional[Dict[str, int]]
    tokens_by_model: Optional[Dict[str, Dict[str, int]]]


def _sum_cost(attempts: List[AttemptRecord], extra_costs=()) -> Optional[float]:
    """Sum cost across all calls, or None if any single call is unpriced --
    a partial sum presented as "the total" would understate it silently.
    `extra_costs` covers calls outside the per-attempt loop (the one-off
    summarization call)."""
    total = 0.0
    for a in attempts:
        for c in (a.verdict_cost, a.eval_cost):
            if not c.priced or c.total_cost_usd is None:
                return None
            total += c.total_cost_usd
    for c in extra_costs:
        if not c.priced or c.total_cost_usd is None:
            return None
        total += c.total_cost_usd
    return total


def _cost_by_model(attempts: List[AttemptRecord], extra=()) -> Optional[Dict[str, float]]:
    """Sum cost per model name across all calls (verdict + eval, all attempts,
    plus any `extra` (cost, accounting) pairs outside the loop), or None if
    any single call is unpriced -- same "don't silently understate" policy
    as _sum_cost(). Model names come from the token-accounting breakdown,
    which already records which model each call actually used."""
    by_model: Dict[str, float] = {}
    for cost, accounting in [
        pair
        for a in attempts
        for pair in ((a.verdict_cost, a.verdict_token_accounting), (a.eval_cost, a.eval_token_accounting))
    ] + list(extra):
        if not cost.priced or cost.total_cost_usd is None:
            return None
        model_name = accounting.local_prompt_breakdown.model_name
        by_model[model_name] = by_model.get(model_name, 0.0) + cost.total_cost_usd
    return by_model


def _empty_token_totals() -> Dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "thinking_tokens": 0, "total_tokens": 0}


def _add_usage(totals: Dict[str, int], usage: LLMUsage) -> None:
    totals["prompt_tokens"] += usage.prompt_tokens
    totals["completion_tokens"] += usage.completion_tokens
    totals["thinking_tokens"] += usage.thinking_tokens or 0
    totals["total_tokens"] += usage.total_tokens


def _sum_tokens(attempts: List[AttemptRecord], extra=()) -> Optional[Dict[str, int]]:
    """Sum prompt/completion/thinking/total tokens across every call (verdict
    + eval, all attempts, plus any `extra` TokenAccountingPair outside the
    loop), or None if any single call's usage wasn't reported by the
    provider -- same "don't silently understate" policy as _sum_cost().
    thinking_tokens is kept separate from completion_tokens, consistent
    with the per-call breakdown."""
    totals = _empty_token_totals()
    for accounting in [
        acc for a in attempts for acc in (a.verdict_token_accounting, a.eval_token_accounting)
    ] + list(extra):
        usage = accounting.provider_usage
        if usage.source != "provider" or usage.prompt_tokens is None or usage.completion_tokens is None or usage.total_tokens is None:
            return None
        _add_usage(totals, usage)
    return totals


def _tokens_by_model(attempts: List[AttemptRecord], extra=()) -> Optional[Dict[str, Dict[str, int]]]:
    """Same breakdown as _sum_tokens(), grouped per model name instead of a
    single grand total -- e.g. when the verdict and eval calls use different
    models, this shows each one's own token usage separately."""
    by_model: Dict[str, Dict[str, int]] = {}
    for accounting in [
        acc for a in attempts for acc in (a.verdict_token_accounting, a.eval_token_accounting)
    ] + list(extra):
        usage = accounting.provider_usage
        if usage.source != "provider" or usage.prompt_tokens is None or usage.completion_tokens is None or usage.total_tokens is None:
            return None
        model_name = accounting.local_prompt_breakdown.model_name
        totals = by_model.setdefault(model_name, _empty_token_totals())
        _add_usage(totals, usage)
    return by_model


def run_verdict_with_evaluation(
    question: str,
    student_answer: str,
    answer_textbook_list: List[str],
    rules_md: str,
    max_marks: float,
    *,
    eval_threshold: Optional[float] = None,
    max_attempts: Optional[int] = None,
) -> OrchestrationResult:
    eval_threshold = eval_threshold if eval_threshold is not None else float(os.getenv("EVAL_THRESHOLD", 0.90))
    max_attempts = max_attempts if max_attempts is not None else int(os.getenv("EVAL_MAX_ATTEMPTS", 3))

    attempts: List[AttemptRecord] = []
    best: Optional[AttemptRecord] = None
    feedback = None

    for attempt_number in range(1, max_attempts + 1):
        verdict_prompt = compose_prompt(question, answer_textbook_list, student_answer, rules_md, max_marks, retry_feedback=feedback)
        verdict_result = generate_verdict_response(verdict_prompt)
        sections = parse_verdict_sections(verdict_result.text)

        verdict_breakdown = count_prompt_sections(
            {
                "question": question,
                "textbook_answers": "\n".join(answer_textbook_list),
                "student_answer": student_answer,
                "rubric": rules_md,
                "instructions_boilerplate": INSTRUCTIONS_BOILERPLATE,
            },
            verdict_result.model,
        )
        verdict_cost = compute_cost(verdict_result.usage, verdict_result.model, verdict_result.provider)

        eval_prompt = compose_eval_prompt(question, student_answer, sections, rules_md, answer_textbook_list)
        eval_result = generate_eval_response(eval_prompt)
        eval_parsed = parse_eval_response(eval_result.text)

        eval_breakdown = count_prompt_sections(
            {
                "strengths_section": sections.strengths,
                "weakness_section": sections.weaknesses,
                "verdict_section": sections.verdict_text,
                "question_and_student_answer": f"Question: {question}\nStudent's Answer: {student_answer}",
                "rubric": rules_md,
                "baseline_answer": "\n".join(answer_textbook_list),
                "instructions_boilerplate": EVAL_INSTRUCTIONS_BOILERPLATE,
            },
            eval_result.model,
        )
        eval_cost = compute_cost(eval_result.usage, eval_result.model, eval_result.provider)

        record = AttemptRecord(
            attempt_number=attempt_number,
            verdict_text=verdict_result.text,
            verdict_sections=sections,
            verdict_token_accounting=TokenAccountingPair(verdict_breakdown, verdict_result.usage),
            verdict_duration_seconds=verdict_result.duration_seconds,
            verdict_cost=verdict_cost,
            eval_score=eval_parsed.score,
            eval_critique=eval_parsed.critique,
            eval_parse_ok=eval_parsed.parse_ok,
            eval_token_accounting=TokenAccountingPair(eval_breakdown, eval_result.usage),
            eval_duration_seconds=eval_result.duration_seconds,
            eval_cost=eval_cost,
        )
        attempts.append(record)

        logger.info(
            "attempt %d: verdict=%.2fs ($%s) eval=%.2fs ($%s) score=%.2f parse_ok=%s",
            attempt_number,
            record.verdict_duration_seconds,
            f"{verdict_cost.total_cost_usd:.4f}" if verdict_cost.priced else "unpriced",
            record.eval_duration_seconds,
            f"{eval_cost.total_cost_usd:.4f}" if eval_cost.priced else "unpriced",
            record.eval_score,
            eval_parsed.parse_ok,
        )

        if best is None or record.eval_score > best.eval_score:
            best = record

        if eval_parsed.score >= eval_threshold:
            final_record = record
            meets_threshold = True
            break

        feedback = eval_parsed.critique
    else:
        final_record = best
        meets_threshold = False

    logger.info(
        "verdict resolved after %d attempt(s), threshold_met=%s, score=%.2f",
        len(attempts), meets_threshold, final_record.eval_score,
    )

    # One-off summarization call on the resolved attempt only -- never per
    # attempt, since interim attempts get discarded and summarizing them
    # would be wasted cost/latency.
    long_feedback = (
        f"Strengths:\n{final_record.verdict_sections.strengths}\n\n"
        f"Weaknesses:\n{final_record.verdict_sections.weaknesses}\n\n"
        f"Verdict:\n{final_record.verdict_sections.verdict_text}"
    )
    summary_prompt = compose_summary_prompt(long_feedback)
    summary_result = generate_summary_response(summary_prompt)
    short_feedback = summary_result.text.strip()

    summary_breakdown = count_prompt_sections(
        {
            "long_feedback": long_feedback,
            "instructions_boilerplate": SUMMARY_INSTRUCTIONS_BOILERPLATE,
        },
        summary_result.model,
    )
    summary_cost = compute_cost(summary_result.usage, summary_result.model, summary_result.provider)
    summary_accounting = TokenAccountingPair(summary_breakdown, summary_result.usage)

    total_duration = (
        sum(a.verdict_duration_seconds + a.eval_duration_seconds for a in attempts)
        + summary_result.duration_seconds
    )
    total_cost = _sum_cost(attempts, extra_costs=(summary_cost,))
    logger.info(
        "/validate done in %s (%d attempt(s), threshold_met=%s) -- total cost %s",
        format_duration(total_duration), len(attempts), meets_threshold,
        f"${total_cost:.4f}" if total_cost is not None else "unpriced",
    )
    return OrchestrationResult(
        final_verdict_text=final_record.verdict_text,
        final_verdict_sections=final_record.verdict_sections,
        max_marks=max_marks,
        meets_quality_threshold=meets_threshold,
        best_score=final_record.eval_score,
        attempts=attempts,
        short_feedback=short_feedback,
        summary_token_accounting=summary_accounting,
        summary_duration_seconds=summary_result.duration_seconds,
        summary_cost=summary_cost,
        total_duration_seconds=total_duration,
        total_duration_formatted=format_duration(total_duration),
        total_cost_usd=total_cost,
        cost_by_model=_cost_by_model(attempts, extra=((summary_cost, summary_accounting),)),
        total_token_usage=_sum_tokens(attempts, extra=(summary_accounting,)),
        tokens_by_model=_tokens_by_model(attempts, extra=(summary_accounting,)),
    )
