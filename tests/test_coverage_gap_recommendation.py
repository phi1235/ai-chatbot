from __future__ import annotations

from orchestrator.coverage_gap_recommendation import (
    get_topic_source_context,
    recommend_for_cluster,
)


def test_get_topic_source_context_counts_sources(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "kubernetes.json").write_text(
        '[{"url":"https://k8s.io/a"},{"url":"https://k8s.io/b"}]',
        encoding="utf-8",
    )
    (sources / "docker.json").write_text('[]', encoding="utf-8")

    ctx = get_topic_source_context(sources)
    assert ctx == {"kubernetes": 2, "docker": 0}


def test_recommend_add_source_when_topic_has_no_sources():
    cluster = {
        "cluster_key": "kubernetes:statefulset vs deployment",
        "representative_question": "StatefulSet khác Deployment như nào?",
        "detected_topic": "kubernetes",
        "count": 4,
        "statuses": {"new": 4},
        "resolutions": {},
    }

    rec = recommend_for_cluster(cluster, {})
    assert rec["recommended_action"] == "add_source"
    assert rec["candidate_topic"] == "kubernetes"
    assert rec["priority"] in {"medium", "high"}
    assert "topic_no_sources" in rec["signals"]
    assert "official docs" in rec["suggested_search_query"]


def test_recommend_add_source_when_topic_sources_are_thin():
    cluster = {
        "cluster_key": "kubernetes:statefulset vs deployment",
        "representative_question": "StatefulSet vs Deployment",
        "detected_topic": "kubernetes",
        "count": 3,
        "statuses": {"new": 3},
        "resolutions": {},
    }

    rec = recommend_for_cluster(cluster, {"kubernetes": 1})
    assert rec["recommended_action"] == "add_source"
    assert "topic_sources_thin" in rec["signals"]


def test_recommend_recrawl_when_topic_has_enough_sources_but_repeats():
    cluster = {
        "cluster_key": "kubernetes:deployment strategy",
        "representative_question": "Deployment strategy rollout?",
        "detected_topic": "kubernetes",
        "count": 2,
        "statuses": {"new": 2},
        "resolutions": {},
    }

    rec = recommend_for_cluster(cluster, {"kubernetes": 4})
    assert rec["recommended_action"] == "recrawl"
    assert rec["candidate_topic"] == "kubernetes"
    assert "topic_has_sources" in rec["signals"]


def test_recommend_review_only_when_signal_is_weak():
    cluster = {
        "cluster_key": "what is grpc",
        "representative_question": "What is gRPC?",
        "detected_topic": "",
        "count": 1,
        "statuses": {"new": 1},
        "resolutions": {},
    }

    rec = recommend_for_cluster(cluster, {})
    assert rec["recommended_action"] == "review_only"
    assert rec["priority"] == "low"
    assert rec["candidate_topic"] == ""


def test_recommend_add_source_when_topic_unknown_but_high_repetition():
    cluster = {
        "cluster_key": "strange repeated query",
        "representative_question": "strange repeated query",
        "detected_topic": "",
        "count": 5,
        "statuses": {"new": 5},
        "resolutions": {},
    }

    rec = recommend_for_cluster(cluster, {})
    assert rec["recommended_action"] == "add_source"
    assert rec["priority"] == "high"


def test_search_query_prefers_representative_question():
    cluster = {
        "cluster_key": "kubernetes:deployment strategy",
        "representative_question": "How to choose a deployment strategy?",
        "detected_topic": "kubernetes",
        "count": 3,
        "statuses": {"new": 3},
        "resolutions": {},
    }

    rec = recommend_for_cluster(cluster, {"kubernetes": 2})
    assert rec["suggested_search_query"].startswith("kubernetes How to choose a deployment strategy?")
