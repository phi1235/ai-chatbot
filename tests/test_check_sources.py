"""Tests cho tools.check_sources - không gọi network thật."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root + tools to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools"
for p in (str(PROJECT_ROOT), str(TOOLS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def cs():
    """Import (or reload) check_sources module fresh."""
    if "check_sources" in sys.modules:
        return importlib.reload(sys.modules["check_sources"])
    return importlib.import_module("check_sources")


def test_content_hash_normalizes_whitespace(cs):
    """Khoảng trắng dư không làm hash khác."""
    a = cs._content_hash("hello world")
    b = cs._content_hash("hello  \n\n world  ")
    assert a == b


def test_content_hash_detects_real_change(cs):
    a = cs._content_hash("hello world")
    b = cs._content_hash("hello there")
    assert a != b


def test_check_one_local_file_exists(cs, tmp_path, monkeypatch):
    f = tmp_path / "doc.md"
    f.write_text("content")
    spec = {"location": str(f), "topic": "x", "title": "T"}
    r = cs._check_one(spec)
    assert r.status == "OK"


def test_check_one_local_file_missing(cs):
    spec = {"location": "/nonexistent/path/file.md", "topic": "x", "title": "T"}
    r = cs._check_one(spec)
    assert r.status == "DEAD"


def test_check_one_url_404(cs):
    """Mock HEAD trả 404 → DEAD."""
    spec = {"location": "https://example.com/missing", "topic": "x", "title": "T"}

    fake_resp = MagicMock(status_code=404, headers={})
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.head.return_value = fake_resp

    with patch.object(cs.httpx, "Client", return_value=fake_client):
        r = cs._check_one(spec)
    assert r.status == "DEAD"
    assert r.http_status == 404


def test_check_one_url_redirect(cs):
    spec = {"location": "https://example.com/old", "topic": "x", "title": "T"}

    fake_resp = MagicMock(status_code=301, headers={"location": "/new-path"})
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.head.return_value = fake_resp

    with patch.object(cs.httpx, "Client", return_value=fake_client):
        r = cs._check_one(spec)
    assert r.status == "REDIRECT"
    assert r.final_url == "/new-path"


def test_check_one_network_error(cs):
    spec = {"location": "https://example.com/", "topic": "x", "title": "T"}

    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.head.side_effect = Exception("connection refused")

    with patch.object(cs.httpx, "Client", return_value=fake_client):
        r = cs._check_one(spec)
    assert r.status == "UNKNOWN"
    assert "connection refused" in r.detail


def test_load_sources_filters_topic(cs, tmp_path, monkeypatch):
    sdir = tmp_path / "sources"
    sdir.mkdir()
    (sdir / "topic_a.json").write_text('[{"location":"u1","topic":"a","title":"T"}]')
    (sdir / "topic_b.json").write_text('[{"location":"u2","topic":"b","title":"T"}]')
    monkeypatch.setattr(cs, "SOURCES_DIR", sdir)

    a_only = cs.load_sources(topic="topic_a")
    assert len(a_only) == 1
    assert a_only[0]["location"] == "u1"

    all_sources = cs.load_sources()
    assert len(all_sources) == 2
