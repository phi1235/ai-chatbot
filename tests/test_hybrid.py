"""Tests cho rag.hybrid - BM25 tokenize, BM25Index search, RRF fusion."""
from __future__ import annotations

from rank_bm25 import BM25Okapi

from rag.hybrid import (
    BM25Index,
    IndexedChunk,
    _chunk_key,
    rrf_fuse,
    tokenize,
)


# ─── tokenize ────────────────────────────────────────────────────────────────
def test_tokenize_lowercase_and_strip_diacritics():
    tokens = tokenize("Pod là gì?")
    # "la" và "gi" là stopword; "pod" giữ lại
    assert "pod" in tokens
    assert "là" not in tokens
    assert "la" not in tokens  # stopword


def test_tokenize_keeps_camelcase_intact():
    """useState phải được giữ nguyên (không tách use + state)."""
    tokens = tokenize("Hook useState dùng khi nào?")
    assert "usestate" in tokens
    assert "hook" in tokens


def test_tokenize_keeps_version_numbers():
    """v1.2.3 / 3.1.1 phải được giữ làm 1 token để match exact."""
    tokens = tokenize("Spring Boot 3.1.1 có @Transactional")
    assert any("3.1.1" in t for t in tokens)
    assert "spring" in tokens
    assert "boot" in tokens


def test_tokenize_keeps_underscored_terms():
    tokens = tokenize("Hàm get_user_id trả về gì?")
    assert "get_user_id" in tokens


def test_tokenize_handles_diacritics_consistently():
    """nguồn = nguon → cùng token."""
    a = tokenize("nguồn tham khảo")
    b = tokenize("nguon tham khao")
    assert a == b


def test_tokenize_filters_short_tokens():
    tokens = tokenize("a b ab abc")
    assert "a" not in tokens
    assert "b" not in tokens
    assert "ab" in tokens or "abc" in tokens


def test_tokenize_empty_returns_empty():
    assert tokenize("") == []
    assert tokenize("    ") == []


# ─── BM25Index ───────────────────────────────────────────────────────────────
def _make_index_from_corpus(corpus: list[tuple[str, dict]]) -> BM25Index:
    chunks = [IndexedChunk(content=c, metadata=m, tokens=tokenize(c)) for c, m in corpus]
    bm25 = BM25Okapi([c.tokens for c in chunks])
    return BM25Index(chunks=chunks, bm25=bm25)


def test_bm25_search_returns_keyword_match():
    corpus = [
        ("Pod là đơn vị nhỏ nhất trong Kubernetes", {"topic": "kubernetes", "url": "u1"}),
        ("Deployment quản lý ReplicaSet", {"topic": "kubernetes", "url": "u2"}),
        ("React useState là một hook", {"topic": "react", "url": "u3"}),
    ]
    idx = _make_index_from_corpus(corpus)
    results = idx.search("useState hook", top_k=2)
    assert len(results) >= 1
    # Top result phải là chunk về useState
    assert "useState" in results[0]["content"]


def test_bm25_search_filters_by_topic():
    corpus = [
        ("Pod là đơn vị nhỏ nhất", {"topic": "kubernetes", "url": "u1"}),
        ("React useState hook", {"topic": "react", "url": "u3"}),
        ("Pod trong React", {"topic": "react", "url": "u4"}),
    ]
    idx = _make_index_from_corpus(corpus)
    results = idx.search("Pod", top_k=5, topic="kubernetes")
    # Chỉ chunk topic=kubernetes được trả
    assert all(r["metadata"].get("topic") == "kubernetes" for r in results)


def test_bm25_empty_query_returns_empty():
    corpus = [("Pod K8s", {"topic": "k8s"})]
    idx = _make_index_from_corpus(corpus)
    assert idx.search("", top_k=3) == []


def test_bm25_empty_index_returns_empty():
    idx = BM25Index.empty()
    assert not idx.is_ready()
    assert idx.search("anything", top_k=3) == []


def test_bm25_zero_score_filtered():
    """Nếu score = 0 (không có overlap token nào) thì không trả về."""
    corpus = [("Docker container", {"topic": "docker"})]
    idx = _make_index_from_corpus(corpus)
    # Query hoàn toàn không liên quan
    results = idx.search("xyzqwerty kubernetes", top_k=3)
    # Có thể có kubernetes match một chunk nào đó - test an toàn:
    # Chỉ assert: nếu có result, score > 0
    for r in results:
        assert r["bm25_score"] > 0


# ─── RRF fusion ──────────────────────────────────────────────────────────────
def test_rrf_merges_two_rankings():
    a = [
        {"content": "doc-A", "metadata": {"url": "uA"}},
        {"content": "doc-B", "metadata": {"url": "uB"}},
        {"content": "doc-C", "metadata": {"url": "uC"}},
    ]
    b = [
        {"content": "doc-B", "metadata": {"url": "uB"}},
        {"content": "doc-C", "metadata": {"url": "uC"}},
        {"content": "doc-D", "metadata": {"url": "uD"}},
    ]
    fused = rrf_fuse([a, b], top_k=3)
    urls = [c["metadata"]["url"] for c in fused]
    # B và C xuất hiện ở cả 2 ranking → điểm cao nhất, lên top
    assert "uB" in urls
    assert "uC" in urls
    assert urls[0] in {"uB", "uC"}


def test_rrf_doc_in_one_source_only():
    """Doc chỉ có trong 1 nguồn vẫn được trả nếu rank cao."""
    a = [{"content": "only-A", "metadata": {"url": "uA"}}]
    b = [{"content": "only-B", "metadata": {"url": "uB"}}]
    fused = rrf_fuse([a, b], top_k=2)
    assert len(fused) == 2


def test_rrf_top_k_limits_results():
    a = [{"content": f"d{i}", "metadata": {"url": f"u{i}"}} for i in range(10)]
    b = [{"content": f"d{i}", "metadata": {"url": f"u{i}"}} for i in range(10)]
    fused = rrf_fuse([a, b], top_k=3)
    assert len(fused) == 3


def test_rrf_score_decreases_with_rank():
    a = [
        {"content": "first", "metadata": {"url": "u1"}},
        {"content": "second", "metadata": {"url": "u2"}},
    ]
    fused = rrf_fuse([a], top_k=2)
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"]


def test_rrf_empty_input():
    assert rrf_fuse([], top_k=3) == []
    assert rrf_fuse([[]], top_k=3) == []


# ─── _chunk_key ──────────────────────────────────────────────────────────────
def test_chunk_key_uses_url_section():
    c1 = {"content": "x", "metadata": {"url": "u1", "section": "s1"}}
    c2 = {"content": "y", "metadata": {"url": "u1", "section": "s1"}}
    # Cùng url + section → cùng key (dedupe trong RRF)
    assert _chunk_key(c1) == _chunk_key(c2)


def test_chunk_key_falls_back_to_content():
    c = {"content": "some content", "metadata": {}}
    key = _chunk_key(c)
    assert "some content" in key
