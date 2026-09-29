import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from embedding_backend import get_embedder

load_dotenv()
COLLECTION_NAME = os.getenv('COLLECTION_NAME', 'student_validator_qa')
QDRANT_HOST = os.getenv('QDRANT_HOST', 'localhost')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', 6333))
EMBED_MODEL = os.getenv('EMBED_MODEL', 'all-MiniLM-L6-v2')

embedder = get_embedder(EMBED_MODEL)
retrieval_dim = len(embedder.get_text_embedding("test"))

def retrieve_similar_questions(question, top_k=2):
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    query_vec = embedder.get_text_embedding(question)
    res = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vec,
        limit=top_k,
        with_vectors=False,
        with_payload=True,
    )
    # Return: list of {question_text, answer_text, subject, similarity}
    return [
        {
            "question_text": r.payload["question_text"],
            "answer_text": r.payload["answer_text"],
            "subject": r.payload["subject"],
            "similarity": float(r.score)
        }
        for r in res.points
    ]