import os

EMBED_BACKEND = os.getenv('EMBED_BACKEND', 'sentence_transformers')


class _SentenceTransformerEmbedder:
    def __init__(self, model_name):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)

    def get_text_embedding(self, text):
        return self._model.encode(text).tolist()


def get_embedder(model_name):
    """Return an embedder exposing get_text_embedding(text) -> list[float].

    Backend is chosen via EMBED_BACKEND env var:
      - 'sentence_transformers' (default): sentence-transformers directly.
      - 'llama_index_hf': llama_index's HuggingFaceEmbedding wrapper.
    """
    if EMBED_BACKEND == 'llama_index_hf':
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        return HuggingFaceEmbedding(model_name=model_name)
    if EMBED_BACKEND == 'sentence_transformers':
        return _SentenceTransformerEmbedder(model_name)
    raise ValueError(f"Unknown EMBED_BACKEND: {EMBED_BACKEND}")
