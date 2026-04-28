"""Unit tests cho orchestrator.coverage_gap_store – test persistence layer."""
from __future__ import annotations

import importlib
import time

import pytest


@pytest.fixture(autouse=True)
def _fresh_store(tmp_path, monkeypatch):
    """Mỗi test dùng DB riêng trong tmp_path."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))

    import config.settings as settings_mod
    importlib.reload(settings_mod)

    import orchestrator.coverage_gap_store as cgs
    cgs._initialised_paths.clear()
    importlib.reload(cgs)


def _store():
    """Import lại sau reload để lấy module đúng."""
    import orchestrator.coverage_gap_store as cgs
    return cgs


# ─── add_gap ─────────────────────────────────────────────────────────────────

def test_add_gap_returns_id():
    store = _store()
    gid = store.add_gap(question="What is Kubernetes?")
    assert isinstance(gid, int)
    assert gid > 0


def test_add_gap_with_all_fields():
    store = _store()
    gid = store.add_gap(
        question="How to deploy?",
        answer_excerpt="I don't have enough info...",
        retrieval_count=0,
        gap_signals=["no_retrieval", "fallback_answer"],
        citations_snapshot=[{"title": "K8s Guide", "url": "http://ex.com", "score": 0.2}],
        session_id="sess-1",
        message_id="msg-1",
        rewritten_query="how to deploy kubernetes pods",
        detected_topic="kubernetes",
        feedback_type="down",
    )
    record = store.get_gap(gid)
    assert record is not None
    assert record["question"] == "How to deploy?"
    assert record["answer_excerpt"] == "I don't have enough info..."
    assert record["retrieval_count"] == 0
    assert record["gap_signals"] == ["no_retrieval", "fallback_answer"]
    assert len(record["citations_snapshot"]) == 1
    assert record["session_id"] == "sess-1"
    assert record["message_id"] == "msg-1"
    assert record["rewritten_query"] == "how to deploy kubernetes pods"
    assert record["detected_topic"] == "kubernetes"
    assert record["feedback_type"] == "down"
    assert record["status"] == "new"
    assert record["resolution"] is None


def test_add_gap_empty_question_raises():
    store = _store()
    with pytest.raises(ValueError, match="empty"):
        store.add_gap(question="")


def test_add_gap_strips_whitespace():
    store = _store()
    gid = store.add_gap(
        question="  What is X?  ",
        session_id="  sid  ",
    )
    record = store.get_gap(gid)
    assert record["question"] == "What is X?"
    assert record["session_id"] == "sid"


def test_add_gap_sets_created_at():
    store = _store()
    before = time.time()
    gid = store.add_gap(question="Q")
    after = time.time()
    record = store.get_gap(gid)
    assert before <= record["created_at"] <= after


def test_add_gap_truncates_answer_excerpt():
    store = _store()
    long_answer = "A" * 1000
    gid = store.add_gap(question="Q", answer_excerpt=long_answer)
    record = store.get_gap(gid)
    assert len(record["answer_excerpt"]) <= 500


# ─── get_gap ─────────────────────────────────────────────────────────────────

def test_get_gap_not_found():
    store = _store()
    assert store.get_gap(999) is None


def test_get_gap_by_id():
    store = _store()
    gid = store.add_gap(question="Q")
    record = store.get_gap(gid)
    assert record["id"] == gid
    assert record["question"] == "Q"


# ─── list_gaps ───────────────────────────────────────────────────────────────

def test_list_gaps_empty():
    store = _store()
    items = store.list_gaps()
    assert items == []


def test_list_gaps_returns_all():
    store = _store()
    store.add_gap(question="Q1")
    store.add_gap(question="Q2")
    items = store.list_gaps()
    assert len(items) == 2


def test_list_gaps_new_first():
    """New gaps should appear before reviewed gaps."""
    store = _store()
    gid1 = store.add_gap(question="Q1")
    store.add_gap(question="Q2")
    store.review_gap(gid1, status="reviewed")
    items = store.list_gaps()
    assert items[0]["status"] == "new"
    assert items[1]["status"] == "reviewed"


def test_list_gaps_filter_by_status():
    store = _store()
    gid1 = store.add_gap(question="Q1")
    store.add_gap(question="Q2")
    store.review_gap(gid1, status="actioned")

    new_items = store.list_gaps(status="new")
    assert len(new_items) == 1
    assert new_items[0]["question"] == "Q2"

    actioned = store.list_gaps(status="actioned")
    assert len(actioned) == 1
    assert actioned[0]["question"] == "Q1"


def test_list_gaps_filter_by_topic():
    store = _store()
    store.add_gap(question="Q1", detected_topic="kubernetes")
    store.add_gap(question="Q2", detected_topic="docker")
    items = store.list_gaps(detected_topic="kubernetes")
    assert len(items) == 1
    assert items[0]["question"] == "Q1"


def test_list_gaps_filter_by_resolution():
    store = _store()
    gid1 = store.add_gap(question="Q1")
    store.add_gap(question="Q2")
    store.review_gap(gid1, status="actioned", resolution="add_source")

    items = store.list_gaps(resolution="add_source")
    assert len(items) == 1
    assert items[0]["question"] == "Q1"


def test_list_gaps_pagination():
    store = _store()
    for i in range(5):
        store.add_gap(question=f"Q{i}")
    items = store.list_gaps(limit=2)
    assert len(items) == 2
    items_offset = store.list_gaps(limit=2, offset=3)
    assert len(items_offset) == 2


# ─── review_gap ──────────────────────────────────────────────────────────────

def test_review_gap_basic():
    store = _store()
    gid = store.add_gap(question="Q")
    result = store.review_gap(gid, status="reviewed")
    assert result["status"] == "reviewed"
    assert result["reviewed_at"] is not None


def test_review_gap_with_resolution_and_note():
    store = _store()
    gid = store.add_gap(question="Q")
    result = store.review_gap(
        gid,
        status="actioned",
        resolution="add_source",
        review_note="Need to add K8s docs",
    )
    assert result["status"] == "actioned"
    assert result["resolution"] == "add_source"
    assert result["review_note"] == "Need to add K8s docs"


def test_review_gap_invalid_status_raises():
    store = _store()
    gid = store.add_gap(question="Q")
    with pytest.raises(ValueError, match="status"):
        store.review_gap(gid, status="invalid")


def test_review_gap_invalid_resolution_raises():
    store = _store()
    gid = store.add_gap(question="Q")
    with pytest.raises(ValueError, match="resolution"):
        store.review_gap(gid, resolution="invalid_res")


# ─── action_gap ──────────────────────────────────────────────────────────────

def test_action_gap_add_source():
    store = _store()
    gid = store.add_gap(question="Q", detected_topic="kubernetes")
    result = store.action_gap(
        gid,
        resolution="add_source",
        action_payload={"topic": "kubernetes", "url": "https://k8s.io/docs"},
        review_note="Added K8s docs",
    )
    assert result["status"] == "actioned"
    assert result["resolution"] == "add_source"
    assert result["action_payload"]["topic"] == "kubernetes"
    assert result["action_payload"]["url"] == "https://k8s.io/docs"
    assert result["actioned_at"] is not None
    assert result["reviewed_at"] is not None
    assert result["review_note"] == "Added K8s docs"


def test_action_gap_recrawl():
    store = _store()
    gid = store.add_gap(question="Q")
    result = store.action_gap(
        gid,
        resolution="recrawl",
        action_payload={"topic": "docker", "result": {"documents_crawled": 3}},
    )
    assert result["status"] == "actioned"
    assert result["resolution"] == "recrawl"
    assert result["action_payload"]["topic"] == "docker"
    assert result["actioned_at"] is not None


def test_action_gap_invalid_resolution_raises():
    store = _store()
    gid = store.add_gap(question="Q")
    with pytest.raises(ValueError, match="resolution"):
        store.action_gap(gid, resolution="out_of_scope")


def test_action_gap_empty_payload():
    store = _store()
    gid = store.add_gap(question="Q")
    result = store.action_gap(gid, resolution="add_source")
    assert result["action_payload"] == {}
    assert result["status"] == "actioned"


def test_action_gap_sets_timestamps():
    store = _store()
    gid = store.add_gap(question="Q")
    before = time.time()
    result = store.action_gap(gid, resolution="recrawl", action_payload={"topic": "t"})
    after = time.time()
    assert before <= result["actioned_at"] <= after
    assert before <= result["reviewed_at"] <= after


def test_action_gap_not_found_returns_none():
    store = _store()
    result = store.action_gap(999, resolution="add_source")
    assert result is None


# ─── new fields in dict ─────────────────────────────────────────────────────

def test_gap_dict_includes_action_fields():
    """Verify _row_to_dict includes action_payload and actioned_at."""
    store = _store()
    gid = store.add_gap(question="Q")
    record = store.get_gap(gid)
    assert "action_payload" in record
    assert "actioned_at" in record
    assert record["action_payload"] == {}
    assert record["actioned_at"] is None


# ─── count_summary ───────────────────────────────────────────────────────────

def test_count_summary_empty():
    store = _store()
    s = store.count_summary()
    assert s["total"] == 0
    assert s["total_new"] == 0
    assert s["by_topic"] == {}
    assert s["by_resolution"] == {}


def test_count_summary():
    store = _store()
    store.add_gap(question="Q1", detected_topic="kubernetes")
    gid2 = store.add_gap(question="Q2", detected_topic="kubernetes")
    gid3 = store.add_gap(question="Q3", detected_topic="docker")
    store.review_gap(gid2, status="actioned", resolution="add_source")
    store.review_gap(gid3, status="ignored", resolution="out_of_scope")

    s = store.count_summary()
    assert s["total"] == 3
    assert s["total_new"] == 1
    assert s["total_actioned"] == 1
    assert s["total_ignored"] == 1
    assert s["by_topic"]["kubernetes"] == 2
    assert s["by_topic"]["docker"] == 1
    assert s["by_resolution"]["add_source"] == 1
    assert s["by_resolution"]["out_of_scope"] == 1


# ─── JSON serialization ─────────────────────────────────────────────────────

def test_gap_signals_and_citations_roundtrip():
    store = _store()
    signals = ["no_retrieval", "fallback_answer"]
    citations = [{"title": "Doc A", "url": "http://a.com", "score": 0.5}]
    gid = store.add_gap(
        question="Q",
        gap_signals=signals,
        citations_snapshot=citations,
    )
    record = store.get_gap(gid)
    assert record["gap_signals"] == signals
    assert record["citations_snapshot"] == citations


# ─── cluster_key persistence ─────────────────────────────────────────────────

def test_add_gap_sets_cluster_key():
    store = _store()
    gid = store.add_gap(question="How to deploy pods?", detected_topic="kubernetes")
    record = store.get_gap(gid)
    assert record["cluster_key"] == "kubernetes:how to deploy pods"


def test_add_gap_cluster_key_uses_rewritten_query():
    store = _store()
    gid = store.add_gap(
        question="deploy?",
        rewritten_query="How to deploy Kubernetes pods?",
        detected_topic="kubernetes",
    )
    record = store.get_gap(gid)
    assert record["cluster_key"] == "kubernetes:how to deploy kubernetes pods"


def test_add_gap_cluster_key_no_topic():
    store = _store()
    gid = store.add_gap(question="What is Docker?")
    record = store.get_gap(gid)
    assert record["cluster_key"] == "what is docker"


def test_same_question_same_cluster_key():
    store = _store()
    gid1 = store.add_gap(question="How to deploy?", detected_topic="k8s")
    gid2 = store.add_gap(question="How to Deploy?", detected_topic="k8s")
    r1 = store.get_gap(gid1)
    r2 = store.get_gap(gid2)
    assert r1["cluster_key"] == r2["cluster_key"]


# ─── list_clusters ───────────────────────────────────────────────────────────

def test_list_clusters_empty():
    store = _store()
    clusters = store.list_clusters()
    assert clusters == []


def test_list_clusters_groups_duplicates():
    store = _store()
    store.add_gap(question="How to deploy pods?", detected_topic="kubernetes")
    store.add_gap(question="how to deploy pods", detected_topic="kubernetes")
    store.add_gap(question="How to Deploy Pods??", detected_topic="kubernetes")
    clusters = store.list_clusters()
    assert len(clusters) == 1
    assert clusters[0]["count"] == 3
    assert clusters[0]["detected_topic"] == "kubernetes"
    assert len(clusters[0]["sample_gap_ids"]) == 3


def test_list_clusters_sorted_by_count_desc():
    store = _store()
    # 2 gaps for cluster A
    store.add_gap(question="deploy pods", detected_topic="k8s")
    store.add_gap(question="deploy pods", detected_topic="k8s")
    # 3 gaps for cluster B
    store.add_gap(question="what is docker", detected_topic="docker")
    store.add_gap(question="what is docker", detected_topic="docker")
    store.add_gap(question="what is docker", detected_topic="docker")
    clusters = store.list_clusters()
    assert len(clusters) == 2
    assert clusters[0]["count"] == 3  # docker cluster first (higher count)
    assert clusters[1]["count"] == 2


def test_list_clusters_filter_by_topic():
    store = _store()
    store.add_gap(question="Q1", detected_topic="kubernetes")
    store.add_gap(question="Q2", detected_topic="docker")
    clusters = store.list_clusters(detected_topic="kubernetes")
    assert len(clusters) == 1
    assert clusters[0]["detected_topic"] == "kubernetes"


def test_list_clusters_filter_by_status():
    store = _store()
    gid1 = store.add_gap(question="Q1", detected_topic="k8s")
    store.add_gap(question="Q2", detected_topic="k8s")
    store.review_gap(gid1, status="actioned", resolution="add_source")
    # Filter by 'new' should return only the cluster for Q2
    clusters = store.list_clusters(status="new")
    assert len(clusters) == 1
    # Q2 is still new, Q1 is actioned (different cluster key though)
    assert clusters[0]["count"] == 1


def test_list_clusters_status_breakdown():
    store = _store()
    gid1 = store.add_gap(question="Deploy pods?", detected_topic="k8s")
    store.add_gap(question="Deploy pods!", detected_topic="k8s")
    store.review_gap(gid1, status="reviewed")
    clusters = store.list_clusters()
    assert len(clusters) == 1
    statuses = clusters[0]["statuses"]
    assert statuses.get("new") == 1
    assert statuses.get("reviewed") == 1


def test_list_clusters_resolution_breakdown():
    store = _store()
    gid1 = store.add_gap(question="Deploy pods", detected_topic="k8s")
    store.add_gap(question="Deploy pods", detected_topic="k8s")
    store.review_gap(gid1, status="actioned", resolution="add_source")
    clusters = store.list_clusters()
    assert clusters[0]["resolutions"].get("add_source") == 1


def test_list_clusters_pagination():
    store = _store()
    for i in range(5):
        store.add_gap(question=f"Unique question {i}", detected_topic="k8s")
    clusters = store.list_clusters(limit=2)
    assert len(clusters) == 2
    clusters_page2 = store.list_clusters(limit=2, offset=2)
    assert len(clusters_page2) == 2


def test_list_clusters_representative_question():
    store = _store()
    store.add_gap(question="How to deploy pods?", detected_topic="k8s")
    import time
    time.sleep(0.01)
    store.add_gap(question="How to Deploy Pods!", detected_topic="k8s")
    clusters = store.list_clusters()
    assert len(clusters) == 1
    # Representative should be from the newest gap
    assert clusters[0]["representative_question"] in (
        "How to deploy pods?", "How to Deploy Pods!",
    )


# ─── list_gaps_by_cluster ───────────────────────────────────────────────────

def test_list_gaps_by_cluster():
    store = _store()
    store.add_gap(question="Deploy pods?", detected_topic="k8s")
    store.add_gap(question="Deploy pods!", detected_topic="k8s")
    store.add_gap(question="What is docker?", detected_topic="docker")
    # Get the cluster key
    gap = store.get_gap(1)
    ck = gap["cluster_key"]
    gaps = store.list_gaps_by_cluster(ck)
    assert len(gaps) == 2
    assert all(g["cluster_key"] == ck for g in gaps)


def test_list_gaps_by_cluster_empty():
    store = _store()
    gaps = store.list_gaps_by_cluster("nonexistent_key")
    assert gaps == []


def test_list_gaps_by_cluster_pagination():
    store = _store()
    for _ in range(5):
        store.add_gap(question="Same question", detected_topic="t")
    gap = store.get_gap(1)
    ck = gap["cluster_key"]
    gaps = store.list_gaps_by_cluster(ck, limit=2)
    assert len(gaps) == 2
