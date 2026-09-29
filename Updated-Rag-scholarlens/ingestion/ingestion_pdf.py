import re
from ingestion.qadrant_init import ensure_qdrant
from ingestion.pdf_utils import extract_pdf_text
from ingestion.qdrant_upsert import upsert_records

# Matches the "N. Question\n<text>\nAnswer\n<text>\nSubject: <text>" layout
# produced by pdf_render/render_pdf.py (see qa_content.pdf).
QA_PDF_PATTERN = re.compile(
    r'\d+\.\s*Question\s*\n(.*?)\nAnswer\s*\n(.*?)\nSubject:\s*(.*?)(?=\n\d+\.\s*Question|\Z)',
    re.DOTALL
)


def parse_canonical_qa_pdf(text):
    records = []
    for question, answer, subject in QA_PDF_PATTERN.findall(text):
        records.append({
            "question_text": " ".join(question.split()),
            "answer_text": " ".join(answer.split()),
            "subject": " ".join(subject.split()),
        })
    return records


def main(pdf_paths=None, qp_sa_pairs=None):
    """pdf_paths: canonical Question/Answer/Subject PDFs (see qa_content.pdf).
    qp_sa_pairs: list of (question_paper_path, answer_paper_path) tuples.
    """
    from ingestion.qp_sa_converter import convert_qp_sa

    ensure_qdrant()
    records = []
    for path in (pdf_paths or []):
        text = extract_pdf_text(path)
        parsed = parse_canonical_qa_pdf(text)
        if not parsed:
            print(f"WARNING: no Q&A entries parsed from {path}")
        records.extend(parsed)

    for qp_path, sa_path in (qp_sa_pairs or []):
        parsed, warnings = convert_qp_sa(qp_path, sa_path)
        for w in warnings:
            print(f"WARNING [{qp_path}]: {w}")
        records.extend(parsed)

    count = upsert_records(records)
    print(f"Ingested {count} Q&A pairs.")


if __name__ == '__main__':
    import sys
    main(pdf_paths=sys.argv[1:])
