import re
from dataclasses import dataclass
from typing import Optional

_STRICT_HEADINGS = {
    "summary": re.compile(r"^##\s*SUMMARY\s*$", re.IGNORECASE),
    "strengths": re.compile(r"^##\s*STRENGTHS\s*$", re.IGNORECASE),
    "weaknesses": re.compile(r"^##\s*WEAKNESSES\s*$", re.IGNORECASE),
    "verdict": re.compile(r"^##\s*VERDICT\s*$", re.IGNORECASE),
}

_FUZZY_TARGETS = {
    "SUMMARY": "summary",
    "STRENGTHS": "strengths",
    "WEAKNESSES": "weaknesses",
    "VERDICT": "verdict",
    "RUBRICBASEDVERDICT": "verdict",
}

_MARKS_RE = re.compile(r"Marks:\s*([\d]+(?:\.\d+)?)\s*/\s*([\d]+(?:\.\d+)?)", re.IGNORECASE)


@dataclass
class VerdictSections:
    summary: str
    strengths: str
    weaknesses: str
    verdict_text: str
    marks_awarded: Optional[float]
    marks_out_of: Optional[float]
    parse_ok: bool


def _split_by_line_predicate(lines, is_heading_fn):
    """Split `lines` into {section_key: [content lines]} using a predicate that
    returns a section key (or None) for a given line. Lines before the first
    recognized heading are dropped."""
    sections = {}
    current_key = None
    for line in lines:
        key = is_heading_fn(line)
        if key:
            current_key = key
            sections.setdefault(current_key, [])
            continue
        if current_key:
            sections.setdefault(current_key, []).append(line)
    return sections


def _strict_heading(line):
    for key, pattern in _STRICT_HEADINGS.items():
        if pattern.match(line.strip()):
            return key
    return None


def _fuzzy_heading(line):
    stripped = re.sub(r"[^A-Za-z]", "", line).upper()
    return _FUZZY_TARGETS.get(stripped)


def parse_verdict_sections(text: str) -> VerdictSections:
    if not text:
        return VerdictSections(summary="", strengths="", weaknesses="", verdict_text="", marks_awarded=None, marks_out_of=None, parse_ok=False)

    lines = text.splitlines()

    strict_sections = _split_by_line_predicate(lines, _strict_heading)
    if len(strict_sections) >= 3:
        sections = strict_sections
        parse_ok = True
    else:
        fuzzy_sections = _split_by_line_predicate(lines, _fuzzy_heading)
        if len(fuzzy_sections) >= 2:
            sections = fuzzy_sections
            parse_ok = True
        else:
            # Tier 3: give up gracefully -- treat the whole response as the
            # weakness section so downstream evaluation still has something
            # concrete (and over-inclusive, not silently empty) to check.
            return VerdictSections(
                summary="",
                strengths="",
                weaknesses=text.strip(),
                verdict_text=text.strip(),
                marks_awarded=None,
                marks_out_of=None,
                parse_ok=False,
            )

    summary = "\n".join(sections.get("summary", [])).strip()
    strengths = "\n".join(sections.get("strengths", [])).strip()
    weaknesses = "\n".join(sections.get("weaknesses", [])).strip()
    verdict_text = "\n".join(sections.get("verdict", [])).strip()

    marks_match = _MARKS_RE.search(verdict_text) or _MARKS_RE.search(text)
    marks_awarded = float(marks_match.group(1)) if marks_match else None
    marks_out_of = float(marks_match.group(2)) if marks_match else None

    return VerdictSections(
        summary=summary,
        strengths=strengths,
        weaknesses=weaknesses,
        verdict_text=verdict_text,
        marks_awarded=marks_awarded,
        marks_out_of=marks_out_of,
        parse_ok=parse_ok,
    )


def extract_weaknesses(text: str) -> str:
    return parse_verdict_sections(text).weaknesses
