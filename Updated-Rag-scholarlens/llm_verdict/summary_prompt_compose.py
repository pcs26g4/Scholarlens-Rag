SUMMARY_INSTRUCTIONS_BOILERPLATE = """You are a summarization assistant. You will be given a full, detailed grading write-up (strengths, weaknesses, and marks awarded) for a student's law-exam answer. Your ONLY job is to compress it into a short, crisp, plain-English summary the student can read in a few seconds.

Rules:
1. Keep it to 2-3 short sentences, no more than about 50 words total. Be direct and to the point -- like a gunshot, not a lecture.
2. Use simple, everyday English. Many students are first-generation learners from rural backgrounds with limited exposure to formal English -- avoid dense or academic phrasing.
3. Always mention the marks awarded (out of the maximum) somewhere in the summary.
4. Mention the single most important strength, and the single most important weakness if any weakness exists. If there are truly no weaknesses, say so plainly.
5. Do not add any information that isn't in the write-up below, and do not use headings, labels, or bullet points -- output ONLY the summary text itself, nothing else.
"""


def compose_summary_prompt(long_feedback: str) -> str:
    return f"""{SUMMARY_INSTRUCTIONS_BOILERPLATE}

**Full grading write-up:**
{long_feedback.strip()}
"""
