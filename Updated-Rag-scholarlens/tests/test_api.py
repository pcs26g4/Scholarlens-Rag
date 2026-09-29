import json
import pytest
from fastapi.testclient import TestClient

from api.main import app
from retrieval.retriever import retrieve_similar_questions

MOCKED_VERDICT_TEXT = (
    "## SUMMARY\nGood attempt, but a couple of things are missing.\n\n"
    "## STRENGTHS\nOn-topic and clearly written.\n\n"
    "## WEAKNESSES\nNone identified.\n\n"
    "## VERDICT\nSolid answer overall.\nMarks: 4/5"
)
MOCKED_SHORT_FEEDBACK = "You scored 4/5. Good, clear answer with nothing major missing."

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture(autouse=True)
def patch_llm(monkeypatch):
    # Patch both LLM calls (verdict generation + weakness evaluation) so tests
    # never hit external network. Patched where they're looked up (the
    # orchestrator's own namespace, since it did `from ... import name`).
    from llm_verdict import verdict_llm, verdict_orchestrator, pricing

    def _fake_verdict(prompt):
        return verdict_llm.LLMCallResult(
            text=MOCKED_VERDICT_TEXT,
            usage=verdict_llm.LLMUsage(10, 5, 15, "provider"),
            provider="openrouter",
            model="test-verdict-model",
            duration_seconds=0.5,
        )

    def _fake_eval(prompt):
        return verdict_llm.LLMCallResult(
            text="## SCORE\n0.95\n\n## CRITIQUE\nNo issues found.",
            usage=verdict_llm.LLMUsage(8, 3, 11, "provider"),
            provider="openrouter",
            model="test-eval-model",
            duration_seconds=0.3,
        )

    def _fake_summary(prompt):
        return verdict_llm.LLMCallResult(
            text=MOCKED_SHORT_FEEDBACK,
            usage=verdict_llm.LLMUsage(6, 2, 8, "provider"),
            provider="openrouter",
            model="test-summary-model",
            duration_seconds=0.2,
        )

    def _fake_compute_cost(usage, model, provider):
        return pricing.CostBreakdown(
            prompt_cost_usd=usage.prompt_tokens * 0.000002,
            completion_cost_usd=usage.completion_tokens * 0.000008,
            total_cost_usd=usage.prompt_tokens * 0.000002 + usage.completion_tokens * 0.000008,
            priced=True,
            pricing_source="openrouter_live",
        )

    monkeypatch.setattr(verdict_orchestrator, "generate_verdict_response", _fake_verdict)
    monkeypatch.setattr(verdict_orchestrator, "generate_eval_response", _fake_eval)
    monkeypatch.setattr(verdict_orchestrator, "generate_summary_response", _fake_summary)
    monkeypatch.setattr(verdict_orchestrator, "compute_cost", _fake_compute_cost)

