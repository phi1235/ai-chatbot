"""Tests cho coverage gap API endpoints (TestClient)."""
from __future__ import annotations

import importlib
import json
from unittest.mock import patch

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


# ─── POST /admin/coverage-gaps/{id}/action ────────────────────────────────────

def test_action_add_source(client, tmp_path):
    """Action: add_source writes to sources file and marks gap actioned."""
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/action",
        json={
            "resolution": "add_source",
            "action_payload": {
                "topic": "kubernetes",
                "url": "https://k8s.io/docs/deploy",
                "title": "K8s Deploy Guide",
            },
            "review_note": "Added deploy docs",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["gap"]["status"] == "actioned"
    assert data["gap"]["resolution"] == "add_source"
    assert data["gap"]["actioned_at"] is not None
    assert data["gap"]["action_payload"]["url"] == "https://k8s.io/docs/deploy"
    assert data["action_result"]["topic"] == "kubernetes"
    assert data["action_result"]["total"] == 1

    # Verify source file was created
    source_file = tmp_path / "sources" / "kubernetes.json"
    assert source_file.exists()
    items = json.loads(source_file.read_text())
    assert len(items) == 1
    assert items[0]["location"] == "https://k8s.io/docs/deploy"


def test_action_add_source_duplicate(client, tmp_path):
    """add_source with existing URL returns 409."""
    # Pre-populate sources file
    (tmp_path / "sources").mkdir(exist_ok=True)
    items = [{"location": "https://k8s.io/docs", "topic": "tech", "title": "T", "source": "website"}]
    (tmp_path / "sources" / "tech.json").write_text(json.dumps(items))

    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/action",
        json={
            "resolution": "add_source",
            "action_payload": {"topic": "tech", "url": "https://k8s.io/docs"},
        },
    )
    assert r.status_code == 409


def test_action_add_source_missing_url(client):
    """add_source without URL returns 400."""
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/action",
        json={
            "resolution": "add_source",
            "action_payload": {"topic": "tech"},
        },
    )
    assert r.status_code == 400
    assert "url" in r.json()["detail"].lower()


def test_action_add_source_missing_topic(client):
    """add_source without topic returns 400."""
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/action",
        json={
            "resolution": "add_source",
            "action_payload": {"url": "https://example.com"},
        },
    )
    assert r.status_code == 400
    assert "topic" in r.json()["detail"].lower()


def test_action_recrawl_by_topic(client, tmp_path):
    """Action: recrawl by topic calls pipeline and marks gap actioned."""
    # Seed a topic file
    items = [{"location": "https://k8s.io/a", "topic": "kubernetes", "title": "A", "source": "website"}]
    (tmp_path / "sources" / "kubernetes.json").write_text(json.dumps(items))

    gap_id = _seed_gap(client)

    fake_docs = [{"id": "x", "title": "T", "content": "c", "topic": "kubernetes", "url": "u"}]
    fake_chunks = [{"chunk_id": "x-1", "doc_id": "x", "title": "T", "content": "c", "topic": "kubernetes"}]
    with patch("crawler.fetch_data.crawl_sources", return_value=fake_docs), \
         patch("processor.chunker.process_documents", return_value=fake_chunks), \
         patch("processor.embedder.embed_and_store"):
        r = client.post(
            f"/admin/coverage-gaps/{gap_id}/action",
            json={
                "resolution": "recrawl",
                "action_payload": {"topic": "kubernetes"},
                "review_note": "Recrawled K8s topic",
            },
        )

    assert r.status_code == 200
    data = r.json()
    assert data["gap"]["status"] == "actioned"
    assert data["gap"]["resolution"] == "recrawl"
    assert data["gap"]["actioned_at"] is not None
    assert data["action_result"]["documents_crawled"] == 1
    assert data["action_result"]["chunks_indexed"] == 1


def test_action_recrawl_missing_target(client):
    """recrawl without topic or urls returns 400."""
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/action",
        json={
            "resolution": "recrawl",
            "action_payload": {},
        },
    )
    assert r.status_code == 400


def test_action_recrawl_nonexistent_topic(client):
    """recrawl with non-existent topic returns 404."""
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/action",
        json={
            "resolution": "recrawl",
            "action_payload": {"topic": "nonexistent_topic"},
        },
    )
    assert r.status_code == 404


def test_action_invalid_resolution(client):
    """Invalid resolution returns 400."""
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/action",
        json={
            "resolution": "out_of_scope",
            "action_payload": {},
        },
    )
    assert r.status_code == 400


def test_action_gap_not_found(client):
    """Action on non-existent gap returns 404."""
    r = client.post(
        "/admin/coverage-gaps/9999/action",
        json={
            "resolution": "add_source",
            "action_payload": {"topic": "t", "url": "https://x.com"},
        },
    )
    assert r.status_code == 404


def test_action_gap_response_includes_action_payload(client):
    """Verify the gap response includes action_payload and actioned_at fields."""
    gap_id = _seed_gap(client)
    r = client.post(
        f"/admin/coverage-gaps/{gap_id}/action",
        json={
            "resolution": "add_source",
            "action_payload": {
                "topic": "newstuff",
                "url": "https://example.com/new",
            },
        },
    )
    assert r.status_code == 200
    gap = r.json()["gap"]
    assert "action_payload" in gap
    assert "actioned_at" in gap
    assert gap["action_payload"]["url"] == "https://example.com/new"
    assert gap["action_payload"]["result"]["total"] == 1


# ─── Integration: full action flow ───────────────────────────────────────────

def test_full_action_flow(client, tmp_path):
    """Gap detected → admin sees it → admin actions add_source → gap actioned."""
    gap_id = _seed_gap(client)

    # Admin sees it
    r1 = client.get("/admin/coverage-gaps", params={"status": "new"})
    assert r1.json()["count"] == 1

    # Admin actions add_source
    r2 = client.post(
        f"/admin/coverage-gaps/{gap_id}/action",
        json={
            "resolution": "add_source",
            "action_payload": {
                "topic": "kubernetes",
                "url": "https://k8s.io/docs/new-guide",
                "title": "New K8s Guide",
            },
            "review_note": "Added new guide to fill gap",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["gap"]["status"] == "actioned"

    # No longer shows as new
    r3 = client.get("/admin/coverage-gaps", params={"status": "new"})
    assert r3.json()["count"] == 0

    # Shows as actioned
    r4 = client.get("/admin/coverage-gaps", params={"status": "actioned"})
    assert r4.json()["count"] == 1
    item = r4.json()["items"][0]
    assert item["action_payload"]["url"] == "https://k8s.io/docs/new-guide"
    assert item["actioned_at"] is not None

    # Source file was written
    source_file = tmp_path / "sources" / "kubernetes.json"
    assert source_file.exists()
