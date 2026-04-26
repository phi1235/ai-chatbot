"""Tests cho orchestrator.store - SQLite persistence."""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Reload settings + store với DB tạm để mỗi test cô lập."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    import config.settings as settings_mod
    import orchestrator.store as store_mod

    importlib.reload(settings_mod)
    importlib.reload(store_mod)
    return store_mod


def test_create_and_list_session(store):
    store.ensure_session("s1")
    store.add_message("s1", "user", "hello")
    sessions = store.list_sessions()
    assert any(s["id"] == "s1" for s in sessions)


def test_session_with_no_messages_not_listed(store):
    store.ensure_session("empty")
    sessions = store.list_sessions()
    # ensure_session tạo nhưng không có message → không list
    assert not any(s["id"] == "empty" for s in sessions)


def test_add_message_increments_count(store):
    store.add_message("s1", "user", "q1")
    store.add_message("s1", "assistant", "a1")
    store.add_message("s1", "user", "q2")
    assert store.session_message_count("s1") == 3


def test_get_messages_in_order(store):
    store.add_message("s1", "user", "first")
    store.add_message("s1", "assistant", "second")
    store.add_message("s1", "user", "third")
    msgs = store.get_messages("s1")
    contents = [m["content"] for m in msgs]
    assert contents == ["first", "second", "third"]


def test_get_messages_with_citations_and_trace(store):
    citations = [{"title": "Doc", "url": "u", "section": "", "source": "", "score": 0.9}]
    trace = {"request_id": "r1", "latency_ms": 12.3}
    store.add_message(
        "s1",
        "assistant",
        "answer",
        citations=citations,
        show_citations=True,
        trace=trace,
    )
    msgs = store.get_messages("s1")
    assert msgs[0]["citations"] == citations
    assert msgs[0]["trace"] == trace
    assert msgs[0]["show_citations"] is True


def test_get_recent_turns_limits_to_n(store):
    for i in range(15):
        store.add_message("s1", "user" if i % 2 == 0 else "assistant", f"m{i}")
    turns = store.get_recent_turns("s1", max_turns=5)
    assert len(turns) == 5
    assert turns[-1]["content"] == "m14"


def test_update_title(store):
    store.add_message("s1", "user", "x")
    store.update_title("s1", "New Title")
    sessions = store.list_sessions()
    s = next(s for s in sessions if s["id"] == "s1")
    assert s["title"] == "New Title"


def test_delete_session_cascades_messages(store):
    store.add_message("s1", "user", "x")
    store.add_message("s1", "assistant", "y")
    store.delete_session("s1")
    assert store.session_message_count("s1") == 0
    sessions = store.list_sessions()
    assert not any(s["id"] == "s1" for s in sessions)


def test_auto_title_truncates_long_content():
    from orchestrator.store import auto_title_from_first_message

    long_text = "Đây là một câu hỏi rất rất dài " * 10
    title = auto_title_from_first_message(long_text)
    assert len(title) <= 64
    assert title.endswith("…") or len(title) < 64


def test_auto_title_handles_empty():
    from orchestrator.store import auto_title_from_first_message

    assert auto_title_from_first_message("") == "Cuộc trò chuyện mới"
