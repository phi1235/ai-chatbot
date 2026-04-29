"""Tests for eval case API endpoints."""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Each test gets isolated chroma dir + fresh SQLite DBs."""
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
    import api.admin as admin_mod
    importlib.reload(admin_mod)

    from api.main import app
    return TestClient(app)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _create_reviewed_feedback(client, *, root_cause="retrieval_miss", topic="kubernetes"):
    """Submit a down feedback and mark it reviewed. Returns feedback_id."""
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


# ─── POST /admin/feedback/{id}/eval-case ─────────────────────────────────────

def test_create_eval_case_from_reviewed_feedback(client):
    fb_id = _create_reviewed_feedback(client)
    r = _create_eval_case(client, fb_id)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] > 0
    assert data["feedback_id"] == fb_id
    assert data["question"] == "How to deploy pods?"
    assert data["root_cause"] == "retrieval_miss"
    assert data["expected_topic"] == "kubernetes"
    assert data["status"] == "active"
    # Check expectations were derived
    exp = data["eval_expectations"]
    assert exp["should_not_fallback"] is True
    assert exp["should_have_citations"] is True
    assert exp["min_retrieval_count"] == 1


def test_create_eval_case_preserves_snapshot_fields(client):
    fb_id = _create_reviewed_feedback(client)
    r = _create_eval_case(client, fb_id)
    data = r.json()
    assert data["rewritten_query"] == "deploy kubernetes pods"
    assert isinstance(data["citations_snapshot"], list)
    assert len(data["citations_snapshot"]) == 1
    assert data["citations_snapshot"][0]["title"] == "K8s docs"


def test_create_eval_case_feedback_not_found(client):
    r = _create_eval_case(client, 9999)
    assert r.status_code == 404


def test_create_eval_case_unreviewed_feedback_rejected(client):
    """Feedback that has not been reviewed yet must be rejected."""
    r = client.post("/feedback", json={
        "question": "Q", "answer": "A", "feedback_type": "down",
    })
    fb_id = r.json()["id"]
    r2 = _create_eval_case(client, fb_id)
    assert r2.status_code == 400
    assert "review" in r2.json()["detail"].lower()


def test_create_eval_case_duplicate_active_rejected(client):
    """Creating a second active eval case for the same feedback must return 409."""
    fb_id = _create_reviewed_feedback(client)
    r1 = _create_eval_case(client, fb_id)
    assert r1.status_code == 200
    r2 = _create_eval_case(client, fb_id)
    assert r2.status_code == 409
    assert "active eval case" in r2.json()["detail"].lower()


def test_create_eval_case_root_cause_true_coverage_gap(client):
    fb_id = _create_reviewed_feedback(client, root_cause="true_coverage_gap")
    r = _create_eval_case(client, fb_id)
    assert r.status_code == 200
    exp = r.json()["eval_expectations"]
    # true_coverage_gap: should_not_fallback=False (fallback acceptable)
    assert exp["should_not_fallback"] is False


# ─── GET /admin/eval-cases ───────────────────────────────────────────────────

def test_list_eval_cases_empty(client):
    r = client.get("/admin/eval-cases")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["items"] == []
    assert data["summary"]["total"] == 0


def test_list_eval_cases_returns_items(client):
    fb1 = _create_reviewed_feedback(client)
    fb2 = _create_reviewed_feedback(client, root_cause="hallucination", topic="docker")
    _create_eval_case(client, fb1)
    # Need different feedback for second case — fb2
    _create_eval_case(client, fb2)

    r = client.get("/admin/eval-cases")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2


def test_list_eval_cases_filter_by_status(client):
    fb_id = _create_reviewed_feedback(client)
    r_create = _create_eval_case(client, fb_id)
    case_id = r_create.json()["id"]

    # Archive it
    client.patch(f"/admin/eval-cases/{case_id}/status", json={"status": "archived"})

    active = client.get("/admin/eval-cases", params={"status": "active"})
    assert active.json()["count"] == 0

    archived = client.get("/admin/eval-cases", params={"status": "archived"})
    assert archived.json()["count"] == 1


def test_list_eval_cases_invalid_status(client):
    r = client.get("/admin/eval-cases", params={"status": "invalid"})
    assert r.status_code == 400


def test_list_eval_cases_includes_latest_run(client):
    """latest_run should be None before any run, populated after."""
    fb_id = _create_reviewed_feedback(client)
    _create_eval_case(client, fb_id)

    items = client.get("/admin/eval-cases").json()["items"]
    assert items[0]["latest_run"] is None


# ─── GET /admin/eval-cases/summary ──────────────────────────────────────────

def test_eval_cases_summary_empty(client):
    r = client.get("/admin/eval-cases/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["total_active"] == 0
    assert data["latest_runs"]["total"] == 0


def test_eval_cases_summary_with_data(client):
    fb1 = _create_reviewed_feedback(client)
    fb2 = _create_reviewed_feedback(client, root_cause="hallucination", topic="docker")
    _create_eval_case(client, fb1)
    _create_eval_case(client, fb2)

    r = client.get("/admin/eval-cases/summary")
    data = r.json()
    assert data["total"] == 2
    assert data["total_active"] == 2
    assert data["by_root_cause"]["retrieval_miss"] == 1
    assert data["by_root_cause"]["hallucination"] == 1


# ─── POST /admin/eval-cases/{id}/run ────────────────────────────────────────

def _mock_rag_result(
    answer="Kubernetes is a container orchestration platform.",
    detected_topic="kubernetes",
    retrieval_count=3,
    citations_count=1,
):
    """Build a mock RagResult-like object."""
    from schemas.chat import Citation
    citations = [
        Citation(title=f"K8s docs {i}", url="https://k8s.io")
        for i in range(citations_count)
    ]
    mock = MagicMock()
    mock.answer = answer
    mock.detected_topic = detected_topic
    mock.retrieval_count = retrieval_count
    mock.citations = citations
    return mock


def test_run_eval_case_pass(client):
    fb_id = _create_reviewed_feedback(client)
    r_case = _create_eval_case(client, fb_id)
    case_id = r_case.json()["id"]

    rag_mock = _mock_rag_result(
        answer="Kubernetes is an orchestration platform.",
        detected_topic="kubernetes",
        retrieval_count=3,
    )
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=rag_mock):
        r = client.post(f"/admin/eval-cases/{case_id}/run")

    assert r.status_code == 200
    data = r.json()
    assert data["eval_case_id"] == case_id
    assert data["pass"] is True
    assert "checks" in data
    assert "result_snapshot" in data


def test_run_eval_case_fail_on_fallback(client):
    """Expectations say should_not_fallback=True; if answer is fallback → fail."""
    fb_id = _create_reviewed_feedback(client, root_cause="retrieval_miss")
    r_case = _create_eval_case(client, fb_id)
    case_id = r_case.json()["id"]

    # Fallback-like answer
    rag_mock = _mock_rag_result(
        answer="Hiện tại tôi chưa tìm thấy thông tin đủ liên quan để trả lời.",
        detected_topic="kubernetes",
        retrieval_count=0,
    )
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=rag_mock):
        r = client.post(f"/admin/eval-cases/{case_id}/run")

    assert r.status_code == 200
    data = r.json()
    assert data["pass"] is False
    checks = data["checks"]
    assert checks["should_not_fallback"]["pass"] is False


def test_run_eval_case_fail_on_no_citations(client):
    """should_have_citations=True + retrieval_count=0 → fail."""
    fb_id = _create_reviewed_feedback(client, root_cause="retrieval_miss")
    r_case = _create_eval_case(client, fb_id)
    case_id = r_case.json()["id"]

    rag_mock = _mock_rag_result(
        answer="Some answer text that is not a fallback response here.",
        detected_topic="kubernetes",
        retrieval_count=0,
        citations_count=0,
    )
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=rag_mock):
        r = client.post(f"/admin/eval-cases/{case_id}/run")

    assert r.status_code == 200
    data = r.json()
    assert data["pass"] is False
    assert data["checks"]["should_have_citations"]["pass"] is False


def test_run_eval_case_not_found(client):
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_result()):
        r = client.post("/admin/eval-cases/9999/run")
    assert r.status_code == 404


def test_run_eval_case_archived_rejected(client):
    fb_id = _create_reviewed_feedback(client)
    r_case = _create_eval_case(client, fb_id)
    case_id = r_case.json()["id"]
    client.patch(f"/admin/eval-cases/{case_id}/status", json={"status": "archived"})

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_result()):
        r = client.post(f"/admin/eval-cases/{case_id}/run")
    assert r.status_code == 400


# ─── GET /admin/eval-cases/{id}/runs ────────────────────────────────────────

def test_list_eval_case_runs_empty(client):
    fb_id = _create_reviewed_feedback(client)
    r_case = _create_eval_case(client, fb_id)
    case_id = r_case.json()["id"]

    r = client.get(f"/admin/eval-cases/{case_id}/runs")
    assert r.status_code == 200
    data = r.json()
    assert data["eval_case_id"] == case_id
    assert data["count"] == 0
    assert data["runs"] == []


def test_list_eval_case_runs_after_run(client):
    fb_id = _create_reviewed_feedback(client)
    r_case = _create_eval_case(client, fb_id)
    case_id = r_case.json()["id"]

    rag_mock = _mock_rag_result(answer="Good answer.", detected_topic="kubernetes",
                                retrieval_count=2)
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=rag_mock):
        client.post(f"/admin/eval-cases/{case_id}/run")
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=rag_mock):
        client.post(f"/admin/eval-cases/{case_id}/run")

    r = client.get(f"/admin/eval-cases/{case_id}/runs")
    data = r.json()
    assert data["count"] == 2


def test_list_eval_case_runs_not_found(client):
    r = client.get("/admin/eval-cases/9999/runs")
    assert r.status_code == 404


# ─── PATCH /admin/eval-cases/{id}/status ────────────────────────────────────

def test_update_eval_case_status_archive(client):
    fb_id = _create_reviewed_feedback(client)
    r_case = _create_eval_case(client, fb_id)
    case_id = r_case.json()["id"]

    r = client.patch(f"/admin/eval-cases/{case_id}/status", json={"status": "archived"})
    assert r.status_code == 200
    assert r.json()["status"] == "archived"


def test_update_eval_case_status_invalid(client):
    fb_id = _create_reviewed_feedback(client)
    r_case = _create_eval_case(client, fb_id)
    case_id = r_case.json()["id"]

    r = client.patch(f"/admin/eval-cases/{case_id}/status", json={"status": "deleted"})
    assert r.status_code == 400


def test_update_eval_case_status_not_found(client):
    r = client.patch("/admin/eval-cases/9999/status", json={"status": "archived"})
    assert r.status_code == 404


# ─── Integration: full eval flow ─────────────────────────────────────────────

def test_full_eval_flow(client):
    """Full flow: submit feedback → review → create eval case → run → see result in list."""
    # Submit down feedback
    r1 = client.post("/feedback", json={
        "question": "How to configure ingress?",
        "answer": "Use nginx.",
        "feedback_type": "down",
        "detected_topic": "kubernetes",
        "retrieval_count": 0,
    })
    fb_id = r1.json()["id"]

    # Admin reviews with root cause
    client.post(f"/admin/feedback/{fb_id}/review", json={
        "review_status": "reviewed",
        "root_cause": "retrieval_miss",
    })

    # Create eval case
    r2 = client.post(f"/admin/feedback/{fb_id}/eval-case")
    assert r2.status_code == 200
    case_id = r2.json()["id"]

    # Run the eval case (mock pipeline returning good answer)
    rag_mock = _mock_rag_result(
        answer="Ingress controller manages external access to services.",
        detected_topic="kubernetes",
        retrieval_count=2,
    )
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=rag_mock):
        r3 = client.post(f"/admin/eval-cases/{case_id}/run")
    assert r3.status_code == 200
    run = r3.json()
    assert run["pass"] is True

    # List eval cases — latest_run should be populated
    r4 = client.get("/admin/eval-cases")
    items = r4.json()["items"]
    assert len(items) == 1
    assert items[0]["latest_run"] is not None
    assert items[0]["latest_run"]["pass"] is True

    # Summary counts
    r5 = client.get("/admin/eval-cases/summary")
    summary = r5.json()
    assert summary["total_active"] == 1
    assert summary["latest_runs"]["pass"] == 1
    assert summary["latest_runs"]["fail"] == 0
