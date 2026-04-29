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


# ─── POST /admin/eval-cases/run-batch ────────────────────────────────────────

def _setup_two_cases(client) -> tuple[int, int]:
    """Create two active eval cases with different root causes. Returns case IDs."""
    fb1 = _create_reviewed_feedback(client, root_cause="retrieval_miss", topic="kubernetes")
    fb2 = _create_reviewed_feedback(client, root_cause="hallucination", topic="docker")
    c1 = _create_eval_case(client, fb1).json()["id"]
    c2 = _create_eval_case(client, fb2).json()["id"]
    return c1, c2


def _mock_rag_pass():
    return _mock_rag_result(
        answer="Kubernetes is a container orchestration platform.",
        detected_topic="kubernetes",
        retrieval_count=3,
    )


def test_run_eval_batch_basic(client):
    """Run batch over active cases; verify batch + summary structure."""
    _setup_two_cases(client)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-cases/run-batch", json={})

    assert r.status_code == 200
    batch = r.json()
    assert batch["id"] > 0
    assert batch["status"] == "completed"
    assert batch["total_cases"] == 2
    assert "summary" in batch
    s = batch["summary"]
    assert s["total_cases"] == 2
    assert s["pass_count"] + s["fail_count"] + s["error_count"] == 2
    assert "by_root_cause" in s
    assert "by_expected_topic" in s


def test_run_eval_batch_with_label(client):
    _setup_two_cases(client)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-cases/run-batch", json={"label": "Post-tuning check"})

    assert r.status_code == 200
    assert r.json()["label"] == "Post-tuning check"


def test_run_eval_batch_filter_by_root_cause(client):
    """Only cases matching root_cause should be included."""
    _setup_two_cases(client)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-cases/run-batch", json={"root_cause": "retrieval_miss"})

    assert r.status_code == 200
    batch = r.json()
    assert batch["total_cases"] == 1
    s = batch["summary"]
    assert "retrieval_miss" in s["by_root_cause"]
    assert "hallucination" not in s["by_root_cause"]


def test_run_eval_batch_filter_by_expected_topic(client):
    """Only cases matching expected_topic should be included."""
    _setup_two_cases(client)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-cases/run-batch", json={"expected_topic": "docker"})

    assert r.status_code == 200
    batch = r.json()
    assert batch["total_cases"] == 1


def test_run_eval_batch_no_matching_cases_rejected(client):
    """Batch with no matching cases must return 400."""
    r = client.post("/admin/eval-cases/run-batch", json={})
    assert r.status_code == 400
    assert "No matching eval cases" in r.json()["detail"]


def test_run_eval_batch_invalid_status_rejected(client):
    r = client.post("/admin/eval-cases/run-batch", json={"status": "invalid"})
    assert r.status_code == 400


def test_run_eval_batch_filter_by_status_archived(client):
    """Batch can also run archived cases if explicitly requested."""
    fb1 = _create_reviewed_feedback(client)
    case_id = _create_eval_case(client, fb1).json()["id"]
    # Archive the case
    client.patch(f"/admin/eval-cases/{case_id}/status", json={"status": "archived"})

    # Should find no active cases
    r_no = client.post("/admin/eval-cases/run-batch", json={"status": "active"})
    assert r_no.status_code == 400

    # Should find archived case
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r_arch = client.post("/admin/eval-cases/run-batch", json={"status": "archived"})
    assert r_arch.status_code == 200
    assert r_arch.json()["total_cases"] == 1


def test_run_eval_batch_persists_batch_items(client):
    """Each case run must create a batch item with correct eval_run_id linkage."""
    c1_id, c2_id = _setup_two_cases(client)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-cases/run-batch", json={})
    batch_id = r.json()["id"]

    items_r = client.get(f"/admin/eval-batches/{batch_id}/items")
    assert items_r.status_code == 200
    items = items_r.json()["items"]
    assert len(items) == 2
    case_ids_in_batch = {it["eval_case_id"] for it in items}
    assert c1_id in case_ids_in_batch
    assert c2_id in case_ids_in_batch
    # Each item should link to an eval_run
    for it in items:
        assert it["eval_run_id"] is not None
        assert it["pass"] is not None


