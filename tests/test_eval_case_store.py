"""Unit tests for orchestrator.eval_case_store."""
from __future__ import annotations

import importlib
import time

import pytest


@pytest.fixture(autouse=True)
def _fresh_store(tmp_path, monkeypatch):
    """Each test uses an isolated DB in tmp_path."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))

    import config.settings as settings_mod
    importlib.reload(settings_mod)

    import orchestrator.eval_case_store as ecs
    ecs._initialised_paths.clear()
    importlib.reload(ecs)


def _store():
    import orchestrator.eval_case_store as ecs
    return ecs


# ─── derive_expectations ──────────────────────────────────────────────────────

def test_derive_expectations_retrieval_miss():
    ecs = _store()
    exp = ecs.derive_expectations("retrieval_miss")
    assert exp["should_not_fallback"] is True
    assert exp["should_have_citations"] is True
    assert exp["min_retrieval_count"] == 1
    assert exp["expected_topic"] is None


def test_derive_expectations_true_coverage_gap():
    ecs = _store()
    exp = ecs.derive_expectations("true_coverage_gap")
    assert exp["should_not_fallback"] is False
    assert exp["should_have_citations"] is False
    assert exp["min_retrieval_count"] is None


def test_derive_expectations_bad_citation_fit():
    ecs = _store()
    exp = ecs.derive_expectations("bad_citation_fit")
    assert exp["should_have_citations"] is True
    assert exp["should_not_fallback"] is None
    assert exp["min_retrieval_count"] is None


def test_derive_expectations_insufficient_context():
    ecs = _store()
    exp = ecs.derive_expectations("insufficient_context")
    assert exp["should_not_fallback"] is True
    assert exp["min_retrieval_count"] == 1


def test_derive_expectations_hallucination():
    ecs = _store()
    exp = ecs.derive_expectations("hallucination")
    assert exp["should_have_citations"] is True
    assert exp["should_not_fallback"] is None


def test_derive_expectations_with_expected_topic():
    ecs = _store()
    exp = ecs.derive_expectations("retrieval_miss", expected_topic="kubernetes")
    assert exp["expected_topic"] == "kubernetes"


def test_derive_expectations_unknown_root_cause():
    ecs = _store()
    exp = ecs.derive_expectations("unknown_cause")
    # Falls through to default (all None)
    assert exp["should_not_fallback"] is None
    assert exp["should_have_citations"] is None
    assert exp["min_retrieval_count"] is None


def test_derive_expectations_none_root_cause():
    ecs = _store()
    exp = ecs.derive_expectations(None)
    assert exp["should_not_fallback"] is None
    assert exp["should_have_citations"] is None
    assert exp["min_retrieval_count"] is None
    assert exp["expected_topic"] is None


# ─── create_eval_case ─────────────────────────────────────────────────────────

def test_create_eval_case_basic():
    ecs = _store()
    case = ecs.create_eval_case(
        feedback_id=1,
        question="How to deploy pods?",
        root_cause="retrieval_miss",
        expected_topic="kubernetes",
    )
    assert case["id"] > 0
    assert case["feedback_id"] == 1
    assert case["question"] == "How to deploy pods?"
    assert case["root_cause"] == "retrieval_miss"
    assert case["expected_topic"] == "kubernetes"
    assert case["status"] == "active"
    assert case["eval_expectations"]["should_not_fallback"] is True
    assert case["eval_expectations"]["expected_topic"] == "kubernetes"


def test_create_eval_case_with_snapshots():
    ecs = _store()
    citations = [{"title": "K8s docs", "url": "https://k8s.io"}]
    trace = {"request_id": "r1", "cache_hit": False}
    case = ecs.create_eval_case(
        feedback_id=2,
        question="How to scale?",
        root_cause="insufficient_context",
        citations_snapshot=citations,
        trace_snapshot=trace,
    )
    assert case["citations_snapshot"] == citations
    assert case["trace_snapshot"] == trace


def test_create_eval_case_sets_timestamps():
    ecs = _store()
    before = time.time()
    case = ecs.create_eval_case(feedback_id=3, question="Q")
    after = time.time()
    assert before <= case["created_at"] <= after
    assert before <= case["updated_at"] <= after


def test_create_eval_case_empty_question_raises():
    ecs = _store()
    with pytest.raises(ValueError, match="empty"):
        ecs.create_eval_case(feedback_id=1, question="  ")


def test_create_eval_case_duplicate_active_raises():
    """One active eval case per feedback_id — second create must raise."""
    ecs = _store()
    ecs.create_eval_case(feedback_id=5, question="Q1")
    with pytest.raises(ValueError, match="already has an active eval case"):
        ecs.create_eval_case(feedback_id=5, question="Q2")


def test_create_eval_case_after_archive_allowed():
    """After archiving the first case, a new one can be created."""
    ecs = _store()
    first = ecs.create_eval_case(feedback_id=6, question="Q1")
    ecs.update_eval_case_status(first["id"], status="archived")
    second = ecs.create_eval_case(feedback_id=6, question="Q2")
    assert second["id"] != first["id"]
    assert second["status"] == "active"


def test_create_eval_case_custom_expectations():
    ecs = _store()
    custom = {"should_not_fallback": True, "should_have_citations": False,
              "min_retrieval_count": 2, "expected_topic": "docker"}
    case = ecs.create_eval_case(
        feedback_id=7,
        question="Q",
        eval_expectations=custom,
    )
    assert case["eval_expectations"] == custom


# ─── get_eval_case ────────────────────────────────────────────────────────────

def test_get_eval_case_not_found():
    ecs = _store()
    assert ecs.get_eval_case(999) is None


def test_get_eval_case_includes_latest_run_none_when_no_runs():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    fetched = ecs.get_eval_case(case["id"])
    assert fetched is not None
    assert fetched["latest_run"] is None


# ─── list_eval_cases ──────────────────────────────────────────────────────────

def test_list_eval_cases_empty():
    ecs = _store()
    assert ecs.list_eval_cases() == []


def test_list_eval_cases_returns_all():
    ecs = _store()
    ecs.create_eval_case(feedback_id=1, question="Q1")
    ecs.create_eval_case(feedback_id=2, question="Q2")
    items = ecs.list_eval_cases()
    assert len(items) == 2


def test_list_eval_cases_filter_by_status():
    ecs = _store()
    c1 = ecs.create_eval_case(feedback_id=1, question="Q1")
    ecs.create_eval_case(feedback_id=2, question="Q2")
    ecs.update_eval_case_status(c1["id"], status="archived")

    active = ecs.list_eval_cases(status="active")
    assert len(active) == 1
    assert active[0]["question"] == "Q2"

    archived = ecs.list_eval_cases(status="archived")
    assert len(archived) == 1
    assert archived[0]["question"] == "Q1"


def test_list_eval_cases_filter_by_root_cause():
    ecs = _store()
    ecs.create_eval_case(feedback_id=1, question="Q1", root_cause="retrieval_miss")
    ecs.create_eval_case(feedback_id=2, question="Q2", root_cause="hallucination")

    hits = ecs.list_eval_cases(root_cause="retrieval_miss")
    assert len(hits) == 1
    assert hits[0]["root_cause"] == "retrieval_miss"


def test_list_eval_cases_includes_latest_run():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    # No run yet
    items = ecs.list_eval_cases()
    assert items[0]["latest_run"] is None

    # Add a run
    ecs.create_eval_run(
        eval_case_id=case["id"],
        passed=True,
        checks={"c": {"pass": True, "reason": "ok", "skipped": False}},
        result_snapshot={"retrieval_count": 3},
    )
    items2 = ecs.list_eval_cases()
    assert items2[0]["latest_run"] is not None
    assert items2[0]["latest_run"]["pass"] is True


# ─── update_eval_case_status ─────────────────────────────────────────────────

def test_update_eval_case_status_archive():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    updated = ecs.update_eval_case_status(case["id"], status="archived")
    assert updated["status"] == "archived"


def test_update_eval_case_status_invalid_raises():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    with pytest.raises(ValueError, match="status"):
        ecs.update_eval_case_status(case["id"], status="deleted")


# ─── count_summary ────────────────────────────────────────────────────────────

def test_count_summary_empty():
    ecs = _store()
    s = ecs.count_summary()
    assert s["total"] == 0
    assert s["total_active"] == 0
    assert s["total_archived"] == 0
    assert s["by_root_cause"] == {}
    assert s["latest_runs"]["total"] == 0


def test_count_summary_with_cases():
    ecs = _store()
    ecs.create_eval_case(feedback_id=1, question="Q1", root_cause="retrieval_miss")
    ecs.create_eval_case(feedback_id=2, question="Q2", root_cause="retrieval_miss")
    c3 = ecs.create_eval_case(feedback_id=3, question="Q3", root_cause="hallucination")
    ecs.update_eval_case_status(c3["id"], status="archived")

    s = ecs.count_summary()
    assert s["total"] == 3
    assert s["total_active"] == 2
    assert s["total_archived"] == 1
    assert s["by_root_cause"]["retrieval_miss"] == 2
    assert s["by_root_cause"]["hallucination"] == 1


def test_count_summary_latest_runs():
    ecs = _store()
    c1 = ecs.create_eval_case(feedback_id=1, question="Q1")
    c2 = ecs.create_eval_case(feedback_id=2, question="Q2")
    ecs.create_eval_run(eval_case_id=c1["id"], passed=True,
                        checks={}, result_snapshot={})
    ecs.create_eval_run(eval_case_id=c2["id"], passed=False,
                        checks={}, result_snapshot={})

    s = ecs.count_summary()
    assert s["latest_runs"]["total"] == 2
    assert s["latest_runs"]["pass"] == 1
    assert s["latest_runs"]["fail"] == 1


# ─── eval runs ────────────────────────────────────────────────────────────────

def test_create_eval_run_basic():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    run = ecs.create_eval_run(
        eval_case_id=case["id"],
        passed=True,
        checks={"should_not_fallback": {"pass": True, "reason": "ok", "skipped": False}},
        result_snapshot={"retrieval_count": 2, "detected_topic": "k8s"},
    )
    assert run["id"] > 0
    assert run["eval_case_id"] == case["id"]
    assert run["pass"] is True
    assert run["checks"]["should_not_fallback"]["pass"] is True
    assert run["result_snapshot"]["retrieval_count"] == 2


def test_create_eval_run_fail():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    run = ecs.create_eval_run(
        eval_case_id=case["id"],
        passed=False,
        checks={"should_not_fallback": {"pass": False, "reason": "fallback", "skipped": False}},
        result_snapshot={},
    )
    assert run["pass"] is False


def test_get_latest_run_none_when_no_runs():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    assert ecs.get_latest_run(case["id"]) is None


def test_get_latest_run_returns_most_recent():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    ecs.create_eval_run(eval_case_id=case["id"], passed=False,
                        checks={}, result_snapshot={"v": 1})
    time.sleep(0.01)
    r2 = ecs.create_eval_run(eval_case_id=case["id"], passed=True,
                              checks={}, result_snapshot={"v": 2})
    latest = ecs.get_latest_run(case["id"])
    assert latest["id"] == r2["id"]
    assert latest["pass"] is True


def test_list_eval_runs_empty():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    assert ecs.list_eval_runs(case["id"]) == []


def test_list_eval_runs_newest_first():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    ecs.create_eval_run(eval_case_id=case["id"], passed=False,
                        checks={}, result_snapshot={"v": 1})
    time.sleep(0.01)
    ecs.create_eval_run(eval_case_id=case["id"], passed=True,
                        checks={}, result_snapshot={"v": 2})
    runs = ecs.list_eval_runs(case["id"])
    assert len(runs) == 2
    assert runs[0]["result_snapshot"]["v"] == 2  # newest first
    assert runs[1]["result_snapshot"]["v"] == 1


def test_list_eval_runs_pagination():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    for _ in range(5):
        ecs.create_eval_run(eval_case_id=case["id"], passed=True,
                            checks={}, result_snapshot={})
    page1 = ecs.list_eval_runs(case["id"], limit=2)
    assert len(page1) == 2
    page2 = ecs.list_eval_runs(case["id"], limit=2, offset=2)
    assert len(page2) == 2


# ─── eval batch CRUD ─────────────────────────────────────────────────────────

def test_create_eval_batch_basic():
    ecs = _store()
    batch = ecs.create_eval_batch(
        label="Post-tuning check",
        filters={"status": "active"},
        total_cases=5,
        pass_count=3,
        fail_count=2,
    )
    assert batch["id"] > 0
    assert batch["label"] == "Post-tuning check"
    assert batch["filters"] == {"status": "active"}
    assert batch["status"] == "completed"
    assert batch["total_cases"] == 5
    assert batch["pass_count"] == 3
    assert batch["fail_count"] == 2
    assert "created_at" in batch
    # summary is attached
    assert "summary" in batch


def test_create_eval_batch_no_label():
    ecs = _store()
    batch = ecs.create_eval_batch(
        label=None,
        filters={},
        total_cases=2,
        pass_count=2,
        fail_count=0,
    )
    assert batch["label"] is None
    assert batch["id"] > 0


def test_get_eval_batch_not_found():
    ecs = _store()
    assert ecs.get_eval_batch(999) is None


def test_get_eval_batch_includes_summary():
    ecs = _store()
    batch = ecs.create_eval_batch(
        label=None,
        filters={},
        total_cases=0,
        pass_count=0,
        fail_count=0,
    )
    fetched = ecs.get_eval_batch(batch["id"])
    assert fetched is not None
    s = fetched["summary"]
    assert s["total_cases"] == 0
    assert s["pass_count"] == 0
    assert s["fail_count"] == 0
    assert s["pass_rate"] == 0.0
    assert s["by_root_cause"] == {}
    assert s["by_expected_topic"] == {}


def test_list_eval_batches_empty():
    ecs = _store()
    assert ecs.list_eval_batches() == []


def test_list_eval_batches_newest_first():
    ecs = _store()
    b1 = ecs.create_eval_batch(label="first", filters={}, total_cases=1, pass_count=1, fail_count=0)
    time.sleep(0.01)
    b2 = ecs.create_eval_batch(label="second", filters={}, total_cases=2, pass_count=1, fail_count=1)
    batches = ecs.list_eval_batches()
    assert len(batches) == 2
    assert batches[0]["id"] == b2["id"]
    assert batches[1]["id"] == b1["id"]


def test_create_eval_batch_item_pass():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q", root_cause="retrieval_miss",
                                 expected_topic="kubernetes")
    run = ecs.create_eval_run(eval_case_id=case["id"], passed=True, checks={}, result_snapshot={})
    batch = ecs.create_eval_batch(label=None, filters={}, total_cases=1, pass_count=1, fail_count=0)

    item = ecs.create_eval_batch_item(
        batch_id=batch["id"],
        eval_case_id=case["id"],
        eval_run_id=run["id"],
        passed=True,
        root_cause="retrieval_miss",
        expected_topic="kubernetes",
    )
    assert item["id"] > 0
    assert item["batch_id"] == batch["id"]
    assert item["eval_case_id"] == case["id"]
    assert item["eval_run_id"] == run["id"]
    assert item["pass"] is True
    assert item["root_cause"] == "retrieval_miss"
    assert item["expected_topic"] == "kubernetes"
    assert item["error"] is None


def test_create_eval_batch_item_fail():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    run = ecs.create_eval_run(eval_case_id=case["id"], passed=False, checks={}, result_snapshot={})
    batch = ecs.create_eval_batch(label=None, filters={}, total_cases=1, pass_count=0, fail_count=1)

    item = ecs.create_eval_batch_item(
        batch_id=batch["id"],
        eval_case_id=case["id"],
        eval_run_id=run["id"],
        passed=False,
        root_cause=None,
        expected_topic=None,
    )
    assert item["pass"] is False
    assert item["error"] is None


def test_create_eval_batch_item_execution_error():
    ecs = _store()
    case = ecs.create_eval_case(feedback_id=1, question="Q")
    batch = ecs.create_eval_batch(label=None, filters={}, total_cases=1, pass_count=0, fail_count=0)

    item = ecs.create_eval_batch_item(
        batch_id=batch["id"],
        eval_case_id=case["id"],
        eval_run_id=None,
        passed=None,
        root_cause=None,
        expected_topic=None,
        error="Pipeline unavailable",
    )
    assert item["pass"] is None
    assert item["eval_run_id"] is None
    assert item["error"] == "Pipeline unavailable"


def test_list_eval_batch_items_empty():
    ecs = _store()
    batch = ecs.create_eval_batch(label=None, filters={}, total_cases=0, pass_count=0, fail_count=0)
    assert ecs.list_eval_batch_items(batch["id"]) == []


def test_list_eval_batch_items_ordered():
    ecs = _store()
    c1 = ecs.create_eval_case(feedback_id=1, question="Q1")
    c2 = ecs.create_eval_case(feedback_id=2, question="Q2")
    batch = ecs.create_eval_batch(label=None, filters={}, total_cases=2, pass_count=1, fail_count=1)

    it1 = ecs.create_eval_batch_item(
        batch_id=batch["id"], eval_case_id=c1["id"], eval_run_id=None,
        passed=True, root_cause=None, expected_topic=None,
    )
    it2 = ecs.create_eval_batch_item(
        batch_id=batch["id"], eval_case_id=c2["id"], eval_run_id=None,
        passed=False, root_cause=None, expected_topic=None,
    )
    items = ecs.list_eval_batch_items(batch["id"])
    assert len(items) == 2
    assert items[0]["id"] == it1["id"]
    assert items[1]["id"] == it2["id"]


def test_build_batch_summary_counts():
    ecs = _store()
    c1 = ecs.create_eval_case(feedback_id=1, question="Q1", root_cause="retrieval_miss",
                               expected_topic="kubernetes")
    c2 = ecs.create_eval_case(feedback_id=2, question="Q2", root_cause="retrieval_miss",
                               expected_topic="kubernetes")
    c3 = ecs.create_eval_case(feedback_id=3, question="Q3", root_cause="hallucination",
                               expected_topic="docker")
    batch = ecs.create_eval_batch(label=None, filters={}, total_cases=3, pass_count=1, fail_count=2)

    ecs.create_eval_batch_item(
        batch_id=batch["id"], eval_case_id=c1["id"], eval_run_id=None,
        passed=True, root_cause="retrieval_miss", expected_topic="kubernetes",
    )
    ecs.create_eval_batch_item(
        batch_id=batch["id"], eval_case_id=c2["id"], eval_run_id=None,
        passed=False, root_cause="retrieval_miss", expected_topic="kubernetes",
    )
    ecs.create_eval_batch_item(
        batch_id=batch["id"], eval_case_id=c3["id"], eval_run_id=None,
        passed=False, root_cause="hallucination", expected_topic="docker",
    )

    fetched = ecs.get_eval_batch(batch["id"])
    s = fetched["summary"]
    assert s["total_cases"] == 3
    assert s["pass_count"] == 1
    assert s["fail_count"] == 2
    assert s["error_count"] == 0
    assert s["pass_rate"] == round(1 / 3, 4)

    by_rc = s["by_root_cause"]
    assert by_rc["retrieval_miss"]["pass"] == 1
    assert by_rc["retrieval_miss"]["fail"] == 1
    assert by_rc["hallucination"]["fail"] == 1

    by_et = s["by_expected_topic"]
    assert by_et["kubernetes"]["pass"] == 1
    assert by_et["kubernetes"]["fail"] == 1
    assert by_et["docker"]["fail"] == 1


def test_build_batch_summary_excludes_errors_from_breakdown():
    ecs = _store()
    c1 = ecs.create_eval_case(feedback_id=1, question="Q1", root_cause="retrieval_miss",
                               expected_topic="kubernetes")
    c2 = ecs.create_eval_case(feedback_id=2, question="Q2", root_cause="retrieval_miss",
                               expected_topic="kubernetes")
    batch = ecs.create_eval_batch(label=None, filters={}, total_cases=2, pass_count=1, fail_count=0)

    ecs.create_eval_batch_item(
        batch_id=batch["id"], eval_case_id=c1["id"], eval_run_id=None,
        passed=True, root_cause="retrieval_miss", expected_topic="kubernetes",
    )
    ecs.create_eval_batch_item(
        batch_id=batch["id"], eval_case_id=c2["id"], eval_run_id=None,
        passed=None, root_cause="retrieval_miss", expected_topic="kubernetes",
        error="Pipeline error",
    )

    fetched = ecs.get_eval_batch(batch["id"])
    s = fetched["summary"]
    assert s["total_cases"] == 2
    assert s["pass_count"] == 1
    assert s["error_count"] == 1
    # Error item should not appear in by_root_cause breakdown
    by_rc = s["by_root_cause"]
    assert by_rc["retrieval_miss"]["pass"] == 1
    assert by_rc["retrieval_miss"].get("fail", 0) == 0
