import os
import uuid
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from embedding_backend import get_embedder

load_dotenv()
COLLECTION_NAME = os.getenv('COLLECTION_NAME', 'student_validator_qa')
QDRANT_HOST = os.getenv('QDRANT_HOST', 'localhost')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', 6333))
EMBED_MODEL = os.getenv('EMBED_MODEL', 'all-MiniLM-L6-v2')

# Fixed namespace so the same record always hashes to the same point ID,
# regardless of which process/run computed it.
_ID_NAMESPACE = uuid.UUID('c9c8b1c0-4b8b-4b8b-8b8b-1b1b1b1b1b1b')


def record_id(record):
    """Deterministic point ID from record content, so re-ingesting the same
    Q&A (e.g. re-running ingestion on the same file) overwrites the existing
    point instead of creating a duplicate."""
    key = f"{record['question_text']}||{record['answer_text']}||{record['subject']}"
    return str(uuid.uuid5(_ID_NAMESPACE, key))


def upsert_records(records, qclient=None, embedder=None):
    embedder = embedder or get_embedder(EMBED_MODEL)
    qclient = qclient or QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    dim = len(embedder.get_text_embedding("hi"))
    try:
        qclient.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE)
        )
    except Exception:
        pass  # collection exists
    points = []
    for record in records:
        vec = embedder.get_text_embedding(record['question_text'])
        points.append(qmodels.PointStruct(
            id=record_id(record),
            vector=vec,
            payload=record,
        ))
    qclient.upsert(collection_name=COLLECTION_NAME, points=points)
    return len(points)
