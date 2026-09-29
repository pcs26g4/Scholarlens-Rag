import logging
import os
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

from api.schemas import (
    ValidateRequest, ValidateResponse, ExactMatch, ErrorResponse,
    VerdictAttempt, LLMCallTokenAccounting, PromptSectionTokens, TokenUsage, CostBreakdown,
)

from retrieval.retriever import retrieve_similar_questions
from llm_verdict.rules_loader import load_rules_yaml
from llm_verdict.verdict_orchestrator import run_verdict_with_evaluation, TokenAccountingPair
from llm_verdict.verdict_llm import LLMTimeoutError

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

load_dotenv()
TOP_K = int(os.getenv('TOP_K', 2))
SIM_THRESHOLD = float(os.getenv('SIMILARITY_THRESHOLD', 0.8))
if not SIM_THRESHOLD:
    import yaml
    with open('config.yaml') as f:
        SIM_THRESHOLD = float(yaml.safe_load(f)['retrieval']['similarity_threshold'])

app = FastAPI()


def _token_accounting_to_schema(pair: TokenAccountingPair) -> LLMCallTokenAccounting:
    breakdown = pair.local_prompt_breakdown
    usage = pair.provider_usage
    return LLMCallTokenAccounting(
        local_prompt_breakdown=PromptSectionTokens(
            sections=breakdown.sections,
            prompt_total_approx=breakdown.prompt_total_approx,
            model_name=breakdown.model_name,
            encoding_used=breakdown.encoding_used,
        ),
        provider_usage=TokenUsage(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            source=usage.source,
            thinking_tokens=usage.thinking_tokens,
        ),
    )


def _cost_to_schema(cost) -> CostBreakdown:
    return CostBreakdown(
        prompt_cost_usd=cost.prompt_cost_usd,
        completion_cost_usd=cost.completion_cost_usd,
        total_cost_usd=cost.total_cost_usd,
        priced=cost.priced,
        pricing_source=cost.pricing_source,
    )


def _attempt_to_schema(record) -> VerdictAttempt:
    return VerdictAttempt(
        attempt_number=record.attempt_number,
        verdict=record.verdict_text,
        summary=record.verdict_sections.summary,
        strengths=record.verdict_sections.strengths,
        weaknesses=record.verdict_sections.weaknesses,
        marks_awarded=record.verdict_sections.marks_awarded,
        marks_out_of=record.verdict_sections.marks_out_of,
        verdict_parse_ok=record.verdict_sections.parse_ok,
        verdict_token_accounting=_token_accounting_to_schema(record.verdict_token_accounting),
        verdict_duration_seconds=record.verdict_duration_seconds,
        verdict_cost=_cost_to_schema(record.verdict_cost),
        eval_score=record.eval_score,
        eval_critique=record.eval_critique,
        eval_parse_ok=record.eval_parse_ok,
        eval_token_accounting=_token_accounting_to_schema(record.eval_token_accounting),
        eval_duration_seconds=record.eval_duration_seconds,
        eval_cost=_cost_to_schema(record.eval_cost),
    )


@app.post("/validate", response_model=ValidateResponse, responses={404: {"model": ErrorResponse}})
def validate(req: ValidateRequest):
    matches = retrieve_similar_questions(req.question, top_k=TOP_K)
    # Only keep those above similarity threshold
    matches_filtered = [m for m in matches if m['similarity'] > SIM_THRESHOLD]
    if not matches_filtered:
        raise HTTPException(status_code=404, detail="No semantically similar question found in Q&A bank (similarity < 0.80).")
    answer_textbook = [m['answer_text'] for m in matches_filtered]
    rules_md = load_rules_yaml()

    try:
        result = run_verdict_with_evaluation(
            question=req.question,
            student_answer=req.student_answer,
            answer_textbook_list=answer_textbook,
            rules_md=rules_md,
            max_marks=req.max_marks,
        )
    except LLMTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))

    exact_matches = [ExactMatch(**m) for m in matches_filtered]
    return ValidateResponse(
        verdict=result.final_verdict_text,
        summary=result.final_verdict_sections.summary,
        short_feedback=result.short_feedback,
        max_marks=result.max_marks,
        exact_matches=exact_matches,
        meets_quality_threshold=result.meets_quality_threshold,
        quality_score=result.best_score,
        attempts=[_attempt_to_schema(a) for a in result.attempts],
        summary_token_accounting=_token_accounting_to_schema(result.summary_token_accounting),
        summary_duration_seconds=result.summary_duration_seconds,
        summary_cost=_cost_to_schema(result.summary_cost),
        total_duration_seconds=result.total_duration_seconds,
        total_duration_formatted=result.total_duration_formatted,
        total_cost_usd=result.total_cost_usd,
        cost_by_model=result.cost_by_model,
        total_token_usage=result.total_token_usage,
        tokens_by_model=result.tokens_by_model,
    )