"""Tests cho rag.generator helpers - không gọi LLM."""
from __future__ import annotations

from rag.generator import (
    _build_context,
    _is_context_relevant,
    _looks_like_garbage,
    _strip_diacritics,
    _tokenize,
    wants_citations,
)


# ─── wants_citations ────────────────────────────────────────────────────────
def test_wants_citations_negative():
    assert not wants_citations("Python là gì?")
    assert not wants_citations("Docker compose dùng để làm gì")
    assert not wants_citations("")


def test_wants_citations_positive_no_diacritics():
    assert wants_citations("cho minh nguon")
    assert wants_citations("trich dan o dau")


def test_wants_citations_positive_with_diacritics():
    assert wants_citations("Python là gì? cho mình nguồn")
    assert wants_citations("hãy đưa trích dẫn")
    assert wants_citations("cho tôi tham khảo tài liệu")


def test_wants_citations_english():
    assert wants_citations("show me sources")
    assert wants_citations("any citations?")


# ─── _strip_diacritics ──────────────────────────────────────────────────────
def test_strip_diacritics_handles_d_stroke():
    assert _strip_diacritics("đường") == "duong"
    assert _strip_diacritics("Đà Nẵng") == "Da Nang"


def test_strip_diacritics_idempotent_for_ascii():
    assert _strip_diacritics("hello world") == "hello world"


# ─── _tokenize ───────────────────────────────────────────────────────────────
def test_tokenize_filters_stopwords_and_short():
    tokens = _tokenize("RBAC là một cơ chế phân quyền")
    assert "rbac" in tokens
    # 1-char tokens phải bị filter
    assert all(len(t) >= 2 for t in tokens)


# ─── _is_context_relevant ───────────────────────────────────────────────────
def test_relevant_when_overlap_exists(fake_chunks):
    assert _is_context_relevant("Pod là gì?", fake_chunks)


def test_irrelevant_when_no_overlap(fake_chunks):
    # query về Ronaldo nhưng context toàn k8s
    assert not _is_context_relevant("Ronaldo ghi bao nhieu ban thang", fake_chunks)


def test_relevant_returns_true_for_empty_query():
    """Edge case: query rỗng → coi như relevant để không block."""
    assert _is_context_relevant("", [{"content": "x", "metadata": {}}])


# ─── _build_context ─────────────────────────────────────────────────────────
def test_build_context_includes_title_and_url(fake_chunks):
    ctx = _build_context(fake_chunks)
    assert "K8s Pod" in ctx
    assert "K8s Deployment" in ctx
    assert "u1" in ctx


def test_build_context_truncates_long_content():
    # default max_context_chars = 600 → content 5000 chars phải bị cắt
    chunks = [{"content": "A" * 5000, "metadata": {"title": "T"}}]
    ctx = _build_context(chunks)
    assert "..." in ctx
    assert len(ctx) < 5000


# ─── _looks_like_garbage ─────────────────────────────────────────────────────
def test_garbage_detects_prompt_leak():
    leak = "Theo khuyến nghị 1, 2, 3 hay 4, không nên bắt đầu..."
    assert _looks_like_garbage(leak)


def test_garbage_detects_too_short():
    assert _looks_like_garbage("ok")
    assert _looks_like_garbage("...")


def test_garbage_clean_answer_passes():
    clean = "Python là một ngôn ngữ lập trình thông dịch, đa nhiệm, được phát triển bởi Guido van Rossum."
    assert not _looks_like_garbage(clean)


def test_garbage_detects_context_marker_echo():
    leak = "=== context === something here"
    assert _looks_like_garbage(leak)
