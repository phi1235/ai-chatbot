"""Tests for feedback action queue API endpoints (TestClient)."""
from __future__ import annotations

import importlib

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
