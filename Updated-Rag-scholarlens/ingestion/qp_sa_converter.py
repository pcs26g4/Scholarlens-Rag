import re
from ingestion.pdf_utils import extract_pdf_text

# Running headers/footers repeated on every page of these exam-paper PDFs.
BOILERPLATE_RE = re.compile(
    r'^\s*(CA\s*-FOUNDATION.*|No\.1 for CA/CMA.*|B\.LAW SUGGESTED|THE END)\s*$'
)
MARK_RE = re.compile(r'\[(\d+)M\]')
SA_KEY_RE = re.compile(r'Question No\.\s*(\d+)\s*\(([a-c])\)\s*(?:\(([ivx]+)\))?\s*\[(\d+)M\]')
QUESTION_HEADER_RE = re.compile(r'Question\s+\d+\s*:\s*(?:\d+\s*Marks)?')
CHAPTER_RE = re.compile(r'Chapter:\s*(.*?)\s*Time:')


def _clean(text):
    lines = [l for l in text.splitlines() if l.strip() and not BOILERPLATE_RE.match(l)]
    return "\n".join(lines)


def _segment_key(sa_match):
    num, letter, roman, marks = sa_match.groups()
    key = f"{num}{letter}"
    if roman:
        key += f"-{roman}"
    return key, marks


def convert_qp_sa(qp_path, sa_path, subject=None):
    """Parse a question-paper PDF + suggested-answer PDF pair into canonical
    {question_text, answer_text, subject} records, matched by sub-part order.

    Returns (records, warnings). If the two documents don't have the same
    number of gradeable sub-parts, no records are returned -- the pair is
    too ambiguous to auto-match and needs manual handling. Mark-value
    mismatches between QP and SA for an otherwise-aligned sub-part are
    still paired but reported as warnings, since they typically indicate a
    typo in one source document rather than a structural misalignment.
    """
    qp_raw = extract_pdf_text(qp_path)
    sa_raw = extract_pdf_text(sa_path)
    qp = _clean(qp_raw)
    sa = _clean(sa_raw)

    qp_marks = list(MARK_RE.finditer(qp))
    sa_matches = list(SA_KEY_RE.finditer(sa))

    warnings = []
    if len(qp_marks) != len(sa_matches):
        warnings.append(
            f"NEEDS REVIEW: {qp_path} has {len(qp_marks)} marked sub-parts but "
            f"{sa_path} has {len(sa_matches)} answer entries -- counts don't match, "
            f"skipping auto-conversion for this pair."
        )
        return [], warnings

    if subject is None:
        m = CHAPTER_RE.search(qp_raw)
        subject = " ".join(m.group(1).split()) if m else "Unknown"

    records = []
    first_question = re.search(r'Question\s+\d+\s*:', qp)
    qp_pos = first_question.start() if first_question else 0
    for i, (qp_mark, sa_match) in enumerate(zip(qp_marks, sa_matches)):
        key, sa_marks = _segment_key(sa_match)

        question_text = qp[qp_pos:qp_mark.end()]
        question_text = QUESTION_HEADER_RE.sub('', question_text)
        question_text = " ".join(question_text.split())
        qp_pos = qp_mark.end()

        answer_start = sa_match.end()
        answer_end = sa_matches[i + 1].start() if i + 1 < len(sa_matches) else len(sa)
        answer_text = " ".join(sa[answer_start:answer_end].split())

        records.append({
            "question_text": question_text,
            "answer_text": answer_text,
            "subject": subject,
        })

        if qp_mark.group(1) != sa_marks:
            warnings.append(
                f"VERIFY: segment {key} -- QP shows [{qp_mark.group(1)}M] but "
                f"SA shows [{sa_marks}M]; paired positionally, check for a typo."
            )

    return records, warnings
