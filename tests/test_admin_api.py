"""Tests cho api.admin endpoints (TestClient, không gọi crawl thật)."""
from __future__ import annotations

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
