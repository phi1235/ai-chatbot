"""Unit tests for orchestrator.feedback_action_store."""
from __future__ import annotations

import importlib
import time

import pytest


@pytest.fixture(autouse=True)
def _fresh_store(tmp_path, monkeypatch):
    """Each test gets its own isolated DB."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))

    import config.settings as settings_mod
    importlib.reload(settings_mod)

    import orchestrator.feedback_action_store as fas
    fas._initialised_paths.clear()
    importlib.reload(fas)


def _store():
    import orchestrator.feedback_action_store as fas
    return fas


# ─── Heuristic mapping ────────────────────────────────────────────────────────

def test_suggested_action_for_known_root_causes():
    fas = _store()
    assert fas.suggested_action_for("retrieval_miss") == "create_coverage_gap"
    assert fas.suggested_action_for("true_coverage_gap") == "create_coverage_gap"
    assert fas.suggested_action_for("stale_source_mix") == "recrawl_source"
    assert fas.suggested_action_for("insufficient_context") == "improve_retrieval"
    assert fas.suggested_action_for("bad_citation_fit") == "improve_retrieval"
    assert fas.suggested_action_for("wrong_answer_from_context") == "adjust_prompt"
    assert fas.suggested_action_for("hallucination") == "adjust_prompt"
    assert fas.suggested_action_for("other") == "ignore"


def test_suggested_action_for_none_returns_ignore():
    fas = _store()
    assert fas.suggested_action_for(None) == "ignore"


def test_suggested_action_for_unknown_returns_ignore():
    fas = _store()
    assert fas.suggested_action_for("nonexistent_cause") == "ignore"


# ─── create_action_item ───────────────────────────────────────────────────────

def test_create_action_item_basic():
    fas = _store()
    item = fas.create_action_item(
        feedback_id=1,
        root_cause="retrieval_miss",
        detected_topic="kubernetes",
        query_hint="scaling pods",
    )
    assert item["id"] > 0
    assert item["feedback_id"] == 1
    assert item["root_cause"] == "retrieval_miss"
    assert item["detected_topic"] == "kubernetes"
    assert item["suggested_action"] == "create_coverage_gap"
    assert item["status"] == "pending"
    assert item["query_hint"] == "scaling pods"
    assert item["reason"]  # non-empty default reason
    assert item["owner_note"] == ""
    assert item["created_at"] > 0
    assert item["updated_at"] > 0


def test_create_action_item_no_root_cause():
    fas = _store()
    item = fas.create_action_item(feedback_id=2)
    assert item["suggested_action"] == "ignore"
    assert item["status"] == "pending"


def test_create_action_item_with_custom_reason():
    fas = _store()
    item = fas.create_action_item(
        feedback_id=3,
        root_cause="hallucination",
        reason="Custom reason text",
    )
    assert item["reason"] == "Custom reason text"


def test_create_action_item_returns_persisted_record():
    fas = _store()
    item = fas.create_action_item(feedback_id=10, root_cause="stale_source_mix")
    fetched = fas.get_action_item(item["id"])
    assert fetched is not None
    assert fetched["id"] == item["id"]
    assert fetched["suggested_action"] == "recrawl_source"


# ─── Duplicate-active protection ─────────────────────────────────────────────

def test_create_duplicate_active_raises():
    fas = _store()
    fas.create_action_item(feedback_id=5, root_cause="retrieval_miss")
    with pytest.raises(ValueError, match="active action item"):
        fas.create_action_item(feedback_id=5, root_cause="hallucination")


def test_create_allowed_after_done():
    fas = _store()
    item1 = fas.create_action_item(feedback_id=5, root_cause="retrieval_miss")
    fas.update_action_status(item1["id"], status="done")
    # Now a new one can be created
    item2 = fas.create_action_item(feedback_id=5, root_cause="hallucination")
    assert item2["id"] != item1["id"]
    assert item2["suggested_action"] == "adjust_prompt"


def test_create_allowed_after_ignored():
    fas = _store()
    item1 = fas.create_action_item(feedback_id=7, root_cause="other")
    fas.update_action_status(item1["id"], status="ignored")
    item2 = fas.create_action_item(feedback_id=7, root_cause="retrieval_miss")
    assert item2["id"] != item1["id"]


def test_create_different_feedbacks_independent():
    """Different feedback IDs should not interfere with each other."""
    fas = _store()
    item1 = fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    item2 = fas.create_action_item(feedback_id=2, root_cause="hallucination")
    assert item1["id"] != item2["id"]


# ─── get_action_item ──────────────────────────────────────────────────────────

def test_get_action_item_not_found():
    fas = _store()
    assert fas.get_action_item(9999) is None


# ─── list_action_items ────────────────────────────────────────────────────────

def test_list_action_items_empty():
    fas = _store()
    assert fas.list_action_items() == []


def test_list_action_items_returns_all():
    fas = _store()
    fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    fas.create_action_item(feedback_id=2, root_cause="hallucination")
    items = fas.list_action_items()
    assert len(items) == 2


def test_list_action_items_pending_first():
    fas = _store()
    item1 = fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    item2 = fas.create_action_item(feedback_id=2, root_cause="hallucination")
    fas.update_action_status(item1["id"], status="done")
    items = fas.list_action_items()
    # pending item2 should come first
    assert items[0]["status"] == "pending"
    assert items[0]["id"] == item2["id"]


def test_list_action_items_filter_by_status():
    fas = _store()
    item1 = fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    fas.create_action_item(feedback_id=2, root_cause="hallucination")
    fas.update_action_status(item1["id"], status="accepted")

    accepted = fas.list_action_items(status="accepted")
    assert len(accepted) == 1
    assert accepted[0]["status"] == "accepted"

    pending = fas.list_action_items(status="pending")
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"


def test_list_action_items_filter_by_suggested_action():
    fas = _store()
    fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    fas.create_action_item(feedback_id=2, root_cause="hallucination")

    hits = fas.list_action_items(suggested_action="create_coverage_gap")
    assert len(hits) == 1
    assert hits[0]["suggested_action"] == "create_coverage_gap"


def test_list_action_items_filter_by_root_cause():
    fas = _store()
    fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    fas.create_action_item(feedback_id=2, root_cause="hallucination")

    hits = fas.list_action_items(root_cause="retrieval_miss")
    assert len(hits) == 1
    assert hits[0]["root_cause"] == "retrieval_miss"


def test_list_action_items_filter_by_topic():
    fas = _store()
    fas.create_action_item(feedback_id=1, root_cause="retrieval_miss", detected_topic="k8s")
    fas.create_action_item(feedback_id=2, root_cause="hallucination", detected_topic="docker")

    hits = fas.list_action_items(detected_topic="k8s")
    assert len(hits) == 1
    assert hits[0]["detected_topic"] == "k8s"


def test_list_action_items_pagination():
    fas = _store()
    for i in range(5):
        fas.create_action_item(feedback_id=i + 100)
    page1 = fas.list_action_items(limit=2)
    assert len(page1) == 2
    page2 = fas.list_action_items(limit=2, offset=2)
    assert len(page2) == 2
    page3 = fas.list_action_items(limit=2, offset=4)
    assert len(page3) == 1


# ─── update_action_status ─────────────────────────────────────────────────────

def test_update_action_status_basic():
    fas = _store()
    item = fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    updated = fas.update_action_status(item["id"], status="accepted")
    assert updated["status"] == "accepted"
    assert updated["updated_at"] >= item["updated_at"]


def test_update_action_status_with_owner_note():
    fas = _store()
    item = fas.create_action_item(feedback_id=1, root_cause="hallucination")
    updated = fas.update_action_status(item["id"], status="done", owner_note="Fixed in prompt v2")
    assert updated["status"] == "done"
    assert updated["owner_note"] == "Fixed in prompt v2"


def test_update_action_status_preserves_note_when_not_provided():
    fas = _store()
    item = fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    fas.update_action_status(item["id"], status="accepted", owner_note="First note")
    updated2 = fas.update_action_status(item["id"], status="done")
    assert updated2["owner_note"] == "First note"


def test_update_action_status_invalid_raises():
    fas = _store()
    item = fas.create_action_item(feedback_id=1)
    with pytest.raises(ValueError, match="status"):
        fas.update_action_status(item["id"], status="invalid_status")


def test_update_action_status_not_found_returns_none():
    fas = _store()
    result = fas.update_action_status(9999, status="done")
    assert result is None


# ─── count_summary ────────────────────────────────────────────────────────────

def test_count_summary_empty():
    fas = _store()
    s = fas.count_summary()
    assert s["total"] == 0
    assert s["total_pending"] == 0
    assert s["total_accepted"] == 0
    assert s["total_done"] == 0
    assert s["total_ignored"] == 0
    assert s["by_action"] == {}


def test_count_summary_with_data():
    fas = _store()
    item1 = fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    item2 = fas.create_action_item(feedback_id=2, root_cause="hallucination")
    fas.create_action_item(feedback_id=3, root_cause="stale_source_mix")
    fas.update_action_status(item1["id"], status="accepted")
    fas.update_action_status(item2["id"], status="done")

    s = fas.count_summary()
    assert s["total"] == 3
    assert s["total_pending"] == 1
    assert s["total_accepted"] == 1
    assert s["total_done"] == 1
    assert s["total_ignored"] == 0
    assert s["by_action"]["create_coverage_gap"] == 1
    assert s["by_action"]["adjust_prompt"] == 1
    assert s["by_action"]["recrawl_source"] == 1


# ─── Timestamps ──────────────────────────────────────────────────────────────

def test_created_at_set():
    fas = _store()
    before = time.time()
    item = fas.create_action_item(feedback_id=1)
    after = time.time()
    assert before <= item["created_at"] <= after


def test_updated_at_changes_on_status_update():
    fas = _store()
    item = fas.create_action_item(feedback_id=1)
    time.sleep(0.01)
    updated = fas.update_action_status(item["id"], status="accepted")
    assert updated["updated_at"] >= item["updated_at"]


# ─── Execution metadata: defaults ─────────────────────────────────────────────

def test_new_item_has_idle_execution_status():
    fas = _store()
    item = fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    assert item["execution_status"] == "idle"
    assert item["execution_type"] is None
    assert item["execution_payload"] == {}
    assert item["execution_result"] == {}
    assert item["executed_at"] is None


def test_execution_fields_present_on_list():
    fas = _store()
    fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    items = fas.list_action_items()
    assert len(items) == 1
    item = items[0]
    assert "execution_status" in item
    assert item["execution_status"] == "idle"


# ─── set_execution_metadata ───────────────────────────────────────────────────

def test_set_execution_metadata_executed():
    fas = _store()
    item = fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    now = time.time()
    updated = fas.set_execution_metadata(
        item["id"],
        execution_status="executed",
        execution_type="coverage_gap_review",
        execution_payload={"gap_id": 42, "question": "q"},
        execution_result={"coverage_gap_id": 42, "summary": "coverage gap #42 created"},
        executed_at=now,
    )
    assert updated is not None
    assert updated["execution_status"] == "executed"
    assert updated["execution_type"] == "coverage_gap_review"
    assert updated["execution_payload"]["gap_id"] == 42
    assert updated["execution_result"]["coverage_gap_id"] == 42
    assert updated["executed_at"] == now


def test_set_execution_metadata_blocked():
    fas = _store()
    item = fas.create_action_item(feedback_id=1, root_cause="stale_source_mix")
    updated = fas.set_execution_metadata(
        item["id"],
        execution_status="blocked",
        execution_type="recrawl",
        execution_result={"reason": "Missing detected_topic."},
    )
    assert updated is not None
    assert updated["execution_status"] == "blocked"
    assert updated["execution_type"] == "recrawl"
    assert updated["execution_result"]["reason"] == "Missing detected_topic."
    assert updated["executed_at"] is None


def test_set_execution_metadata_overwrite():
    """Second call overwrites first execution metadata."""
    fas = _store()
    item = fas.create_action_item(feedback_id=1, root_cause="retrieval_miss")
    fas.set_execution_metadata(
        item["id"],
        execution_status="blocked",
        execution_result={"reason": "first block"},
    )
    updated = fas.set_execution_metadata(
        item["id"],
        execution_status="executed",
        execution_type="coverage_gap_review",
        execution_result={"coverage_gap_id": 5, "summary": "gap #5 created"},
        executed_at=time.time(),
    )
    assert updated["execution_status"] == "executed"
    assert updated["execution_result"]["coverage_gap_id"] == 5


def test_set_execution_metadata_invalid_status():
    fas = _store()
    item = fas.create_action_item(feedback_id=1)
    with pytest.raises(ValueError, match="execution_status"):
        fas.set_execution_metadata(item["id"], execution_status="running")


def test_set_execution_metadata_not_found_returns_none():
    fas = _store()
    result = fas.set_execution_metadata(9999, execution_status="blocked")
    assert result is None


def test_set_execution_metadata_updates_updated_at():
    fas = _store()
    item = fas.create_action_item(feedback_id=1)
    time.sleep(0.01)
    updated = fas.set_execution_metadata(
        item["id"], execution_status="blocked", execution_result={"reason": "no topic"}
    )
    assert updated["updated_at"] > item["updated_at"]
