from pydantic import BaseModel
from typing import Dict, List, Optional

class ValidateRequest(BaseModel):
    question: str
    student_answer: str
    max_marks: float

class ExactMatch(BaseModel):
    question_text: str
    answer_text: str
    subject: str
    similarity: float

class TokenUsage(BaseModel):
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    source: str  # "provider" | "unavailable"
    thinking_tokens: Optional[int] = None  # Gemini "thinking" models only; billed at completion rate

class PromptSectionTokens(BaseModel):
    sections: Dict[str, int]
    prompt_total_approx: int
    model_name: str
    encoding_used: str

class LLMCallTokenAccounting(BaseModel):
    local_prompt_breakdown: PromptSectionTokens
    provider_usage: TokenUsage

class CostBreakdown(BaseModel):
    prompt_cost_usd: Optional[float] = None
    completion_cost_usd: Optional[float] = None
    total_cost_usd: Optional[float] = None
    priced: bool
    pricing_source: str  # "openrouter_live" | "unpriced"

class VerdictAttempt(BaseModel):
    attempt_number: int
    verdict: str
    summary: str
    strengths: str
    weaknesses: str
    marks_awarded: Optional[float] = None
    marks_out_of: Optional[float] = None
    verdict_parse_ok: bool
    verdict_token_accounting: LLMCallTokenAccounting
    verdict_duration_seconds: float
    verdict_cost: CostBreakdown
    eval_score: float
    eval_critique: str
    eval_parse_ok: bool
    eval_token_accounting: LLMCallTokenAccounting
    eval_duration_seconds: float
    eval_cost: CostBreakdown

class ValidateResponse(BaseModel):
    verdict: str
    summary: str
    short_feedback: str
    max_marks: float
    exact_matches: List[ExactMatch]
    meets_quality_threshold: bool
    quality_score: float
    attempts: List[VerdictAttempt]
    summary_token_accounting: LLMCallTokenAccounting
    summary_duration_seconds: float
    summary_cost: CostBreakdown
    total_duration_seconds: float
    total_duration_formatted: str
    total_cost_usd: Optional[float] = None
    cost_by_model: Optional[Dict[str, float]] = None
    total_token_usage: Optional[Dict[str, int]] = None
    tokens_by_model: Optional[Dict[str, Dict[str, int]]] = None

class ErrorResponse(BaseModel):
    detail: str