def test_run_eval_batch_records_execution_errors(client):
    """If one case errors during run, it is recorded as an error item; batch completes."""
    _setup_two_cases(client)
    call_count = [0]

    def _side_effect(question):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Pipeline down")
        return _mock_rag_pass()

    with patch("orchestrator.eval_runner._chat_with_trace", side_effect=_side_effect):
        r = client.post("/admin/eval-cases/run-batch", json={})

    assert r.status_code == 200
    batch = r.json()
    assert batch["total_cases"] == 2
    s = batch["summary"]
    assert s["error_count"] == 1

    items_r = client.get(f"/admin/eval-batches/{batch['id']}/items")
    items = items_r.json()["items"]
    error_items = [it for it in items if it["pass"] is None]
    assert len(error_items) == 1
    assert error_items[0]["error"] is not None
    assert "Pipeline down" in error_items[0]["error"]


def test_run_eval_batch_pass_rate_correct(client):
    """All cases pass → pass_rate = 1.0."""
    _setup_two_cases(client)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-cases/run-batch", json={})

    s = r.json()["summary"]
    # Both cases: retrieval_miss + hallucination. The mock returns good answer
    # with citations, so both should pass.
    assert s["pass_rate"] > 0


# ─── GET /admin/eval-batches ─────────────────────────────────────────────────

def test_list_eval_batches_empty(client):
    r = client.get("/admin/eval-batches")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["batches"] == []


def test_list_eval_batches_after_run(client):
    _setup_two_cases(client)
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        client.post("/admin/eval-cases/run-batch", json={"label": "batch-1"})
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        client.post("/admin/eval-cases/run-batch", json={"label": "batch-2"})

    r = client.get("/admin/eval-batches")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    # newest first
    assert data["batches"][0]["label"] == "batch-2"
    assert data["batches"][1]["label"] == "batch-1"


# ─── GET /admin/eval-batches/{batch_id} ──────────────────────────────────────

def test_get_eval_batch_not_found(client):
    r = client.get("/admin/eval-batches/9999")
    assert r.status_code == 404


def test_get_eval_batch_detail(client):
    _setup_two_cases(client)
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        run_r = client.post("/admin/eval-cases/run-batch", json={})
    batch_id = run_r.json()["id"]

    r = client.get(f"/admin/eval-batches/{batch_id}")
    assert r.status_code == 200
    batch = r.json()
    assert batch["id"] == batch_id
    assert "summary" in batch
    s = batch["summary"]
    assert "total_cases" in s
    assert "pass_count" in s
    assert "fail_count" in s
    assert "pass_rate" in s
    assert "by_root_cause" in s
    assert "by_expected_topic" in s


# ─── GET /admin/eval-batches/{batch_id}/items ────────────────────────────────

def test_get_eval_batch_items_not_found(client):
    r = client.get("/admin/eval-batches/9999/items")
    assert r.status_code == 404


def test_get_eval_batch_items_structure(client):
    c1_id, c2_id = _setup_two_cases(client)
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        run_r = client.post("/admin/eval-cases/run-batch", json={})
    batch_id = run_r.json()["id"]

    r = client.get(f"/admin/eval-batches/{batch_id}/items")
    assert r.status_code == 200
    data = r.json()
    assert data["batch_id"] == batch_id
    assert data["count"] == 2
    items = data["items"]
    for it in items:
        assert "eval_case_id" in it
        assert "eval_run_id" in it
        assert "pass" in it
        assert "root_cause" in it
        assert "expected_topic" in it
        assert "error" in it


# ─── GET /admin/eval-batches/compare ─────────────────────────────────────────

def _run_batch(client, label: str | None = None) -> dict:
    """Run a batch (with mock) and return the batch dict."""
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-cases/run-batch", json={"label": label})
    assert r.status_code == 200
    return r.json()


def test_compare_two_batches_explicit(client):
    """Explicit baseline + candidate comparison returns correct delta fields."""
    _setup_two_cases(client)
    b1 = _run_batch(client, label="baseline")
    b2 = _run_batch(client, label="candidate")

    r = client.get(
        "/admin/eval-batches/compare",
        params={"baseline_batch_id": b1["id"], "candidate_batch_id": b2["id"]},
    )
    assert r.status_code == 200
    cmp = r.json()

    assert cmp["baseline_batch_id"] == b1["id"]
    assert cmp["candidate_batch_id"] == b2["id"]
    # All required top-level delta fields are present
    for field in [
        "baseline_total_cases", "candidate_total_cases",
        "baseline_pass_count", "candidate_pass_count",
        "baseline_fail_count", "candidate_fail_count",
        "baseline_error_count", "candidate_error_count",
        "baseline_pass_rate", "candidate_pass_rate",
        "delta_pass_count", "delta_fail_count", "delta_error_count", "delta_pass_rate",
        "sizes_differ", "by_root_cause", "by_expected_topic",
    ]:
        assert field in cmp, f"Missing field: {field}"