def test_api_validate_returns_verdict(client, sample_qa_df):
    # Use question that is definitely present
    question = sample_qa_df.iloc[0]["question_text"]
    # arbitrary student answer
    data = {"question": question, "student_answer": "A correct student answer.", "max_marks": 5.0}
    resp = client.post("/validate", json=data)
    assert resp.status_code == 200
    out = resp.json()
    assert out["verdict"] == MOCKED_VERDICT_TEXT
    assert out["summary"] == "Good attempt, but a couple of things are missing."
    assert out["short_feedback"] == MOCKED_SHORT_FEEDBACK
    assert out["max_marks"] == 5.0
    assert isinstance(out["exact_matches"], list)
    assert 1 <= len(out["exact_matches"]) <= 2
    for m in out["exact_matches"]:
        assert "question_text" in m
        assert "answer_text" in m
        assert "subject" in m
        assert 0 <= float(m["similarity"]) <= 1.0

    # Evaluation-layer fields: the mocked checker scores 0.95 >= the default
    # 0.90 threshold, so the loop should resolve after a single attempt.
    assert out["meets_quality_threshold"] is True
    assert out["quality_score"] == 0.95
    assert len(out["attempts"]) == 1

    attempt = out["attempts"][0]
    assert attempt["attempt_number"] == 1
    assert attempt["eval_score"] == 0.95
    assert attempt["eval_parse_ok"] is True
    assert attempt["verdict_parse_ok"] is True
    assert attempt["summary"] == "Good attempt, but a couple of things are missing."
    assert attempt["strengths"] == "On-topic and clearly written."
    assert attempt["weaknesses"] == "None identified."
    assert attempt["marks_awarded"] == 4.0
    assert attempt["marks_out_of"] == 5.0

    verdict_sections = attempt["verdict_token_accounting"]["local_prompt_breakdown"]["sections"]
    assert set(verdict_sections.keys()) == {
        "question", "textbook_answers", "student_answer", "rubric", "instructions_boilerplate",
    }
    assert all(isinstance(v, int) and v >= 0 for v in verdict_sections.values())

    eval_sections = attempt["eval_token_accounting"]["local_prompt_breakdown"]["sections"]
    assert set(eval_sections.keys()) == {
        "strengths_section", "weakness_section", "verdict_section",
        "question_and_student_answer", "rubric", "baseline_answer", "instructions_boilerplate",
    }

    for accounting_key in ("verdict_token_accounting", "eval_token_accounting"):
        usage = attempt[accounting_key]["provider_usage"]
        assert usage["source"] == "provider"
        assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]

    # Timing: per-call durations from the mocked LLMCallResults, summed into a total
    # -- verdict (0.5) + eval (0.3) + the one-off summarization call (0.2).
    assert attempt["verdict_duration_seconds"] == 0.5
    assert attempt["eval_duration_seconds"] == 0.3
    assert out["summary_duration_seconds"] == 0.2
    assert out["total_duration_seconds"] == pytest.approx(1.0)
    assert out["total_duration_formatted"] == "0m 1s"

    # Cost: from the mocked compute_cost, using the mocked token usage.
    assert attempt["verdict_cost"]["priced"] is True
    assert attempt["verdict_cost"]["total_cost_usd"] == pytest.approx(10 * 0.000002 + 5 * 0.000008)
    assert attempt["eval_cost"]["priced"] is True
    assert attempt["eval_cost"]["total_cost_usd"] == pytest.approx(8 * 0.000002 + 3 * 0.000008)
    assert out["summary_cost"]["priced"] is True
    assert out["summary_cost"]["total_cost_usd"] == pytest.approx(6 * 0.000002 + 2 * 0.000008)
    expected_total_cost = (
        attempt["verdict_cost"]["total_cost_usd"]
        + attempt["eval_cost"]["total_cost_usd"]
        + out["summary_cost"]["total_cost_usd"]
    )
    assert out["total_cost_usd"] == pytest.approx(expected_total_cost)

    # Cost broken down per model -- verdict, eval, and summary all used
    # different models, so this should be three separate entries.
    assert out["cost_by_model"] == {
        "test-verdict-model": pytest.approx(attempt["verdict_cost"]["total_cost_usd"]),
        "test-eval-model": pytest.approx(attempt["eval_cost"]["total_cost_usd"]),
        "test-summary-model": pytest.approx(out["summary_cost"]["total_cost_usd"]),
    }

    # Tokens: overall grand total (verdict LLMUsage(10,5,15) + eval LLMUsage(8,3,11)
    # + summary LLMUsage(6,2,8)).
    assert out["total_token_usage"] == {
        "prompt_tokens": 24, "completion_tokens": 10, "thinking_tokens": 0, "total_tokens": 34,
    }
    # Tokens broken down per model -- same three-model split as cost_by_model.
    assert out["tokens_by_model"] == {
        "test-verdict-model": {"prompt_tokens": 10, "completion_tokens": 5, "thinking_tokens": 0, "total_tokens": 15},
        "test-eval-model": {"prompt_tokens": 8, "completion_tokens": 3, "thinking_tokens": 0, "total_tokens": 11},
        "test-summary-model": {"prompt_tokens": 6, "completion_tokens": 2, "thinking_tokens": 0, "total_tokens": 8},
    }

def test_api_validate_threshold(client, sample_qa_df, monkeypatch):
    # Patch retrieval to return below-threshold similarities
    monkeypatch.setattr("retrieval.retriever.retrieve_similar_questions", lambda q, top_k=2: [
        {"question_text": "q1", "answer_text": "a1", "subject": "law", "similarity": 0.6}
    ])
    data = {"question": "Inapplicable question", "student_answer": "Blank", "max_marks": 5.0}
    resp = client.post("/validate", json=data)
    assert resp.status_code == 404
    assert "similarity < 0.80" in resp.text
