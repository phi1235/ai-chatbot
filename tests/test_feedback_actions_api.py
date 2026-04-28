"""Tests for feedback action queue API endpoints (TestClient)."""
from __future__ import annotations

import importlib
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Each test gets isolated chroma dir + sqlite DBs."""
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
    import orchestrator.feedback_action_store as fas_mod
    fas_mod._initialised_paths.clear()
    importlib.reload(fas_mod)
    import orchestrator.coverage_gap_store as cgs_mod
    cgs_mod._initialised_paths.clear()
    importlib.reload(cgs_mod)
    import api.admin as admin_mod
    importlib.reload(admin_mod)

    from api.main import app
    return TestClient(app)


def _seed_feedback(client, *, root_cause: str | None = None, topic: str | None = None) -> int:
    """Submit a feedback and optionally review it; return feedback_id."""
    body = {
        "question": "How to scale pods?",
        "answer": "Use HPA.",
        "feedback_type": "down",
        "detected_topic": topic,
    }
    r = client.post("/feedback", json=body)
    assert r.status_code == 200
    fb_id = r.json()["id"]

    if root_cause:
        r2 = client.post(
            f"/admin/feedback/{fb_id}/review",
            json={"review_status": "reviewed", "root_cause": root_cause},
        )
        assert r2.status_code == 200

    return fb_id


# ─── POST /admin/feedback/{id}/action-item ────────────────────────────────────

def test_create_action_item_basic(client):
    fb_id = _seed_feedback(client, root_cause="retrieval_miss", topic="kubernetes")
    r = client.post(f"/admin/feedback/{fb_id}/action-item")
    assert r.status_code == 200
    data = r.json()
    assert data["feedback_id"] == fb_id
    assert data["suggested_action"] == "create_coverage_gap"
    assert data["status"] == "pending"
    assert data["root_cause"] == "retrieval_miss"
    assert data["detected_topic"] == "kubernetes"
    assert data["reason"]


def test_create_action_item_requires_review_first(client):
    fb_id = _seed_feedback(client)
    r = client.post(f"/admin/feedback/{fb_id}/action-item")
    assert r.status_code == 400
    assert "review" in r.json()["detail"].lower()


def test_create_action_item_no_root_cause(client):
    """Feedback without root_cause → suggested_action = ignore."""
    fb_id = _seed_feedback(client)
    client.post(
        f"/admin/feedback/{fb_id}/review",
        json={"review_status": "reviewed"},
    )
    r = client.post(f"/admin/feedback/{fb_id}/action-item")
    assert r.status_code == 200
    assert r.json()["suggested_action"] == "ignore"


def test_create_action_item_not_found(client):
    r = client.post("/admin/feedback/9999/action-item")
    assert r.status_code == 404


def test_create_action_item_duplicate_active_returns_409(client):
    fb_id = _seed_feedback(client, root_cause="retrieval_miss")
    client.post(f"/admin/feedback/{fb_id}/action-item")
    r2 = client.post(f"/admin/feedback/{fb_id}/action-item")
    assert r2.status_code == 409
    assert "active action item" in r2.json()["detail"].lower()


def test_create_action_item_allowed_after_done(client):
    fb_id = _seed_feedback(client, root_cause="retrieval_miss")
    r1 = client.post(f"/admin/feedback/{fb_id}/action-item")
    action_id = r1.json()["id"]
    client.post(
        f"/admin/feedback-actions/{action_id}/status",
        json={"status": "done"},
    )
    # New action item should now be creatable
    r2 = client.post(f"/admin/feedback/{fb_id}/action-item")
    assert r2.status_code == 200
    assert r2.json()["id"] != action_id


# ─── Root cause heuristic mapping (via API) ───────────────────────────────────

@pytest.mark.parametrize("root_cause,expected_action", [
    ("retrieval_miss", "create_coverage_gap"),
    ("true_coverage_gap", "create_coverage_gap"),
    ("stale_source_mix", "recrawl_source"),
    ("insufficient_context", "improve_retrieval"),
    ("bad_citation_fit", "improve_retrieval"),
    ("wrong_answer_from_context", "adjust_prompt"),
    ("hallucination", "adjust_prompt"),
    ("other", "ignore"),
])
def test_heuristic_mapping(client, root_cause, expected_action):
    fb_id = _seed_feedback(client, root_cause=root_cause)
    r = client.post(f"/admin/feedback/{fb_id}/action-item")
    assert r.status_code == 200
    assert r.json()["suggested_action"] == expected_action


# ─── GET /admin/feedback-actions ─────────────────────────────────────────────

def test_list_action_items_empty(client):
    r = client.get("/admin/feedback-actions")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["items"] == []
    assert data["summary"]["total"] == 0


def test_list_action_items_returns_created(client):
    fb_id = _seed_feedback(client, root_cause="retrieval_miss")
    client.post(f"/admin/feedback/{fb_id}/action-item")
    r = client.get("/admin/feedback-actions")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    item = data["items"][0]
    assert item["feedback_id"] == fb_id
    assert item["suggested_action"] == "create_coverage_gap"


def test_list_action_items_filter_by_status(client):
    fb1 = _seed_feedback(client, root_cause="retrieval_miss")
    fb2 = _seed_feedback(client, root_cause="hallucination")
    r1 = client.post(f"/admin/feedback/{fb1}/action-item")
    client.post(f"/admin/feedback/{fb2}/action-item")
    action_id = r1.json()["id"]
    client.post(
        f"/admin/feedback-actions/{action_id}/status",
        json={"status": "accepted"},
    )

    r = client.get("/admin/feedback-actions", params={"status": "accepted"})
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert r.json()["items"][0]["status"] == "accepted"

    r2 = client.get("/admin/feedback-actions", params={"status": "pending"})
    assert r2.json()["count"] == 1
    assert r2.json()["items"][0]["status"] == "pending"


def test_list_action_items_filter_by_suggested_action(client):
    fb1 = _seed_feedback(client, root_cause="retrieval_miss")
    fb2 = _seed_feedback(client, root_cause="hallucination")
    client.post(f"/admin/feedback/{fb1}/action-item")
    client.post(f"/admin/feedback/{fb2}/action-item")

    r = client.get("/admin/feedback-actions", params={"suggested_action": "create_coverage_gap"})
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert r.json()["items"][0]["suggested_action"] == "create_coverage_gap"


def test_list_action_items_invalid_status_returns_400(client):
    r = client.get("/admin/feedback-actions", params={"status": "invalid"})
    assert r.status_code == 400


def test_list_action_items_invalid_suggested_action_returns_400(client):
    r = client.get("/admin/feedback-actions", params={"suggested_action": "invalid"})
    assert r.status_code == 400


def test_list_action_items_includes_summary(client):
    fb1 = _seed_feedback(client, root_cause="retrieval_miss")
    fb2 = _seed_feedback(client, root_cause="stale_source_mix")
    client.post(f"/admin/feedback/{fb1}/action-item")
    client.post(f"/admin/feedback/{fb2}/action-item")

    r = client.get("/admin/feedback-actions")
    summary = r.json()["summary"]
    assert summary["total"] == 2
    assert summary["total_pending"] == 2
    assert summary["by_action"]["create_coverage_gap"] == 1
    assert summary["by_action"]["recrawl_source"] == 1


# ─── POST /admin/feedback-actions/{id}/status ────────────────────────────────

def test_update_action_status_basic(client):
    fb_id = _seed_feedback(client, root_cause="retrieval_miss")
    r1 = client.post(f"/admin/feedback/{fb_id}/action-item")
    action_id = r1.json()["id"]

    r2 = client.post(
        f"/admin/feedback-actions/{action_id}/status",
        json={"status": "accepted"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "accepted"


def test_update_action_status_with_note(client):
    fb_id = _seed_feedback(client, root_cause="hallucination")
    action_id = client.post(f"/admin/feedback/{fb_id}/action-item").json()["id"]

    r = client.post(
        f"/admin/feedback-actions/{action_id}/status",
        json={"status": "done", "owner_note": "Fixed in prompt v3"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "done"
    assert data["owner_note"] == "Fixed in prompt v3"


def test_update_action_status_not_found(client):
    r = client.post(
        "/admin/feedback-actions/9999/status",
        json={"status": "done"},
    )
    assert r.status_code == 404


def test_update_action_status_invalid_status(client):
    fb_id = _seed_feedback(client, root_cause="retrieval_miss")
    action_id = client.post(f"/admin/feedback/{fb_id}/action-item").json()["id"]

    r = client.post(
        f"/admin/feedback-actions/{action_id}/status",
        json={"status": "invalid_status"},
    )
    assert r.status_code == 400


# ─── GET /admin/feedback-actions/summary ─────────────────────────────────────

def test_feedback_actions_summary_empty(client):
    r = client.get("/admin/feedback-actions/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["by_action"] == {}


def test_feedback_actions_summary_with_data(client):
    fb1 = _seed_feedback(client, root_cause="retrieval_miss")
    fb2 = _seed_feedback(client, root_cause="hallucination")
    r1 = client.post(f"/admin/feedback/{fb1}/action-item")
    client.post(f"/admin/feedback/{fb2}/action-item")
    client.post(
        f"/admin/feedback-actions/{r1.json()['id']}/status",
        json={"status": "done"},
    )

    r = client.get("/admin/feedback-actions/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert data["total_done"] == 1
    assert data["total_pending"] == 1


# ─── Integration: full workflow ───────────────────────────────────────────────

def test_full_feedback_to_action_flow(client):
    """Full flow: submit feedback → review with root cause → create action item → update status."""
    # 1. User submits down feedback
    r1 = client.post("/feedback", json={
        "question": "How to configure ingress?",
        "answer": "You can use nginx.",
        "feedback_type": "down",
        "detected_topic": "kubernetes",
        "rewritten_query": "configure kubernetes ingress",
    })
    assert r1.status_code == 200
    fb_id = r1.json()["id"]

    # 2. Admin reviews and sets root cause
    r2 = client.post(
        f"/admin/feedback/{fb_id}/review",
        json={"review_status": "reviewed", "root_cause": "insufficient_context"},
    )
    assert r2.status_code == 200
    assert r2.json()["root_cause"] == "insufficient_context"

    # 3. Admin creates action item
    r3 = client.post(f"/admin/feedback/{fb_id}/action-item")
    assert r3.status_code == 200
    action = r3.json()
    assert action["suggested_action"] == "improve_retrieval"
    assert action["status"] == "pending"
    assert action["detected_topic"] == "kubernetes"
    assert action["query_hint"] == "configure kubernetes ingress"

    action_id = action["id"]

    # 4. Admin accepts the action
    r4 = client.post(
        f"/admin/feedback-actions/{action_id}/status",
        json={"status": "accepted", "owner_note": "Will tune retrieval for ingress docs"},
    )
    assert r4.status_code == 200
    assert r4.json()["status"] == "accepted"
    assert r4.json()["owner_note"] == "Will tune retrieval for ingress docs"

    # 5. Action queue shows it
    r5 = client.get("/admin/feedback-actions", params={"status": "accepted"})
    assert r5.json()["count"] == 1
    assert r5.json()["items"][0]["id"] == action_id

    # 6. Mark done
    r6 = client.post(
        f"/admin/feedback-actions/{action_id}/status",
        json={"status": "done"},
    )
    assert r6.json()["status"] == "done"

    # 7. Summary reflects completion
    r7 = client.get("/admin/feedback-actions/summary")
    assert r7.json()["total_done"] == 1
    assert r7.json()["total_pending"] == 0


# ─── POST /admin/feedback-actions/{id}/execute ───────────────────────────────

def _create_action_item(client, *, root_cause: str, topic: str | None = None) -> dict:
    """Helper: seed feedback → review → create action item. Return action item dict."""
    fb_id = _seed_feedback(client, root_cause=root_cause, topic=topic)
    r = client.post(f"/admin/feedback/{fb_id}/action-item")
    assert r.status_code == 200
    return r.json()


def test_execute_not_found(client):
    r = client.post("/admin/feedback-actions/9999/execute")
    assert r.status_code == 404


def test_execute_create_coverage_gap_success(client):
    """create_coverage_gap action → creates a coverage gap, returns execution_status=executed."""
    action = _create_action_item(client, root_cause="retrieval_miss", topic="kubernetes")
    action_id = action["id"]

    r = client.post(f"/admin/feedback-actions/{action_id}/execute")
    assert r.status_code == 200
    data = r.json()

    assert data["execution_status"] == "executed"
    assert data["execution_type"] == "coverage_gap_review"
    assert data["executed_at"] is not None

    result = data["execution_result"]
    assert "coverage_gap_id" in result
    assert result["coverage_gap_id"] > 0
    assert "created" in result["summary"]

    # Verify the coverage gap was actually persisted
    import orchestrator.coverage_gap_store as cgs
    gap = cgs.get_gap(result["coverage_gap_id"])
    assert gap is not None
    assert gap["detected_topic"] == "kubernetes"
    assert "feedback_action_queue" in gap["gap_signals"]


def test_execute_create_coverage_gap_with_topic_and_hint(client):
    """create_coverage_gap: query_hint + topic set in action context."""
    # Submit feedback with rewritten_query (becomes query_hint on action item)
    r_fb = client.post("/feedback", json={
        "question": "How to scale pods?",
        "answer": "Use HPA.",
        "feedback_type": "down",
        "detected_topic": "kubernetes",
        "rewritten_query": "kubernetes pod autoscaling",
    })
    assert r_fb.status_code == 200
    fb_id = r_fb.json()["id"]

    client.post(f"/admin/feedback/{fb_id}/review",
                json={"review_status": "reviewed", "root_cause": "retrieval_miss"})
    r_action = client.post(f"/admin/feedback/{fb_id}/action-item")
    assert r_action.status_code == 200
    action = r_action.json()
    assert action["query_hint"] == "kubernetes pod autoscaling"

    r = client.post(f"/admin/feedback-actions/{action['id']}/execute")
    assert r.status_code == 200
    data = r.json()
    assert data["execution_status"] == "executed"

    # Coverage gap question should use the query_hint
    import orchestrator.coverage_gap_store as cgs
    gap = cgs.get_gap(data["execution_result"]["coverage_gap_id"])
    assert gap["question"] == "kubernetes pod autoscaling"
    assert gap["rewritten_query"] == "kubernetes pod autoscaling"
    assert gap["detected_topic"] == "kubernetes"


def test_execute_create_coverage_gap_no_context_uses_fallback(client):
    """create_coverage_gap with no topic/hint still succeeds via fallback question."""
    action = _create_action_item(client, root_cause="retrieval_miss")  # no topic
    action_id = action["id"]

    r = client.post(f"/admin/feedback-actions/{action_id}/execute")
    assert r.status_code == 200
    assert r.json()["execution_status"] == "executed"

    import orchestrator.coverage_gap_store as cgs
    gap_id = r.json()["execution_result"]["coverage_gap_id"]
    gap = cgs.get_gap(gap_id)
    assert gap is not None
    assert gap["question"]  # some fallback question was set


def test_execute_recrawl_blocked_no_topic(client):
    """recrawl_source with no detected_topic → blocked with clear reason."""
    action = _create_action_item(client, root_cause="stale_source_mix", topic=None)
    action_id = action["id"]

    r = client.post(f"/admin/feedback-actions/{action_id}/execute")
    assert r.status_code == 200
    data = r.json()

    assert data["execution_status"] == "blocked"
    assert data["execution_type"] == "recrawl"
    result = data["execution_result"]
    assert "topic" in result["reason"].lower() or "detected_topic" in result["reason"].lower()


def test_execute_recrawl_blocked_no_sources_file(client):
    """recrawl_source with topic but no sources/<topic>.json → blocked."""
    action = _create_action_item(
        client, root_cause="stale_source_mix", topic="nonexistent_topic"
    )
    r = client.post(f"/admin/feedback-actions/{action['id']}/execute")
    assert r.status_code == 200
    data = r.json()

    assert data["execution_status"] == "blocked"
    assert "nonexistent_topic" in data["execution_result"]["reason"]


def test_execute_recrawl_success(client, tmp_path):
    """recrawl_source with topic + sources file + mocked pipeline → executed."""
    # Seed a topic sources file
    sources_items = [
        {"location": "https://k8s.io/docs", "topic": "kubernetes", "title": "K8s docs", "source": "website"}
    ]
    (tmp_path / "sources" / "kubernetes.json").write_text(json.dumps(sources_items))

    action = _create_action_item(client, root_cause="stale_source_mix", topic="kubernetes")
    action_id = action["id"]

    fake_docs = [{"id": "d1", "title": "T", "content": "c", "topic": "kubernetes", "url": "u"}]
    fake_chunks = [{"chunk_id": "d1-1", "doc_id": "d1", "title": "T", "content": "c", "topic": "kubernetes"}]

    with patch("crawler.fetch_data.crawl_sources", return_value=fake_docs), \
         patch("processor.chunker.process_documents", return_value=fake_chunks), \
         patch("processor.embedder.embed_and_store"):
        r = client.post(f"/admin/feedback-actions/{action_id}/execute")

    assert r.status_code == 200
    data = r.json()

    assert data["execution_status"] == "executed"
    assert data["execution_type"] == "recrawl"
    assert data["executed_at"] is not None

    result = data["execution_result"]
    assert result["documents_crawled"] == 1
    assert result["chunks_indexed"] == 1
    assert "recrawled" in result["summary"]

    payload = data["execution_payload"]
    assert payload["topic"] == "kubernetes"
    assert payload["sources_count"] == 1


def test_execute_unsupported_action_blocked(client):
    """improve_retrieval, adjust_prompt, ignore → blocked with clear reason."""
    for root_cause in ("insufficient_context", "hallucination", "other"):
        action = _create_action_item(client, root_cause=root_cause)
        r = client.post(f"/admin/feedback-actions/{action['id']}/execute")
        assert r.status_code == 200
        data = r.json()
        assert data["execution_status"] == "blocked"
        assert "not executable" in data["execution_result"]["reason"]
        assert "MVP" in data["execution_result"]["reason"]


def test_execute_response_contains_all_execution_fields(client):
    """Response always includes all execution metadata fields."""
    action = _create_action_item(client, root_cause="retrieval_miss", topic="kubernetes")
    r = client.post(f"/admin/feedback-actions/{action['id']}/execute")
    assert r.status_code == 200
    data = r.json()

    for field in ("execution_status", "execution_type", "execution_payload",
                  "execution_result", "executed_at"):
        assert field in data, f"Missing field: {field}"


def test_execute_updates_existing_item_status(client):
    """After execute, the action item in the list also shows updated execution_status."""
    action = _create_action_item(client, root_cause="retrieval_miss", topic="k8s")
    action_id = action["id"]

    client.post(f"/admin/feedback-actions/{action_id}/execute")

    r = client.get("/admin/feedback-actions")
    items = {i["id"]: i for i in r.json()["items"]}
    assert items[action_id]["execution_status"] == "executed"


def test_execute_recrawl_empty_sources_file_blocked(client, tmp_path):
    """recrawl_source with empty sources array → blocked."""
    (tmp_path / "sources" / "emptytopic.json").write_text("[]")
    action = _create_action_item(client, root_cause="stale_source_mix", topic="emptytopic")
    r = client.post(f"/admin/feedback-actions/{action['id']}/execute")
    assert r.status_code == 200
    assert r.json()["execution_status"] == "blocked"
    assert "No sources configured" in r.json()["execution_result"]["reason"]
