"""Unit tests cho orchestrator.coverage_gap_cluster – normalize + cluster key."""
from __future__ import annotations

from orchestrator.coverage_gap_cluster import make_cluster_key, normalize_text

# ─── normalize_text ──────────────────────────────────────────────────────────

class TestNormalizeText:
    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_none_like(self):
        assert normalize_text("") == ""

    def test_lowercase(self):
        assert normalize_text("How To Deploy") == "how to deploy"

    def test_strips_whitespace(self):
        assert normalize_text("  hello world  ") == "hello world"

    def test_removes_punctuation(self):
        assert normalize_text("hello? world! foo.") == "hello world foo"

    def test_collapses_spaces(self):
        assert normalize_text("hello   world    foo") == "hello world foo"

    def test_combined(self):
        assert normalize_text("  How to deploy  Kubernetes pods??  ") == "how to deploy kubernetes pods"

    def test_unicode_preserved(self):
        # Vietnamese diacritics should be preserved
        assert normalize_text("Làm sao để deploy?") == "làm sao để deploy"

    def test_punctuation_mix(self):
        assert normalize_text("what's the cost (total)?") == "what s the cost total"

    def test_numbers_preserved(self):
        assert normalize_text("K8s version 1.28!") == "k8s version 1 28"


# ─── make_cluster_key ────────────────────────────────────────────────────────

class TestMakeClusterKey:
    def test_question_only(self):
        key = make_cluster_key(question="How to deploy pods?")
        assert key == "how to deploy pods"

    def test_rewritten_query_preferred(self):
        key = make_cluster_key(
            question="deploy?",
            rewritten_query="How to deploy Kubernetes pods?",
        )
        assert key == "how to deploy kubernetes pods"

    def test_topic_prefix(self):
        key = make_cluster_key(
            question="How to deploy pods?",
            detected_topic="kubernetes",
        )
        assert key == "kubernetes:how to deploy pods"

    def test_topic_prefix_with_rewritten_query(self):
        key = make_cluster_key(
            question="Q",
            rewritten_query="How to deploy K8s pods?",
            detected_topic="kubernetes",
        )
        assert key == "kubernetes:how to deploy k8s pods"

    def test_topic_is_lowercased(self):
        key = make_cluster_key(
            question="foo",
            detected_topic="Kubernetes",
        )
        assert key == "kubernetes:foo"

    def test_empty_topic_no_prefix(self):
        key = make_cluster_key(
            question="foo",
            detected_topic="",
        )
        assert key == "foo"

    def test_none_topic_no_prefix(self):
        key = make_cluster_key(
            question="foo",
            detected_topic=None,
        )
        assert key == "foo"

    def test_empty_rewritten_query_falls_back(self):
        key = make_cluster_key(
            question="How to deploy?",
            rewritten_query="",
        )
        assert key == "how to deploy"

    def test_whitespace_rewritten_query_falls_back(self):
        key = make_cluster_key(
            question="How to deploy?",
            rewritten_query="   ",
        )
        assert key == "how to deploy"


# ─── Stability / dedup properties ────────────────────────────────────────────

class TestClusterKeyStability:
    """Same-meaning questions produce the same cluster key."""

    def test_case_insensitive(self):
        a = make_cluster_key(question="How to Deploy Pods?")
        b = make_cluster_key(question="how to deploy pods?")
        assert a == b

    def test_punctuation_insensitive(self):
        a = make_cluster_key(question="How to deploy pods?")
        b = make_cluster_key(question="How to deploy pods")
        assert a == b

    def test_extra_whitespace_insensitive(self):
        a = make_cluster_key(question="How to deploy pods?")
        b = make_cluster_key(question="  How  to  deploy  pods?  ")
        assert a == b

    def test_different_topics_different_keys(self):
        a = make_cluster_key(question="How to deploy?", detected_topic="kubernetes")
        b = make_cluster_key(question="How to deploy?", detected_topic="docker")
        assert a != b

    def test_same_question_same_topic_same_key(self):
        a = make_cluster_key(question="How to deploy?", detected_topic="k8s")
        b = make_cluster_key(question="How to deploy?", detected_topic="k8s")
        assert a == b
