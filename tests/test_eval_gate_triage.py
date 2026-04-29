"""Tests for eval gate triage module and API endpoints.

Covers:
- classify_regression: all outcome combinations
- suggest_next_action: known and unknown root causes
- get_gate_run_triage: structure, no-baseline, with-baseline
- filter_triage_items: each filter dimension
- GET /admin/eval-gates/runs/{run_id}/triage: 404, structure, items
- GET /admin/eval-gates/runs/{run_id}/items: 404, filters, invalid params
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from orchestrator.eval_gate_triage import (
    classify_regression,
    filter_triage_items,
    suggest_next_action,
)

# ─── Unit: classify_regression ───────────────────────────────────────────────


class TestClassifyRegression:
    def test_no_baseline_fail(self):
        assert classify_regression("none", "fail") == "new_fail"

    def test_no_baseline_error(self):
        assert classify_regression("none", "error") == "new_error"

    def test_no_baseline_pass(self):
        assert classify_regression("none", "pass") == "still_pass"

    def test_baseline_pass_candidate_fail(self):
        assert classify_regression("pass", "fail") == "new_fail"

    def test_baseline_pass_candidate_error(self):
        assert classify_regression("pass", "error") == "new_error"

    def test_baseline_pass_candidate_pass(self):
        assert classify_regression("pass", "pass") == "still_pass"

    def test_baseline_fail_candidate_fail(self):
        assert classify_regression("fail", "fail") == "still_fail"

    def test_baseline_fail_candidate_error(self):
        assert classify_regression("fail", "error") == "new_error"

    def test_baseline_fail_candidate_pass(self):
        assert classify_regression("fail", "pass") == "improved"

    def test_baseline_error_candidate_pass(self):
        assert classify_regression("error", "pass") == "improved"

    def test_baseline_error_candidate_fail(self):
        assert classify_regression("error", "fail") == "still_fail"

    def test_baseline_error_candidate_error(self):
        assert classify_regression("error", "error") == "still_error"


class TestSuggestNextAction:
    def test_known_root_cause_retrieval_miss(self):
        suggestion = suggest_next_action("retrieval_miss")
        assert suggestion
        assert "retrieval" in suggestion.lower() or "crawl" in suggestion.lower()

    def test_known_root_cause_true_coverage_gap(self):
        suggestion = suggest_next_action("true_coverage_gap")
        assert suggestion
        assert "source" in suggestion.lower() or "coverage" in suggestion.lower()

    def test_unknown_root_cause_returns_fallback(self):
        suggestion = suggest_next_action("made_up_cause")
        assert suggestion
        assert len(suggestion) > 10

    def test_none_root_cause_returns_fallback(self):
        suggestion = suggest_next_action(None)
        assert suggestion
        assert len(suggestion) > 10


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """Isolated DB + fresh module state for each test."""
    sources = tmp_path / "sources"
    sources.mkdir()
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.chdir(tmp_path)

    import config.settings as settings_mod
    importlib.reload(settings_mod)
    import orchestrator.store as store_mod
    importlib.reload(store_mod)
    import orchestrator.feedback_store as fb_mod
    fb_mod._initialised_paths.clear()
    importlib.reload(fb_mod)
    import orchestrator.freshness_store as fs_mod
    fs_mod._initialised_paths.clear()
    importlib.reload(fs_mod)
    import orchestrator.eval_case_store as ecs_mod
    ecs_mod._initialised_paths.clear()
    importlib.reload(ecs_mod)
    import orchestrator.eval_gate_store as gs_mod
    gs_mod._initialised_paths.clear()
    importlib.reload(gs_mod)
    import api.admin as admin_mod
    importlib.reload(admin_mod)

    from api.main import app
    return TestClient(app)


# ─── Test helpers ─────────────────────────────────────────────────────────────

def _create_reviewed_feedback(client, *, root_cause="retrieval_miss", topic="kubernetes"):
    r = client.post("/feedback", json={
        "question": "How to deploy pods?",
        "answer": "Use kubectl.",
        "feedback_type": "down",
        "detected_topic": topic,
        "rewritten_query": "deploy kubernetes pods",
        "retrieval_count": 2,
        "citations_snapshot": [{"title": "K8s docs", "url": "https://k8s.io"}],
        "trace_snapshot": {"request_id": "r1"},
    })
    fb_id = r.json()["id"]
    client.post(f"/admin/feedback/{fb_id}/review", json={
        "review_status": "reviewed",
        "root_cause": root_cause,
    })
    return fb_id


def _create_eval_case(client, feedback_id: int):
    return client.post(f"/admin/feedback/{feedback_id}/eval-case")


def _mock_rag_pass():
    from schemas.chat import Citation
    mock = MagicMock()
    mock.answer = "Kubernetes is a container orchestration platform."
    mock.detected_topic = "kubernetes"
    mock.retrieval_count = 3
    mock.citations = [Citation(title="K8s docs", url="https://k8s.io")]
    return mock


def _mock_rag_fail():
    mock = MagicMock()
    mock.answer = "hiện tại tôi chưa tìm thấy thông tin"
    mock.detected_topic = "kubernetes"
    mock.retrieval_count = 0
    mock.citations = []
    return mock


def _setup_eval_case(client) -> int:
    fb_id = _create_reviewed_feedback(client)
    return _create_eval_case(client, fb_id).json()["id"]


def _create_gate_config(client, **kwargs) -> dict:
    payload = {"name": "triage-test-gate", "kind": "nightly", **kwargs}
    r = client.post("/admin/eval-gates/configs", json=payload)
    assert r.status_code == 200, r.json()
    return r.json()


def _run_gate(client, config_id: int, mock_rag=None) -> dict:
    mock = mock_rag or _mock_rag_pass()
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=mock):
        r = client.post(f"/admin/eval-gates/configs/{config_id}/run", json={})
    assert r.status_code == 200
    return r.json()


# ─── Triage API: 404 on missing run ──────────────────────────────────────────

def test_triage_run_not_found(client):
    r = client.get("/admin/eval-gates/runs/9999/triage")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_triage_items_run_not_found(client):
    r = client.get("/admin/eval-gates/runs/9999/items")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


# ─── Triage: no-baseline run ─────────────────────────────────────────────────

def test_triage_no_baseline_run(client):
    """First gate run has no baseline → decision=no_baseline; items still present."""
    _setup_eval_case(client)
    cfg = _create_gate_config(client)
    gate_run = _run_gate(client, cfg["id"])
    assert gate_run["decision"] == "no_baseline"
    run_id = gate_run["id"]

    r = client.get(f"/admin/eval-gates/runs/{run_id}/triage")
    assert r.status_code == 200
    data = r.json()

    # Top-level keys present
    assert "gate_run" in data
    assert "config" in data
    assert "candidate_batch" in data
    assert "baseline_batch" in data
    assert "decision_summary" in data
    assert "items" in data

    # Gate run matches
    assert data["gate_run"]["id"] == run_id
    assert data["gate_run"]["decision"] == "no_baseline"

    # Config present
    assert data["config"]["id"] == cfg["id"]
    assert data["config"]["name"] == cfg["name"]

    # Candidate batch present; baseline absent
    assert data["candidate_batch"] is not None
    assert data["baseline_batch"] is None

    # Decision summary
    ds = data["decision_summary"]
    assert ds["decision"] == "no_baseline"
    assert ds["has_baseline"] is False

    # Items: one case was run; baseline_outcome should be "none" since no baseline
    items = data["items"]
    assert len(items) == 1
    item = items[0]
    assert item["baseline_outcome"] == "none"
    # First run with passing mock → candidate_outcome = pass (retrieval_miss expects retrieval ≥ 1)
    assert item["candidate_outcome"] in ("pass", "fail")
    # regression_class derived from no-baseline + candidate_outcome
    assert item["regression_class"] in ("new_fail", "new_error", "still_pass")
    # Question populated from eval case
    assert "deploy" in (item.get("question") or "").lower()


# ─── Triage: run with baseline ────────────────────────────────────────────────

def test_triage_with_baseline_classification(client):
    """Two gate runs: second has a baseline; regression classification reflects pass→fail."""
    fb1 = _create_reviewed_feedback(client, root_cause="retrieval_miss", topic="kubernetes")
    _create_eval_case(client, fb1)

    cfg = _create_gate_config(
        client,
        name="triage-gate-2run",
        baseline_mode="previous_gate_run",
        max_pass_rate_drop=0.05,
    )

    # First run: case passes → no_baseline
    _run_gate(client, cfg["id"], mock_rag=_mock_rag_pass())

    # Second run: case fails → baseline was pass → new_fail
    second_run = _run_gate(client, cfg["id"], mock_rag=_mock_rag_fail())
    run_id = second_run["id"]

    r = client.get(f"/admin/eval-gates/runs/{run_id}/triage")
    assert r.status_code == 200
    data = r.json()

    assert data["baseline_batch"] is not None
    assert data["decision_summary"]["has_baseline"] is True

    items = data["items"]
    assert len(items) == 1
    item = items[0]

    # Candidate should fail (fallback answer triggers should_not_fallback check)
    assert item["candidate_outcome"] == "fail"
    # Baseline passed
    assert item["baseline_outcome"] == "pass"
    # Classification should be new_fail
    assert item["regression_class"] == "new_fail"

    # Candidate detail populated
    assert item.get("failure_reason") is not None
    assert "should_not_fallback" in item["failure_reason"]


# ─── Triage: items structure ──────────────────────────────────────────────────

def test_triage_item_fields_complete(client):
    """Each triage item has all required fields."""
    _setup_eval_case(client)
    cfg = _create_gate_config(client, name="triage-fields")
    gate_run = _run_gate(client, cfg["id"])
    run_id = gate_run["id"]

    r = client.get(f"/admin/eval-gates/runs/{run_id}/triage")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1

    required_fields = {
        "eval_case_id", "question", "expected_topic", "root_cause",
        "candidate_outcome", "baseline_outcome", "regression_class",
        "failure_reason", "answer_excerpt", "citations_count", "retrieval_count",
    }
    for item in items:
        missing = required_fields - set(item.keys())
        assert not missing, f"Item missing fields: {missing}"


# ─── /items endpoint ──────────────────────────────────────────────────────────

def test_items_endpoint_returns_all_items(client):
    _setup_eval_case(client)
    cfg = _create_gate_config(client, name="items-all")
    gate_run = _run_gate(client, cfg["id"])
    run_id = gate_run["id"]

    r = client.get(f"/admin/eval-gates/runs/{run_id}/items")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total_items" in data
    assert "filtered_count" in data
    assert data["run_id"] == run_id
    assert data["filtered_count"] == data["total_items"]


def test_items_filter_by_outcome_pass(client):
    """Filter by outcome=pass should return only passing items."""
    _setup_eval_case(client)
    cfg = _create_gate_config(client, name="items-filter-pass")
    gate_run = _run_gate(client, cfg["id"])  # mock passes
    run_id = gate_run["id"]

    r = client.get(f"/admin/eval-gates/runs/{run_id}/items", params={"outcome": "pass"})
    assert r.status_code == 200
    items = r.json()["items"]
    for item in items:
        assert item["candidate_outcome"] == "pass"


def test_items_filter_by_outcome_fail(client):
    """Filter by outcome=fail should return only failing items."""
    _setup_eval_case(client)
    cfg = _create_gate_config(client, name="items-filter-fail")
    gate_run = _run_gate(client, cfg["id"], mock_rag=_mock_rag_fail())
    run_id = gate_run["id"]

    r = client.get(f"/admin/eval-gates/runs/{run_id}/items", params={"outcome": "fail"})
    assert r.status_code == 200
    items = r.json()["items"]
    for item in items:
        assert item["candidate_outcome"] == "fail"


def test_items_filter_by_regression_class(client):
    """Filter by regression_class returns correctly classified items."""
    fb1 = _create_reviewed_feedback(client, root_cause="retrieval_miss", topic="kubernetes")
    _create_eval_case(client, fb1)
    cfg = _create_gate_config(client, name="items-rc-filter", baseline_mode="previous_gate_run")

    # First run passes → no_baseline
    _run_gate(client, cfg["id"], mock_rag=_mock_rag_pass())

    # Second run fails → new_fail
    second_run = _run_gate(client, cfg["id"], mock_rag=_mock_rag_fail())
    run_id = second_run["id"]

    r = client.get(
        f"/admin/eval-gates/runs/{run_id}/items",
        params={"regression_class": "new_fail"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["filtered_count"] <= data["total_items"]
    for item in data["items"]:
        assert item["regression_class"] == "new_fail"


def test_items_filter_by_root_cause(client):
    """Filter by root_cause returns only items with that root cause."""
    fb1 = _create_reviewed_feedback(client, root_cause="retrieval_miss", topic="kubernetes")
    _create_eval_case(client, fb1)
    cfg = _create_gate_config(client, name="items-rc-cause-filter")
    gate_run = _run_gate(client, cfg["id"])
    run_id = gate_run["id"]

    r = client.get(
        f"/admin/eval-gates/runs/{run_id}/items",
        params={"root_cause": "retrieval_miss"},
    )
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["root_cause"] == "retrieval_miss"

    # Non-matching root cause → 0 items
    r2 = client.get(
        f"/admin/eval-gates/runs/{run_id}/items",
        params={"root_cause": "hallucination"},
    )
    assert r2.status_code == 200
    assert r2.json()["filtered_count"] == 0


def test_items_filter_by_expected_topic(client):
    """Filter by expected_topic returns only items with that topic."""
    fb1 = _create_reviewed_feedback(client, root_cause="retrieval_miss", topic="kubernetes")
    _create_eval_case(client, fb1)
    cfg = _create_gate_config(client, name="items-topic-filter")
    gate_run = _run_gate(client, cfg["id"])
    run_id = gate_run["id"]

    r = client.get(
        f"/admin/eval-gates/runs/{run_id}/items",
        params={"expected_topic": "kubernetes"},
    )
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["expected_topic"] == "kubernetes"

    r2 = client.get(
        f"/admin/eval-gates/runs/{run_id}/items",
        params={"expected_topic": "docker"},
    )
    assert r2.status_code == 200
    assert r2.json()["filtered_count"] == 0


def test_items_invalid_regression_class_returns_400(client):
    """Invalid regression_class returns 400."""
    _setup_eval_case(client)
    cfg = _create_gate_config(client, name="items-invalid-rc")
    gate_run = _run_gate(client, cfg["id"])
    run_id = gate_run["id"]

    r = client.get(
        f"/admin/eval-gates/runs/{run_id}/items",
        params={"regression_class": "totally_wrong"},
    )
    assert r.status_code == 400
    assert "regression_class" in r.json()["detail"].lower()


def test_items_invalid_outcome_returns_400(client):
    """Invalid outcome returns 400."""
    _setup_eval_case(client)
    cfg = _create_gate_config(client, name="items-invalid-outcome")
    gate_run = _run_gate(client, cfg["id"])
    run_id = gate_run["id"]

    r = client.get(
        f"/admin/eval-gates/runs/{run_id}/items",
        params={"outcome": "unknown_outcome"},
    )
    assert r.status_code == 400
    assert "outcome" in r.json()["detail"].lower()


# ─── Triage: gate run with no candidate batch (error decision) ────────────────

def test_triage_error_run_no_candidate(client):
    """Gate run with decision=error and no candidate batch → items is empty list."""
    cfg = _create_gate_config(client, name="triage-error-no-cases")
    # Run with no eval cases → decision=error
    r = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})
    assert r.status_code == 200
    gate_run = r.json()
    assert gate_run["decision"] == "error"
    run_id = gate_run["id"]

    r2 = client.get(f"/admin/eval-gates/runs/{run_id}/triage")
    assert r2.status_code == 200
    data = r2.json()
    assert data["gate_run"]["decision"] == "error"
    assert data["candidate_batch"] is None
    assert data["items"] == []


# ─── Unit: filter_triage_items ────────────────────────────────────────────────


def _make_items(specs: list[tuple]) -> list[dict]:
    """Build minimal triage items from (rc, root_cause, topic, outcome) tuples."""
    return [
        {
            "regression_class": rc,
            "root_cause": rca,
            "expected_topic": topic,
            "candidate_outcome": outcome,
        }
        for (rc, rca, topic, outcome) in specs
    ]


class TestFilterTriageItems:
    def test_no_filters_returns_all(self):
        items = _make_items([
            ("new_fail", "retrieval_miss", "k8s", "fail"),
            ("still_pass", "hallucination", "docker", "pass"),
        ])
        assert len(filter_triage_items(items)) == 2

    def test_filter_regression_class(self):
        items = _make_items([
            ("new_fail", "retrieval_miss", "k8s", "fail"),
            ("still_fail", "retrieval_miss", "k8s", "fail"),
            ("improved", "retrieval_miss", "k8s", "pass"),
        ])
        result = filter_triage_items(items, regression_class="new_fail")
        assert len(result) == 1
        assert result[0]["regression_class"] == "new_fail"

    def test_filter_root_cause(self):
        items = _make_items([
            ("new_fail", "retrieval_miss", "k8s", "fail"),
            ("new_fail", "hallucination", "k8s", "fail"),
        ])
        result = filter_triage_items(items, root_cause="hallucination")
        assert len(result) == 1
        assert result[0]["root_cause"] == "hallucination"

    def test_filter_expected_topic(self):
        items = _make_items([
            ("new_fail", "retrieval_miss", "k8s", "fail"),
            ("new_fail", "retrieval_miss", "docker", "fail"),
        ])
        result = filter_triage_items(items, expected_topic="docker")
        assert len(result) == 1
        assert result[0]["expected_topic"] == "docker"

    def test_filter_outcome(self):
        items = _make_items([
            ("new_fail", "retrieval_miss", "k8s", "fail"),
            ("still_pass", "retrieval_miss", "k8s", "pass"),
            ("new_error", "retrieval_miss", "k8s", "error"),
        ])
        result = filter_triage_items(items, outcome="error")
        assert len(result) == 1
        assert result[0]["candidate_outcome"] == "error"

    def test_combined_filters_anded(self):
        items = _make_items([
            ("new_fail", "retrieval_miss", "k8s", "fail"),
            ("new_fail", "hallucination", "k8s", "fail"),
            ("still_fail", "retrieval_miss", "docker", "fail"),
        ])
        result = filter_triage_items(
            items, regression_class="new_fail", root_cause="retrieval_miss"
        )
        assert len(result) == 1
        assert result[0]["root_cause"] == "retrieval_miss"
        assert result[0]["regression_class"] == "new_fail"

    def test_no_match_returns_empty(self):
        items = _make_items([("new_fail", "retrieval_miss", "k8s", "fail")])
        result = filter_triage_items(items, regression_class="improved")
        assert result == []
