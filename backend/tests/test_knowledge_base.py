from app.knowledge_base import rank_chunks, split_chunks


def test_chunking_is_deterministic_and_overlapping():
    text = "abcdefghijklmnopqrstuvwxyz"
    chunks = split_chunks(text, size=10, overlap=3)
    assert chunks == ["abcdefghij", "hijklmnopq", "opqrstuvwx", "vwxyz"]


def test_rank_chunks_prefers_term_overlap():
    chunks = [
        {"source_type": "profile", "source_id": "u1", "chunk_index": 0, "text": "name Rahul email rahul@example.com", "metadata": {}},
        {"source_type": "education", "source_id": "e1", "chunk_index": 0, "text": "qualification MBBS institution ABC", "metadata": {}},
    ]
    results = rank_chunks("Rahul email", chunks, top_k=1)
    assert len(results) == 1
    assert results[0]["source_type"] == "profile"
    assert results[0]["score"] == 1.0


def test_empty_query_returns_no_results():
    assert rank_chunks("   ", [{"text": "anything", "chunk_index": 0}], 5) == []


def test_top_k_is_respected():
    chunks = [{"text": "alpha beta", "chunk_index": i} for i in range(5)]
    assert len(rank_chunks("alpha", chunks, 2)) == 2
