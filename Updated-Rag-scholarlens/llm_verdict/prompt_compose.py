INSTRUCTIONS_BOILERPLATE = """Instructions:

1. First check whether the student's answer actually addresses the question asked above; note if it drifts off-topic or answers a different question.
2. Thoroughly compare the student's answer to the textbook answer(s), focusing not only on correctness, but also depth, clarity, structure, and accuracy according to the above rubric.
3. Explicitly reference relevant rubric criteria in your evaluation. Do not simply echo text; instead, identify strengths, weaknesses, missing elements, legal misapplications, or exemplary features. Only raise a rubric criterion as a weakness if it is genuinely relevant to what this specific question calls for -- do not penalize an answer for missing something the question never required (e.g. do not fault a purely definitional/statutory question for lacking case-law citation or fact-application if the textbook answer itself has none).
4. Do not claim the student's answer omits something it actually states -- re-read the student's answer text before listing a weakness.
5. Check the student's writing itself for spelling mistakes, grammatical mistakes, and sentence formation problems (per the rubric criteria for these), in addition to the legal content. When you find one, quote the specific word or sentence and say what is wrong with it -- do not just say "there are spelling errors" without naming them.
6. Grade strictly and fairly against the Maximum Marks given above, proportional to how well the rubric criteria that actually apply to this question are satisfied. Do not be generous -- only award marks for what the student's answer genuinely demonstrates. The marks you award must never exceed the Maximum Marks.
7. Write ALL of your response (summary, strengths, weaknesses, verdict) in SIMPLE, PLAIN ENGLISH. Many students are first-generation learners from rural backgrounds with limited exposure to formal English, so avoid dense, formal, academic phrasing -- use short sentences and everyday words wherever possible. You must still name the correct legal terms/sections where relevant (e.g. "Section 2(d)"), but explain them plainly rather than assuming the reader already knows formal legal vocabulary or complex English sentence structures.
8. Output exactly these four headings, each alone on its own line, in this exact order, with no bold markers, brackets, or renumbering:

## SUMMARY
<1-2 short, simple sentences summing up the overall result -- written so a student could read just this and understand how they did>

## STRENGTHS
<content, in simple plain English>

## WEAKNESSES
<content, in simple plain English, or the single line "None identified." if there are truly none>

## VERDICT
<justification in simple plain English, ending with a line of the exact form "Marks: X/Y" where Y is exactly the Maximum Marks given above and X is the marks you are awarding out of that maximum -- X may be a decimal (e.g. "Marks: 3.5/5") and must never exceed Y>

Do not invent facts outside the supplied content.
"""


def compose_prompt(question, answer_textbook_list, answer_student, rules_md, max_marks, retry_feedback=None):
    feedback_block = ""
    if retry_feedback:
        feedback_block = f"""
**Note -- a prior attempt at this evaluation was judged inadequate by an independent reviewer:**
{retry_feedback}

Address this specifically when writing the Weaknesses section: only include a weakness if it is
(a) factually grounded in the student's actual answer text (not something the student in fact
wrote/covered), and (b) actually applicable to what this specific question calls for.
"""

    prompt = f"""You are a rigorous legal examiner for Indian Business Law. Your task is to compare a student's answer to a corresponding model textbook answer and evaluate the student's response according to an explicit assessment rubric.

**Question:**
{question}

**Maximum Marks for this Question:** {max_marks}

**Textbook Answer(s):**
{chr(10).join(['- '+a for a in answer_textbook_list])}

**Student's Answer:**
{answer_student}

**Assessment Rubric:**
{rules_md}
{feedback_block}
{INSTRUCTIONS_BOILERPLATE}"""
    return prompt
