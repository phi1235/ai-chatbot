"""Unit tests cho orchestrator.freshness_store – trực tiếp test persistence layer."""
from __future__ import annotations

import importlib
import time

import pytest


@pytest.fixture(autouse=True)
def _fresh_store(tmp_path, monkeypatch):
    """Mỗi test dùng DB riêng trong tmp_path."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))

    import config.settings as settings_mod
    importlib.reload(settings_mod)

    import orchestrator.freshness_store as fs
    fs._initialised_paths.clear()
    importlib.reload(fs)


def _store():
    """Import lại sau reload để lấy module đúng."""
    import orchestrator.freshness_store as fs
    return fs


# ─── save_many ──────────────────────────────────────────────────────────────

def test_save_many_returns_count():
    fs = _store()
    count = fs.save_many([
        {"url": "https://a.com", "status": "OK", "checked_at": 1000.0},
        {"url": "https://b.com", "status": "DEAD", "checked_at": 1000.0},
    ])
    assert count == 2


def test_save_many_empty_list():
    fs = _store()
    assert fs.save_many([]) == 0


def test_save_many_skips_records_without_url():
    fs = _store()
    count = fs.save_many([
        {"url": "", "status": "OK"},
        {"url": "   ", "status": "OK"},
        {"status": "OK"},
        {"url": "https://valid.com", "status": "OK"},
    ])
    assert count == 1


def test_save_many_normalizes_unknown_to_error():
    fs = _store()
    fs.save_many([
        {"url": "https://u.com", "status": "UNKNOWN", "checked_at": 1.0},
    ])
    rows = fs.list_latest()
    assert len(rows) == 1
    assert rows[0]["status"] == "ERROR"
    assert rows[0]["raw_status"] == "UNKNOWN"


def test_save_many_strips_whitespace():
    fs = _store()
    fs.save_many([
        {"url": "  https://x.com  ", "topic": "  tech  ", "status": "OK",
         "notes": "  note  ", "error_message": "  err  ", "final_url": "  f  "},
    ])
    rows = fs.list_latest()
    assert rows[0]["url"] == "https://x.com"
    assert rows[0]["topic"] == "tech"
    assert rows[0]["notes"] == "note"
    assert rows[0]["error_message"] == "err"
    assert rows[0]["final_url"] == "f"


def test_save_many_defaults_checked_at_to_now():
    fs = _store()
    before = time.time()
    fs.save_many([{"url": "https://t.com", "status": "OK"}])
    after = time.time()
    rows = fs.list_latest()
    assert before <= rows[0]["checked_at"] <= after


def test_save_many_preserves_http_status():
    fs = _store()
    fs.save_many([{"url": "https://h.com", "status": "DEAD", "http_status": 404}])
    rows = fs.list_latest()
    assert rows[0]["http_status"] == 404


def test_save_many_null_topic():
    fs = _store()
    fs.save_many([{"url": "https://n.com", "status": "OK"}])
    rows = fs.list_latest()
    assert rows[0]["topic"] is None


# ─── list_latest ────────────────────────────────────────────────────────────

def test_list_latest_empty_db():
    fs = _store()
    rows = fs.list_latest()
    assert rows == []


def test_list_latest_returns_only_most_recent_per_url_topic():
    """Nếu 1 URL được check 2 lần, chỉ bản mới nhất được trả."""
    fs = _store()
    fs.save_many([
        {"url": "https://a.com", "topic": "t", "status": "STALE", "checked_at": 100.0},
        {"url": "https://a.com", "topic": "t", "status": "OK", "checked_at": 200.0},
    ])
    rows = fs.list_latest()
    assert len(rows) == 1
    assert rows[0]["status"] == "OK"
    assert rows[0]["checked_at"] == 200.0


def test_list_latest_filter_by_status():
    fs = _store()
    fs.save_many([
        {"url": "https://ok.com", "status": "OK", "checked_at": 1.0},
        {"url": "https://dead.com", "status": "DEAD", "checked_at": 1.0},
        {"url": "https://stale.com", "status": "STALE", "checked_at": 1.0},
    ])
    dead_only = fs.list_latest(status="DEAD")
    assert len(dead_only) == 1
    assert dead_only[0]["url"] == "https://dead.com"


def test_list_latest_filter_by_topic():
    fs = _store()
    fs.save_many([
        {"url": "https://a.com", "topic": "k8s", "status": "OK", "checked_at": 1.0},
        {"url": "https://b.com", "topic": "react", "status": "OK", "checked_at": 1.0},
    ])
    rows = fs.list_latest(topic="k8s")
    assert len(rows) == 1
    assert rows[0]["url"] == "https://a.com"


def test_list_latest_filter_status_and_topic():
    fs = _store()
    fs.save_many([
        {"url": "https://a.com", "topic": "k8s", "status": "OK", "checked_at": 1.0},
        {"url": "https://b.com", "topic": "k8s", "status": "DEAD", "checked_at": 1.0},
        {"url": "https://c.com", "topic": "react", "status": "DEAD", "checked_at": 1.0},
    ])
    rows = fs.list_latest(status="DEAD", topic="k8s")
    assert len(rows) == 1
    assert rows[0]["url"] == "https://b.com"


def test_list_latest_ordering_prioritises_errors():
    """DEAD > ERROR > STALE > REDIRECT > OK."""
    fs = _store()
    fs.save_many([
        {"url": "https://ok.com", "status": "OK", "checked_at": 1.0},
        {"url": "https://dead.com", "status": "DEAD", "checked_at": 1.0},
        {"url": "https://stale.com", "status": "STALE", "checked_at": 1.0},
        {"url": "https://redir.com", "status": "REDIRECT", "checked_at": 1.0},
        {"url": "https://err.com", "status": "UNKNOWN", "checked_at": 1.0},
    ])
    rows = fs.list_latest()
    statuses = [r["status"] for r in rows]
    assert statuses == ["DEAD", "ERROR", "STALE", "REDIRECT", "OK"]


def test_list_latest_pagination_limit():
    fs = _store()
    fs.save_many([
        {"url": f"https://{i}.com", "status": "OK", "checked_at": float(i)}
        for i in range(5)
    ])
    rows = fs.list_latest(limit=2)
    assert len(rows) == 2


def test_list_latest_pagination_offset():
    fs = _store()
    fs.save_many([
        {"url": f"https://{i}.com", "status": "OK", "checked_at": float(i)}
        for i in range(5)
    ])
    all_rows = fs.list_latest(limit=100)
    offset_rows = fs.list_latest(limit=100, offset=2)
    assert len(offset_rows) == 3
    assert offset_rows[0]["url"] == all_rows[2]["url"]


def test_list_latest_limit_capped_at_2000():
    """Limit > 2000 should be capped."""
    fs = _store()
    fs.save_many([{"url": "https://a.com", "status": "OK", "checked_at": 1.0}])
    # Should not error even with huge limit
    rows = fs.list_latest(limit=99999)
    assert len(rows) == 1


def test_list_latest_unknown_status_normalised_in_filter():
    """Filtering by UNKNOWN should actually find ERROR records."""
    fs = _store()
    fs.save_many([
        {"url": "https://e.com", "status": "UNKNOWN", "checked_at": 1.0},
        {"url": "https://ok.com", "status": "OK", "checked_at": 1.0},
    ])
    rows = fs.list_latest(status="UNKNOWN")
    assert len(rows) == 1
    assert rows[0]["status"] == "ERROR"


def test_list_latest_same_url_different_topics_kept_separate():
    """Same URL under different topics should be separate records."""
    fs = _store()
    fs.save_many([
        {"url": "https://shared.com", "topic": "k8s", "status": "OK", "checked_at": 1.0},
        {"url": "https://shared.com", "topic": "react", "status": "DEAD", "checked_at": 1.0},
    ])
    rows = fs.list_latest()
    assert len(rows) == 2
    url_status = {r["topic"]: r["status"] for r in rows}
    assert url_status["k8s"] == "OK"
    assert url_status["react"] == "DEAD"


# ─── edge: all statuses stored correctly ────────────────────────────────────

@pytest.mark.parametrize("status", ["OK", "STALE", "DEAD", "REDIRECT"])
def test_save_and_read_each_status(status):
    fs = _store()
    fs.save_many([{"url": f"https://{status.lower()}.com", "status": status, "checked_at": 1.0}])
    rows = fs.list_latest()
    assert len(rows) == 1
    assert rows[0]["status"] == status