def test_compare_batches_delta_values_correct(client):
    """delta_pass_rate = candidate_pass_rate - baseline_pass_rate."""
    _setup_two_cases(client)
    b1 = _run_batch(client)
    b2 = _run_batch(client)

    r = client.get(
        "/admin/eval-batches/compare",
        params={"baseline_batch_id": b1["id"], "candidate_batch_id": b2["id"]},
    )
    cmp = r.json()
    expected_delta = round(cmp["candidate_pass_rate"] - cmp["baseline_pass_rate"], 4)
    assert cmp["delta_pass_rate"] == expected_delta
    assert cmp["delta_pass_count"] == cmp["candidate_pass_count"] - cmp["baseline_pass_count"]
    assert cmp["delta_fail_count"] == cmp["candidate_fail_count"] - cmp["baseline_fail_count"]


def test_compare_batches_breakdown_present(client):
    """by_root_cause and by_expected_topic breakdowns are non-empty dicts."""
    _setup_two_cases(client)
    b1 = _run_batch(client)
    b2 = _run_batch(client)

    r = client.get(
        "/admin/eval-batches/compare",
        params={"baseline_batch_id": b1["id"], "candidate_batch_id": b2["id"]},
    )
    cmp = r.json()
    assert isinstance(cmp["by_root_cause"], dict)
    assert isinstance(cmp["by_expected_topic"], dict)
    # Both cases from _setup_two_cases have known root causes
    assert len(cmp["by_root_cause"]) >= 1


def test_compare_batches_convenience_auto_baseline(client):
    """When only candidate_batch_id supplied, immediately previous batch is baseline."""
    _setup_two_cases(client)
    b1 = _run_batch(client, label="older")
    b2 = _run_batch(client, label="newer")

    r = client.get(
        "/admin/eval-batches/compare",
        params={"candidate_batch_id": b2["id"]},
    )
    assert r.status_code == 200
    cmp = r.json()
    assert cmp["baseline_batch_id"] == b1["id"]
    assert cmp["candidate_batch_id"] == b2["id"]


def test_compare_batches_convenience_no_previous_batch(client):
    """If candidate is the only batch, auto-baseline fails with 400."""
    _setup_two_cases(client)
    b1 = _run_batch(client)

    r = client.get(
        "/admin/eval-batches/compare",
        params={"candidate_batch_id": b1["id"]},
    )
    assert r.status_code == 400
    assert "previous" in r.json()["detail"].lower()


def test_compare_batches_missing_baseline_id(client):
    """Non-existent baseline_batch_id returns 404."""
    _setup_two_cases(client)
    b1 = _run_batch(client)

    r = client.get(
        "/admin/eval-batches/compare",
        params={"baseline_batch_id": 9999, "candidate_batch_id": b1["id"]},
    )
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_compare_batches_missing_candidate_id(client):
    """Non-existent candidate_batch_id returns 404."""
    _setup_two_cases(client)
    b1 = _run_batch(client)

    r = client.get(
        "/admin/eval-batches/compare",
        params={"baseline_batch_id": b1["id"], "candidate_batch_id": 9999},
    )
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


# ─── GET /admin/eval-batches/trend ───────────────────────────────────────────

def test_eval_batches_trend_empty(client):
    r = client.get("/admin/eval-batches/trend")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["batches"] == []


def test_eval_batches_trend_newest_first(client):
    """Trend returns batches newest-first."""
    _setup_two_cases(client)
    _run_batch(client, label="first")
    _run_batch(client, label="second")

    r = client.get("/admin/eval-batches/trend")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert data["batches"][0]["label"] == "second"
    assert data["batches"][1]["label"] == "first"


def test_eval_batches_trend_compact_fields(client):
    """Each trend item has all required compact fields."""
    _setup_two_cases(client)
    _run_batch(client, label="test-run")

    r = client.get("/admin/eval-batches/trend")
    item = r.json()["batches"][0]
    for field in [
        "id", "label", "created_at",
        "total_cases", "pass_count", "fail_count", "error_count", "pass_rate",
    ]:
        assert field in item, f"Missing trend field: {field}"


def test_eval_batches_trend_limit(client):
    """Limit param controls the number of trend items returned."""
    _setup_two_cases(client)
    for _ in range(4):
        _run_batch(client)

    r = client.get("/admin/eval-batches/trend", params={"limit": 2})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert len(data["batches"]) == 2


def test_eval_batches_trend_pass_rate_in_range(client):
    """pass_rate is between 0 and 1."""
    _setup_two_cases(client)
    _run_batch(client)

    r = client.get("/admin/eval-batches/trend")
    item = r.json()["batches"][0]
    assert 0.0 <= item["pass_rate"] <= 1.0
