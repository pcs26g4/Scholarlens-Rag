import os
import pytest
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from ingestion.qdrant_upsert import EMBED_MODEL
from embedding_backend import get_embedder

load_dotenv()
COLLECTION_NAME = os.getenv('COLLECTION_NAME', 'student_validator_qa')
QDRANT_HOST = os.getenv('QDRANT_HOST', 'localhost')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', 6333))


def test_qdrant_collection_populated(ensure_populated_qdrant, sample_qa_df):
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    info = client.get_collection(COLLECTION_NAME)
    assert info is not None
    vectors_count = client.count(COLLECTION_NAME).count
    assert vectors_count == len(sample_qa_df), f"Qdrant count={vectors_count} but CSV={len(sample_qa_df)}"

def test_upserted_payload_matches_csv(ensure_populated_qdrant, sample_qa_df):
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    all_points = []
    offset = 0
    while True:
        batch = client.scroll(
            collection_name=COLLECTION_NAME, 
            with_payload=True, 
            with_vectors=True, 
            limit=100, 
            offset=offset
        )[0]
        if not batch:
            break
        all_points.extend(batch)
        offset += len(batch)
    assert len(all_points) == len(sample_qa_df)
    points_by_question = {p.payload["question_text"]: p for p in all_points}
    for _, row in sample_qa_df.iterrows():
        point = points_by_question[row["question_text"]]
        pl = point.payload
        assert pl["question_text"] == row["question_text"]
        assert pl["answer_text"] == row["answer_text"]
        assert pl["subject"] == row["subject"]
        # Embedding should have used ONLY question text
        embedder = get_embedder(EMBED_MODEL)
        v1 = embedder.get_text_embedding(row["question_text"])
        v2 = point.vector
        assert len(v1) == len(v2)
        assert all(abs(a-b)<1e-5 for a,b in zip(v1,v2)), f"Embedding vector mismatch for '{row['question_text']}'"