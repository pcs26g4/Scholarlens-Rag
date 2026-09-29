import pytest
from retrieval.retriever import retrieve_similar_questions

@pytest.mark.usefixtures("ensure_populated_qdrant")
def test_retrieve_returns_top_k(sample_qa_df):
    first_q = sample_qa_df.iloc[0]["question_text"]
    results = retrieve_similar_questions(first_q, top_k=2)
    assert isinstance(results, list)
    assert len(results) == 2
    for r in results:
        assert "question_text" in r
        assert "answer_text" in r
        assert "subject" in r
        assert "similarity" in r
        assert 0 <= float(r["similarity"]) <= 1.0

@pytest.mark.usefixtures("ensure_populated_qdrant")
def test_embedding_uses_question_only(sample_qa_df, monkeypatch):
    # Patch the embedder to check text
    import retrieval.retriever as retr
    called = {}
    def fake_embed(text):
        called['last'] = text
        return [0.0]*retr.retrieval_dim
    monkeypatch.setattr(retr.embedder, "get_text_embedding", fake_embed)
    q = sample_qa_df.iloc[1]["question_text"]
    retrieve_similar_questions(q, top_k=2)
    assert called['last'] == q