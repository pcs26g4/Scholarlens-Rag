import pandas as pd
from ingestion.qadrant_init import ensure_qdrant
from ingestion.qdrant_upsert import upsert_records


def main():
    ensure_qdrant()
    df = pd.read_csv('qa.csv')
    assert all(c in df.columns for c in ['question_text', 'answer_text', 'subject']), "CSV missing required cols."
    records = df[['question_text', 'answer_text', 'subject']].to_dict('records')
    count = upsert_records(records)
    print(f"Ingested {count} Q&A pairs.")


if __name__ == '__main__':
    main()
