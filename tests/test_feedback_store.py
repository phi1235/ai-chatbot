"""Unit tests cho orchestrator.feedback_store – test persistence layer."""
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

    import orchestrator.feedback_store as fs
    fs._initialised_paths.clear()
    importlib.reload(fs)


def _store():
    """Import lại sau reload để lấy module đúng."""
    import orchestrator.feedback_store as fs
    return fs


# ─── add_feedback ────────────────────────────────────────────────────────────

def test_add_feedback_returns_id():
    fs = _store()
    fid = fs.add_feedback(
        question="What is Python?",
        answer="A programming language.",
        feedback_type="up",
    )
    assert isinstance(fid, int)
    assert fid > 0


def test_add_feedback_down_with_note():
    fs = _store()
    fid = fs.add_feedback(
        question="Explain Docker",
        answer="Docker is...",
        feedback_type="down",
        session_id="sess-123",
        message_id="msg-1",
        note="Answer too vague",
    )
    record = fs.get_feedback(fid)
    assert record is not None
    assert record["feedback_type"] == "down"
    assert record["note"] == "Answer too vague"
    assert record["session_id"] == "sess-123"
    assert record["message_id"] == "msg-1"
    assert record["reviewed"] is False
    assert record["review_status"] == "pending"


def test_add_feedback_invalid_type_raises():
    fs = _store()
    with pytest.raises(ValueError, match="feedback_type"):
        fs.add_feedback(question="Q", answer="A", feedback_type="neutral")


def test_add_feedback_empty_question_raises():
    fs = _store()
    with pytest.raises(ValueError, match="empty"):
        fs.add_feedback(question="", answer="A", feedback_type="up")


def test_add_feedback_empty_answer_raises():
    fs = _store()
    with pytest.raises(ValueError, match="empty"):
        fs.add_feedback(question="Q", answer="  ", feedback_type="up")


def test_add_feedback_strips_whitespace():
    fs = _store()
    fid = fs.add_feedback(
        question="  Q  ",
        answer="  A  ",
        feedback_type="up",
        session_id="  sid  ",
        note="  n  ",
    )
    record = fs.get_feedback(fid)
    assert record["question"] == "Q"
    assert record["answer"] == "A"
    assert record["session_id"] == "sid"
    assert record["note"] == "n"


def test_add_feedback_sets_created_at():
    fs = _store()
    before = time.time()
    fid = fs.add_feedback(question="Q", answer="A", feedback_type="up")
    after = time.time()
    record = fs.get_feedback(fid)
    assert before <= record["created_at"] <= after


# ─── list_feedbacks ──────────────────────────────────────────────────────────

def test_list_feedbacks_empty():
    fs = _store()
    items = fs.list_feedbacks()
    assert items == []


def test_list_feedbacks_returns_all():
    fs = _store()
    fs.add_feedback(question="Q1", answer="A1", feedback_type="up")
    fs.add_feedback(question="Q2", answer="A2", feedback_type="down")
    items = fs.list_feedbacks()
    assert len(items) == 2


def test_list_feedbacks_down_first():
    """Down feedbacks should appear before up feedbacks."""
    fs = _store()
    fs.add_feedback(question="Q1", answer="A1", feedback_type="up")
    time.sleep(0.01)
    fs.add_feedback(question="Q2", answer="A2", feedback_type="down")
    items = fs.list_feedbacks()
    assert items[0]["feedback_type"] == "down"
    assert items[1]["feedback_type"] == "up"


def test_list_feedbacks_filter_by_type():
    fs = _store()
    fs.add_feedback(question="Q1", answer="A1", feedback_type="up")
    fs.add_feedback(question="Q2", answer="A2", feedback_type="down")
    downs = fs.list_feedbacks(feedback_type="down")
    assert len(downs) == 1
    assert downs[0]["question"] == "Q2"


def test_list_feedbacks_filter_by_reviewed():
    fs = _store()
    fid = fs.add_feedback(question="Q1", answer="A1", feedback_type="down")
    fs.add_feedback(question="Q2", answer="A2", feedback_type="down")
    fs.mark_reviewed(fid)

    unreviewed = fs.list_feedbacks(reviewed=False)
    assert len(unreviewed) == 1
    assert unreviewed[0]["question"] == "Q2"

    reviewed = fs.list_feedbacks(reviewed=True)
    assert len(reviewed) == 1
    assert reviewed[0]["question"] == "Q1"


