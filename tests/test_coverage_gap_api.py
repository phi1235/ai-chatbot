"""Tests cho coverage gap API endpoints (TestClient)."""
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
    import orchestrator.coverage_gap_store as cgs_mod
    cgs_mod._initialised_paths.clear()
    importlib.reload(cgs_mod)
    import api.admin as admin_mod
    importlib.reload(admin_mod)

    from api.main import app
    return TestClient(app)


def _seed_gap(client) -> int:
    """Seed a coverage gap directly via the store and return its id."""
    import orchestrator.coverage_gap_store as cgs
    return cgs.add_gap(
        question="How to deploy pods?",
        answer_excerpt="Tôi chưa tìm thấy thông tin đủ liên quan.",
        retrieval_count=0,
        gap_signals=["no_retrieval", "fallback_answer"],
        citations_snapshot=[],
        session_id="sess-1",
        detected_topic="kubernetes",
    )


# ─── GET /admin/coverage-gaps ────────────────────────────────────────────────

def test_list_coverage_gaps_empty(client):
    r = client.get("/admin/coverage-gaps")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["items"] == []
    assert data["summary"]["total"] == 0


def test_list_coverage_gaps_returns_items(client):
    _seed_gap(client)
    r = client.get("/admin/coverage-gaps")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    item = data["items"][0]
    assert item["question"] == "How to deploy pods?"
    assert item["status"] == "new"
    assert "no_retrieval" in item["gap_signals"]


def test_list_coverage_gaps_filter_by_status(client):
    gap_id = _seed_gap(client)
    import orchestrator.coverage_gap_store as cgs
    cgs.review_gap(gap_id, status="actioned", resolution="add_source")

    r = client.get("/admin/coverage-gaps", params={"status": "actioned"})
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r2 = client.get("/admin/coverage-gaps", params={"status": "new"})
    assert r2.json()["count"] == 0


def test_list_coverage_gaps_filter_by_topic(client):
    _seed_gap(client)  # kubernetes topic
    r = client.get("/admin/coverage-gaps", params={"detected_topic": "kubernetes"})
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r2 = client.get("/admin/coverage-gaps", params={"detected_topic": "docker"})
    assert r2.json()["count"] == 0


def test_list_coverage_gaps_invalid_status(client):
    r = client.get("/admin/coverage-gaps", params={"status": "invalid"})
    assert r.status_code == 400


def test_list_coverage_gaps_includes_summary(client):
    _seed_gap(client)
    r = client.get("/admin/coverage-gaps")
    summary = r.json()["summary"]
    assert summary["total"] == 1
    assert summary["total_new"] == 1


# ─── POST /admin/coverage-gaps/{id}/review ───────────────────────────────────

def test_review_coverage_gap(client):
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/review",
        json={
            "status": "actioned",
            "resolution": "add_source",
            "review_note": "Need K8s deploy docs",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "actioned"
    assert data["resolution"] == "add_source"
    assert data["review_note"] == "Need K8s deploy docs"
    assert data["reviewed_at"] is not None


def test_review_coverage_gap_ignored(client):
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/review",
        json={"status": "ignored", "resolution": "out_of_scope"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
    assert r.json()["resolution"] == "out_of_scope"


def test_review_coverage_gap_not_found(client):
    r = client.post(
        "/admin/coverage-gaps/9999/review",
        json={"status": "reviewed"},
    )
    assert r.status_code == 404


def test_review_coverage_gap_invalid_status(client):
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/review",
        json={"status": "invalid"},
    )
    assert r.status_code == 400


def test_review_coverage_gap_invalid_resolution(client):
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/review",
        json={"status": "reviewed", "resolution": "not_a_valid_resolution"},
    )
    assert r.status_code == 400


# ─── GET /admin/coverage-gaps/summary ────────────────────────────────────────

def test_coverage_gaps_summary(client):
    _seed_gap(client)
    r = client.get("/admin/coverage-gaps/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["total_new"] == 1
    assert data["by_topic"]["kubernetes"] == 1


# ─── Integration: full flow ──────────────────────────────────────────────────

def test_full_coverage_gap_flow(client):
    """Gap detected → admin sees it → admin marks actioned with resolution."""
    # Gap is detected (seeded directly)
    gap_id = _seed_gap(client)

    # Admin sees it in queue
    r1 = client.get("/admin/coverage-gaps", params={"status": "new"})
    assert r1.status_code == 200
    assert r1.json()["count"] == 1
    item = r1.json()["items"][0]
    assert item["question"] == "How to deploy pods?"
    assert item["detected_topic"] == "kubernetes"

    # Admin marks actioned
    r2 = client.post(
        f"/admin/coverage-gaps/{gap_id}/review",
        json={
            "status": "actioned",
            "resolution": "add_source",
            "review_note": "Added K8s deployment guide",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "actioned"

    # Verify it no longer shows as new
    r3 = client.get("/admin/coverage-gaps", params={"status": "new"})
    assert r3.json()["count"] == 0

    # But shows as actioned
    r4 = client.get("/admin/coverage-gaps", params={"status": "actioned"})
    assert r4.json()["count"] == 1
