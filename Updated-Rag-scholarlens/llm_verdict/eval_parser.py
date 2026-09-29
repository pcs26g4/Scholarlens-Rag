import re
from dataclasses import dataclass

_SCORE_HEADING_RE = re.compile(r"^##\s*SCORE\s*$", re.IGNORECASE)
_CRITIQUE_HEADING_RE = re.compile(r"^##\s*CRITIQUE\s*$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%?")


@dataclass
class EvalResult:
    score: float
    critique: str
    parse_ok: bool
    raw: str


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_score(raw_number: float) -> float:
    # A value like "95" or "95%" means 0.95; a value already in [0, 1] is left as-is.
    if raw_number > 1.0:
        raw_number = raw_number / 100.0
    return _clamp(raw_number)


def parse_eval_response(text: str) -> EvalResult:
    if not text:
        return EvalResult(score=0.0, critique="", parse_ok=False, raw=text or "")

    lines = text.splitlines()

    score_line_idx = None
    critique_line_idx = None
    for i, line in enumerate(lines):
        if score_line_idx is None and _SCORE_HEADING_RE.match(line.strip()):
            score_line_idx = i
        elif critique_line_idx is None and _CRITIQUE_HEADING_RE.match(line.strip()):
            critique_line_idx = i

    score = None
    if score_line_idx is not None:
        search_end = critique_line_idx if critique_line_idx is not None else len(lines)
        for line in lines[score_line_idx + 1:search_end]:
            match = _NUMBER_RE.search(line)
            if match:
                score = _normalize_score(float(match.group(1)))
                break

    critique = ""
    if critique_line_idx is not None:
        critique = "\n".join(lines[critique_line_idx + 1:]).strip()

    if score is not None:
        if not critique:
            # Heading-based split found a score but no distinct critique block;
            # fall back to everything after the score line as the critique.
            tail_start = score_line_idx + 1
            critique = "\n".join(lines[tail_start:]).strip()
        return EvalResult(score=score, critique=critique, parse_ok=True, raw=text)

    # Tier 2 fallback: no "## SCORE" heading found at all -- scan the whole
    # text for a loose "score: 0.87" / "score = 87%" style mention.
    loose_match = re.search(r"score[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?", text, re.IGNORECASE)
    if loose_match:
        score = _normalize_score(float(loose_match.group(1)))
        return EvalResult(score=score, critique=text.strip(), parse_ok=True, raw=text)

    # Fail closed: no score could be extracted at all. Forces a retry rather
    # than silently accepting an unevaluated verdict.
    return EvalResult(score=0.0, critique=text.strip(), parse_ok=False, raw=text)