def test_list_feedbacks_filter_by_session():
    fs = _store()
    fs.add_feedback(question="Q1", answer="A1", feedback_type="up", session_id="s1")
    fs.add_feedback(question="Q2", answer="A2", feedback_type="up", session_id="s2")
    items = fs.list_feedbacks(session_id="s1")
    assert len(items) == 1
    assert items[0]["question"] == "Q1"


def test_list_feedbacks_filter_by_review_status():
    fs = _store()
    fid1 = fs.add_feedback(question="Q1", answer="A1", feedback_type="down")
    fs.add_feedback(question="Q2", answer="A2", feedback_type="down")
    fs.mark_reviewed(fid1, review_status="actioned")

    actioned = fs.list_feedbacks(review_status="actioned")
    assert len(actioned) == 1
    assert actioned[0]["question"] == "Q1"

    pending = fs.list_feedbacks(review_status="pending")
    assert len(pending) == 1
    assert pending[0]["question"] == "Q2"


def test_list_feedbacks_pagination():
    fs = _store()
    for i in range(5):
        fs.add_feedback(question=f"Q{i}", answer=f"A{i}", feedback_type="up")
    items = fs.list_feedbacks(limit=2)
    assert len(items) == 2
    items_offset = fs.list_feedbacks(limit=2, offset=3)
    assert len(items_offset) == 2


# ─── get_feedback ────────────────────────────────────────────────────────────

def test_get_feedback_not_found():
    fs = _store()
    assert fs.get_feedback(999) is None


def test_get_feedback_by_id():
    fs = _store()
    fid = fs.add_feedback(question="Q", answer="A", feedback_type="up")
    record = fs.get_feedback(fid)
    assert record["id"] == fid
    assert record["question"] == "Q"


def test_delete_feedback_existing():
    fs = _store()
    fid = fs.add_feedback(question="Q", answer="A", feedback_type="up")
    assert fs.delete_feedback(fid) is True
    assert fs.get_feedback(fid) is None


def test_delete_feedback_missing():
    fs = _store()
    assert fs.delete_feedback(9999) is False


# ─── mark_reviewed ───────────────────────────────────────────────────────────

def test_mark_reviewed_basic():
    fs = _store()
    fid = fs.add_feedback(question="Q", answer="A", feedback_type="down")
    result = fs.mark_reviewed(fid)
    assert result["reviewed"] is True
    assert result["review_status"] == "reviewed"
    assert result["reviewed_at"] is not None


def test_mark_reviewed_with_note():
    fs = _store()
    fid = fs.add_feedback(question="Q", answer="A", feedback_type="down")
    result = fs.mark_reviewed(fid, review_note="Need better source", review_status="actioned")
    assert result["review_note"] == "Need better source"
    assert result["review_status"] == "actioned"


def test_mark_reviewed_invalid_status_raises():
    fs = _store()
    fid = fs.add_feedback(question="Q", answer="A", feedback_type="down")
    with pytest.raises(ValueError, match="review_status"):
        fs.mark_reviewed(fid, review_status="invalid")


# ─── count_summary ───────────────────────────────────────────────────────────

def test_count_summary_empty():
    fs = _store()
    s = fs.count_summary()
    assert s == {"total": 0, "total_down": 0, "total_up": 0, "down_pending": 0, "reviewed": 0}


def test_count_summary():
    fs = _store()
    fs.add_feedback(question="Q1", answer="A1", feedback_type="up")
    fid2 = fs.add_feedback(question="Q2", answer="A2", feedback_type="down")
    fs.add_feedback(question="Q3", answer="A3", feedback_type="down")
    fs.mark_reviewed(fid2)

    s = fs.count_summary()
    assert s["total"] == 3
    assert s["total_up"] == 1
    assert s["total_down"] == 2
    assert s["down_pending"] == 1
    assert s["reviewed"] == 1
