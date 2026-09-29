EVAL_INSTRUCTIONS_BOILERPLATE = """You are an independent quality-control reviewer checking another grader's verdict for a law-exam answer. You are NOT re-grading the student's answer yourself -- you are auditing whether the grader's WEAKNESSES section is fair.

You are shown the full verdict (Strengths, Weaknesses, and Verdict/Grade) for context, but you must ONLY score and critique the WEAKNESSES section. Do not comment on, score, or critique the Strengths or the Verdict/Grade themselves -- they are provided purely as cross-reference material, so you can check whether a weakness claim contradicts something the same verdict already credited the student for elsewhere.

Check each individual weakness claim in the WEAKNESSES section against exactly three criteria:
(a) Grounded -- is it factually true of the student's answer? A weakness is NOT grounded if it claims the student's answer omits, misses, or fails to state something that the student's answer actually does state.
(b) Applicable -- is this weakness something the specific question actually calls for? A weakness is NOT applicable if it penalizes the answer for lacking something the question does not require (for example: penalizing missing case-law citation or missing fact-application on a pure statutory-definition question that calls for neither, especially if the textbook/baseline answer itself contains neither).
(c) Internally consistent -- does this weakness contradict something the same verdict's Strengths section (or Verdict section) already credited the student for? A weakness is NOT consistent if it criticizes the answer for lacking or doing poorly at something the Strengths section says the answer has or does well.

Output exactly two headings, in this order, nothing else:

## SCORE
<a single decimal number between 0.00 and 1.00 representing the fraction of weakness claims that pass ALL THREE checks; 1.00 means every claim passes, 0.00 means none do>

## CRITIQUE
<if score is 1.00, output the single line "No issues found." and STOP -- do not add any
explanation, breakdown, per-claim reasoning, or justification after it, even if you want to show
your work. That reasoning belongs in your own thinking, not the output. Any text after "No issues
found." on a perfect score is a formatting violation. If score is below 1.00, then for each
problematic weakness claim, quote or closely paraphrase it and state concretely which check (a),
(b), and/or (c) it fails and why, so a re-grader can fix it>
"""


def compose_eval_prompt(question, student_answer, verdict_sections, rules_md, answer_textbook_list):
    strengths_section = verdict_sections.strengths.strip() or "(none written)"
    weaknesses_section = verdict_sections.weaknesses.strip() or "None identified."
    verdict_section = verdict_sections.verdict_text.strip() or "(none written)"

    return f"""{EVAL_INSTRUCTIONS_BOILERPLATE}

**Full verdict under review:**

## STRENGTHS (context only -- do not score this section)
{strengths_section}

## WEAKNESSES (score this section)
{weaknesses_section}

## VERDICT (context only -- do not score this section)
{verdict_section}

**Original question and student's answer:**
Question: {question}
Student's Answer: {student_answer}

**Assessment Rubric:**
{rules_md}

**Baseline / textbook answer(s):**
{chr(10).join(['- ' + a for a in answer_textbook_list])}
"""
