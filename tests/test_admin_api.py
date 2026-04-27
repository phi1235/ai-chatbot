"""Tests cho api.admin endpoints (TestClient, không gọi crawl thật)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Mỗi test có sources dir + chroma dir + sqlite riêng."""
    import importlib

    sources = tmp_path / "sources"
    sources.mkdir()
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.chdir(tmp_path)

    # Reload theo thứ tự dependency để pick up env mới
    import config.settings as settings_mod
    importlib.reload(settings_mod)
    import orchestrator.store as store_mod
    importlib.reload(store_mod)
    import orchestrator.freshness_store as fs_mod
    fs_mod._initialised_paths.clear()
    importlib.reload(fs_mod)
    import api.admin as admin_mod
    importlib.reload(admin_mod)

    from api.main import app
    return TestClient(app)


def test_list_sources_empty(client):
    r = client.get("/admin/sources")
    assert r.status_code == 200
    assert r.json()["topics"] == []


def test_add_source_creates_file(client, tmp_path):
    body = {"location": "https://example.com/a", "topic": "tech", "title": "Page A"}
    r = client.post("/admin/sources/tech", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["topic"] == "tech"
    assert data["total"] == 1
    assert (tmp_path / "sources" / "tech.json").exists()


def test_add_source_dedupes(client):
    body = {"location": "https://example.com/a", "topic": "tech", "title": "T"}
    client.post("/admin/sources/tech", json=body)
    r = client.post("/admin/sources/tech", json=body)
    assert r.status_code == 409


def test_delete_source(client):
    body = {"location": "https://example.com/a", "topic": "tech", "title": "T"}
    client.post("/admin/sources/tech", json=body)
    r = client.request(
        "DELETE", "/admin/sources/tech", json={"location": "https://example.com/a"},
    )
    assert r.status_code == 200
    assert r.json()["remaining"] == 0


def test_delete_source_missing_topic(client):
    r = client.request(
        "DELETE", "/admin/sources/nonexistent", json={"location": "x"},
    )
    assert r.status_code == 404


def test_delete_source_missing_url(client):
    body = {"location": "https://example.com/a", "topic": "tech", "title": "T"}
    client.post("/admin/sources/tech", json=body)
    r = client.request(
        "DELETE", "/admin/sources/tech", json={"location": "https://other.com/x"},
    )
    assert r.status_code == 404


def test_ingest_requires_topic_or_urls(client):
    r = client.post("/admin/ingest", json={})
    assert r.status_code == 400


def test_ingest_with_urls_calls_pipeline(client):
    """Mock crawl_sources + chunk + embed để khỏi gọi mạng."""
    fake_docs = [{"id": "x", "title": "T", "content": "c", "topic": "t", "url": "u"}]
    fake_chunks = [{"chunk_id": "x-1", "doc_id": "x", "title": "T", "content": "c", "topic": "t"}]

    with patch("crawler.fetch_data.crawl_sources", return_value=fake_docs) as mock_crawl, \
         patch("processor.chunker.process_documents", return_value=fake_chunks) as mock_chunk, \
         patch("processor.embedder.embed_and_store") as mock_embed:
        body = {
            "urls": [{"location": "https://x.com", "topic": "t", "title": "T"}],
            "reset": False,
        }
        r = client.post("/admin/ingest", json=body)

    assert r.status_code == 200
    data = r.json()
    assert data["sources_count"] == 1
    assert data["documents_crawled"] == 1
    assert data["chunks_indexed"] == 1
    mock_crawl.assert_called_once()
    mock_chunk.assert_called_once()
    mock_embed.assert_called_once()


def test_ingest_reset_via_http_blocked(client):
    """Reset KB qua HTTP bị từ chối (403) - chỉ cho phép qua CLI."""
    body = {"topic": "anything", "reset": True}
    r = client.post("/admin/ingest", json=body)
    assert r.status_code == 403
    assert "destructive" in r.json()["detail"].lower() or "an toàn" in r.json()["detail"]


def test_stats_returns_structure(client):
    r = client.get("/admin/stats")
    assert r.status_code == 200
    data = r.json()
    assert "chunks" in data
    assert "bm25" in data
    assert "cache" in data
    assert "sessions" in data
    assert "metrics" in data


def test_clear_cache(client):
    r = client.post("/admin/cache/clear")
    assert r.status_code == 200
    assert r.json()["cleared"] is True


def test_health_check_with_empty_sources(client):
    """Health check với sources rỗng phải không crash."""
    r = client.post("/admin/health-check", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0


def test_health_check_persists_snapshot_and_list_freshness(client):
    summary = SimpleNamespace(
        total=2,
        ok=1,
        stale=0,
        dead=0,
        redirect=0,
        unknown=1,
        results=[
            SimpleNamespace(
                location="https://example.com/ok",
                topic="tech",
                title="OK",
                status="OK",
                detail="Không đổi",
                final_url=None,
                http_status=200,
                diff_chars=None,
            ),
            SimpleNamespace(
                location="https://example.com/err",
                topic="tech",
                title="ERR",
                status="UNKNOWN",
                detail="timeout",
                final_url=None,
                http_status=None,
                diff_chars=None,
            ),
        ],
    )
    with patch("check_sources.check_sources", return_value=summary):
        r = client.post("/admin/health-check", json={"topic": "tech"})
    assert r.status_code == 200
    assert r.json()["snapshot_saved"] == 2

    r2 = client.get("/admin/freshness")
    assert r2.status_code == 200
    data = r2.json()
    assert data["count"] == 2
    statuses = {rec["url"]: rec["status"] for rec in data["records"]}
    assert statuses["https://example.com/ok"] == "OK"
    assert statuses["https://example.com/err"] == "ERROR"

    r3 = client.get("/admin/freshness", params={"status": "ERROR", "topic": "tech"})
    assert r3.status_code == 200
    assert r3.json()["count"] == 1
    assert r3.json()["records"][0]["url"] == "https://example.com/err"
    assert r3.json()["records"][0]["error_message"] == "timeout"


def test_list_freshness_invalid_status(client):
    r = client.get("/admin/freshness", params={"status": "INVALID"})
    assert r.status_code == 400


def test_batch_recrawl_selected_urls(client, tmp_path):
    items = [
        {"location": "https://x.com/a", "topic": "tech", "title": "A", "source": "website"},
        {"location": "https://x.com/b", "topic": "tech", "title": "B", "source": "website"},
    ]
    (tmp_path / "sources" / "tech.json").write_text(json.dumps(items), encoding="utf-8")

    fake_docs = [{"id": "x", "title": "T", "content": "c", "topic": "tech", "url": "u"}]
    fake_chunks = [{"chunk_id": "x-1", "doc_id": "x", "title": "T", "content": "c", "topic": "tech"}]
    with patch("crawler.fetch_data.crawl_sources", return_value=fake_docs) as mock_crawl, \
         patch("processor.chunker.process_documents", return_value=fake_chunks) as mock_chunk, \
         patch("processor.embedder.embed_and_store") as mock_embed:
        r = client.post(
            "/admin/freshness/recrawl",
            json={"urls": ["https://x.com/a", "https://x.com/a", "https://x.com/missing"]},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["requested_count"] == 2
    assert data["selected_count"] == 1
    assert data["missing_count"] == 1
    assert data["missing_urls"] == ["https://x.com/missing"]
    assert data["documents_crawled"] == 1
    assert data["chunks_indexed"] == 1
    mock_crawl.assert_called_once_with([items[0]])
    mock_chunk.assert_called_once()
    mock_embed.assert_called_once()


def test_batch_recrawl_requires_known_urls(client):
    r = client.post("/admin/freshness/recrawl", json={"urls": ["https://not-found.com"]})
    assert r.status_code == 404


def test_batch_recrawl_empty_urls(client):
    """Empty URL list should be rejected."""
    r = client.post("/admin/freshness/recrawl", json={"urls": []})
    assert r.status_code == 400


def test_batch_recrawl_whitespace_only_urls(client):
    """Whitespace-only URLs should be stripped and treated as empty."""
    r = client.post("/admin/freshness/recrawl", json={"urls": ["  ", ""]})
    assert r.status_code == 400


def test_freshness_list_pagination(client):
    """Freshness list should respect limit and offset."""
    summary = SimpleNamespace(
        total=3, ok=3, stale=0, dead=0, redirect=0, unknown=0,
        results=[
            SimpleNamespace(
                location=f"https://example.com/{i}",
                topic="tech", title=f"P{i}", status="OK",
                detail="ok", final_url=None, http_status=200, diff_chars=None,
            )
            for i in range(3)
        ],
    )
    with patch("check_sources.check_sources", return_value=summary):
        client.post("/admin/health-check", json={})

    r = client.get("/admin/freshness", params={"limit": 2, "offset": 0})
    assert r.status_code == 200
    assert r.json()["count"] == 2

    r2 = client.get("/admin/freshness", params={"limit": 2, "offset": 2})
    assert r2.status_code == 200
    assert r2.json()["count"] == 1


def test_health_check_snapshot_saved_zero_when_empty(client):
    """Health check with no sources should save 0 records."""
    r = client.post("/admin/health-check", json={})
    assert r.status_code == 200
    assert r.json()["snapshot_saved"] == 0
