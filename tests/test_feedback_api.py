"""Tests cho feedback API endpoints (TestClient)."""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Mỗi test có chroma dir + sqlite riêng."""
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
    import api.admin as admin_mod
    importlib.reload(admin_mod)

    from api.main import app
    return TestClient(app)


# ─── POST /feedback (user-facing) ───────────────────────────────────────────

def test_submit_feedback_up(client):
    body = {
        "question": "What is K8s?",
        "answer": "Kubernetes is...",
        "feedback_type": "up",
        "session_id": "sess-1",
    }
    r = client.post("/feedback", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] > 0
    assert data["feedback_type"] == "up"


def test_submit_feedback_down_with_note(client):
    body = {
        "question": "Explain Docker",
        "answer": "Docker is a tool",
        "feedback_type": "down",
        "note": "Too vague",
    }
    r = client.post("/feedback", json=body)
    assert r.status_code == 200
    assert r.json()["feedback_type"] == "down"


def test_submit_feedback_invalid_type(client):
    body = {
        "question": "Q",
        "answer": "A",
        "feedback_type": "neutral",
    }
    r = client.post("/feedback", json=body)
    assert r.status_code == 400


def test_submit_feedback_empty_question(client):
    body = {
        "question": "",
        "answer": "A",
        "feedback_type": "up",
    }
    r = client.post("/feedback", json=body)
    assert r.status_code == 400


def test_submit_feedback_empty_answer(client):
    body = {
        "question": "Q",
        "answer": "  ",
        "feedback_type": "up",
    }
    r = client.post("/feedback", json=body)
    assert r.status_code == 400


# ─── POST /admin/feedback (admin submit — same endpoint) ────────────────────

def test_admin_submit_feedback(client):
    body = {
        "question": "What is FastAPI?",
        "answer": "FastAPI is...",
        "feedback_type": "down",
        "session_id": "sess-admin",
        "message_id": "msg-5",
    }
    r = client.post("/admin/feedback", json=body)
    assert r.status_code == 200
    assert r.json()["id"] > 0


# ─── GET /admin/feedback ─────────────────────────────────────────────────────

def test_list_feedback_empty(client):
    r = client.get("/admin/feedback")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["items"] == []
    assert data["summary"]["total"] == 0


def test_list_feedback_returns_items(client):
    client.post("/feedback", json={
        "question": "Q1", "answer": "A1", "feedback_type": "up",
    })
    client.post("/feedback", json={
        "question": "Q2", "answer": "A2", "feedback_type": "down",
    })
    r = client.get("/admin/feedback")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    # down should be first
    assert data["items"][0]["feedback_type"] == "down"


def test_list_feedback_filter_by_type(client):
    client.post("/feedback", json={"question": "Q1", "answer": "A1", "feedback_type": "up"})
    client.post("/feedback", json={"question": "Q2", "answer": "A2", "feedback_type": "down"})

    r = client.get("/admin/feedback", params={"feedback_type": "down"})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["items"][0]["question"] == "Q2"


def test_list_feedback_filter_invalid_type(client):
    r = client.get("/admin/feedback", params={"feedback_type": "invalid"})
    assert r.status_code == 400


def test_list_feedback_filter_by_review_status(client):
    client.post("/feedback", json={"question": "Q1", "answer": "A1", "feedback_type": "down"})
    r = client.get("/admin/feedback", params={"review_status": "pending"})
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_list_feedback_filter_invalid_review_status(client):
    r = client.get("/admin/feedback", params={"review_status": "xyz"})
    assert r.status_code == 400


def test_list_feedback_includes_summary(client):
    client.post("/feedback", json={"question": "Q1", "answer": "A1", "feedback_type": "up"})
    client.post("/feedback", json={"question": "Q2", "answer": "A2", "feedback_type": "down"})

    r = client.get("/admin/feedback")
    summary = r.json()["summary"]
    assert summary["total"] == 2
    assert summary["total_up"] == 1
    assert summary["total_down"] == 1
    assert summary["down_pending"] == 1


# ─── POST /admin/feedback/{id}/review ────────────────────────────────────────

def test_review_feedback(client):
    r = client.post("/feedback", json={
        "question": "Q1", "answer": "A1", "feedback_type": "down",
    })
    fb_id = r.json()["id"]

    r2 = client.post(
        f"/admin/feedback/{fb_id}/review",
        json={"review_note": "Needs better source", "review_status": "reviewed"},
    )
    assert r2.status_code == 200
    data = r2.json()
    assert data["reviewed"] is True
    assert data["review_note"] == "Needs better source"
    assert data["review_status"] == "reviewed"
    assert data["reviewed_at"] is not None


def test_review_feedback_actioned(client):
    r = client.post("/feedback", json={
        "question": "Q", "answer": "A", "feedback_type": "down",
    })
    fb_id = r.json()["id"]

    r2 = client.post(
        f"/admin/feedback/{fb_id}/review",
        json={"review_status": "actioned"},
    )
    assert r2.status_code == 200
    assert r2.json()["review_status"] == "actioned"


def test_review_feedback_not_found(client):
    r = client.post(
        "/admin/feedback/9999/review",
        json={"review_status": "reviewed"},
    )
    assert r.status_code == 404


def test_review_feedback_invalid_status(client):
    r = client.post("/feedback", json={
        "question": "Q", "answer": "A", "feedback_type": "down",
    })
    fb_id = r.json()["id"]

    r2 = client.post(
        f"/admin/feedback/{fb_id}/review",
        json={"review_status": "invalid"},
    )
    assert r2.status_code == 400


# ─── GET /admin/feedback/summary ─────────────────────────────────────────────

def test_feedback_summary(client):
    client.post("/feedback", json={"question": "Q1", "answer": "A1", "feedback_type": "up"})
    client.post("/feedback", json={"question": "Q2", "answer": "A2", "feedback_type": "down"})

    r = client.get("/admin/feedback/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert data["total_up"] == 1
    assert data["total_down"] == 1
    assert data["down_pending"] == 1
    assert data["reviewed"] == 0


# ─── Integration: full flow ──────────────────────────────────────────────────

def test_full_feedback_flow(client):
    """User submits down feedback -> admin sees it -> admin marks reviewed."""
    # User submits
    r1 = client.post("/feedback", json={
        "question": "How to deploy?",
        "answer": "Use kubectl.",
        "feedback_type": "down",
        "session_id": "test-sess",
        "note": "Not enough detail",
    })
    assert r1.status_code == 200
    fb_id = r1.json()["id"]

    # Admin sees it in queue
    r2 = client.get("/admin/feedback", params={"review_status": "pending"})
    assert r2.status_code == 200
    assert r2.json()["count"] == 1
    item = r2.json()["items"][0]
    assert item["question"] == "How to deploy?"
    assert item["note"] == "Not enough detail"
    assert item["reviewed"] is False

    # Admin marks reviewed
    r3 = client.post(
        f"/admin/feedback/{fb_id}/review",
        json={"review_note": "Added deployment guide to KB", "review_status": "actioned"},
    )
    assert r3.status_code == 200
    assert r3.json()["reviewed"] is True
    assert r3.json()["review_status"] == "actioned"

    # Verify it no longer shows as pending
    r4 = client.get("/admin/feedback", params={"review_status": "pending"})
    assert r4.json()["count"] == 0
