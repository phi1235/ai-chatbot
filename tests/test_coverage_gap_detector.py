"""Unit tests cho orchestrator.coverage_gap_detector – heuristic detection."""
from __future__ import annotations

import importlib

import pytest

from orchestrator.coverage_gap_detector import detect, maybe_persist_gap

# ─── detect() pure heuristic ────────────────────────────────────────────────

def test_no_retrieval():
    signals = detect(retrieval_count=0)
    assert "no_retrieval" in signals


def test_low_retrieval_not_triggered_at_threshold():
    """retrieval_count == MIN_RETRIEVAL_COUNT should NOT trigger low_retrieval."""
    signals = detect(retrieval_count=1, citations=[{"title": "A", "url": "u", "score": 0.9}])
    assert "low_retrieval" not in signals
    assert "no_retrieval" not in signals


def test_no_citations_separate_from_no_retrieval():
    """retrieval_count > 0 but empty citations → no_citations."""
    signals = detect(retrieval_count=2, citations=[])
    assert "no_citations" in signals
    assert "no_retrieval" not in signals


def test_no_citations_not_duplicated_with_no_retrieval():
    """If retrieval_count == 0, we get no_retrieval but not no_citations."""
    signals = detect(retrieval_count=0, citations=[])
    assert "no_retrieval" in signals
    assert "no_citations" not in signals


def test_low_citation_scores():
    citations = [
        {"title": "A", "url": "u1", "score": 0.1},
        {"title": "B", "url": "u2", "score": 0.2},
    ]
    signals = detect(retrieval_count=2, citations=citations)
    assert "low_citation_scores" in signals


def test_mixed_citation_scores_no_flag():
    """If any score is above threshold, don't flag."""
    citations = [
        {"title": "A", "url": "u1", "score": 0.1},
        {"title": "B", "url": "u2", "score": 0.8},
    ]
    signals = detect(retrieval_count=2, citations=citations)
    assert "low_citation_scores" not in signals


def test_citations_without_scores_no_flag():
    """If citations have no score field, don't flag low_citation_scores."""
    citations = [
        {"title": "A", "url": "u1"},
        {"title": "B", "url": "u2"},
    ]
    signals = detect(retrieval_count=2, citations=citations)
    assert "low_citation_scores" not in signals


def test_fallback_answer_detected():
    answer = "Hiện tại tôi chưa tìm thấy thông tin đủ liên quan trong kho tri thức."
    signals = detect(retrieval_count=0, answer=answer)
    assert "fallback_answer" in signals


def test_no_context_message_detected():
    answer = "Hiện tại tôi chưa tìm thấy thông tin phù hợp trong kho tri thức."
    signals = detect(retrieval_count=0, answer=answer)
    assert "fallback_answer" in signals


def test_normal_answer_no_fallback():
    answer = "Kubernetes là một container orchestration platform."
    signals = detect(
        retrieval_count=3,
        citations=[{"title": "K8s", "url": "u1", "score": 0.9}],
        answer=answer,
    )
    assert "fallback_answer" not in signals


def test_no_signals_for_good_response():
    """A well-retrieved, well-cited response should trigger zero signals."""
    signals = detect(
        retrieval_count=3,
        citations=[
            {"title": "A", "url": "u1", "score": 0.9},
            {"title": "B", "url": "u2", "score": 0.8},
        ],
        answer="Kubernetes Pod là đơn vị nhỏ nhất...",
    )
    assert signals == []


def test_multiple_signals_combined():
    """A truly bad response can trigger multiple signals at once."""
    answer = "Tôi chưa tìm thấy thông tin đủ liên quan để trả lời."
    signals = detect(retrieval_count=0, citations=[], answer=answer)
    assert "no_retrieval" in signals
    assert "fallback_answer" in signals


# ─── maybe_persist_gap() integration ────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fresh_store(tmp_path, monkeypatch):
    """Mỗi test dùng DB riêng."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))

    import config.settings as settings_mod
    importlib.reload(settings_mod)

    import orchestrator.coverage_gap_store as cgs
    cgs._initialised_paths.clear()
    importlib.reload(cgs)


def test_maybe_persist_gap_returns_id_when_gap():
    gid = maybe_persist_gap(
        question="How to deploy?",
        answer="Tôi chưa tìm thấy thông tin đủ liên quan.",
        retrieval_count=0,
        citations=[],
        session_id="sess-1",
        detected_topic="kubernetes",
    )
    assert isinstance(gid, int)
    assert gid > 0


def test_maybe_persist_gap_returns_none_when_no_gap():
    gid = maybe_persist_gap(
        question="What is K8s?",
        answer="Kubernetes là container orchestration platform.",
        retrieval_count=3,
        citations=[{"title": "K8s", "url": "u1", "score": 0.9}],
    )
    assert gid is None


def test_maybe_persist_gap_stores_signals_and_citations():
    import orchestrator.coverage_gap_store as cgs

    gid = maybe_persist_gap(
        question="Q?",
        answer="fallback",
        retrieval_count=0,
        citations=[{"title": "A", "url": "u", "score": 0.1}],
        session_id="s",
        rewritten_query="rq",
        detected_topic="topic",
    )
    assert gid is not None
    record = cgs.get_gap(gid)
    assert "no_retrieval" in record["gap_signals"]
    assert record["detected_topic"] == "topic"
    assert record["rewritten_query"] == "rq"
    # Citations snapshot should only have title/url/score
    assert record["citations_snapshot"][0]["title"] == "A"
