"""Eval Gate Triage – derive failure triage items for a gate run.

For a given gate run, this module joins:
  - the gate run record
  - the gate config
  - candidate batch items
  - (when present) baseline batch items
  - eval case details
  - eval run details (failure reason, answer excerpt, snapshot)

to produce a compact triage view useful for investigating gate failures
without adding a new persistence layer.

Regression classification:
  new_fail     – candidate fail/error, baseline pass
  still_fail   – candidate fail, baseline fail or error
  new_error    – candidate error, baseline pass or fail (or no baseline)
  still_error  – candidate error, baseline was also error
  improved     – candidate pass, baseline fail or error
  still_pass   – candidate pass, baseline pass (or no baseline available)

This module is read-only; it never writes records.
"""
from __future__ import annotations

_OUTCOME_FAIL = "fail"
_OUTCOME_PASS = "pass"
_OUTCOME_ERROR = "error"
_OUTCOME_NONE = "none"
_MAX_TRIAGE_ITEMS = 500


# ─── Outcome helpers ──────────────────────────────────────────────────────────

def _item_outcome(item: dict) -> str:
    """Derive outcome string from a batch item dict."""
    if item.get("error") or item.get("pass") is None:
        return _OUTCOME_ERROR
    return _OUTCOME_PASS if item["pass"] else _OUTCOME_FAIL


# ─── Regression classification ────────────────────────────────────────────────

def classify_regression(baseline_outcome: str, candidate_outcome: str) -> str:
    """Classify the regression type for a single case.

    Args:
        baseline_outcome: ``pass`` | ``fail`` | ``error`` | ``none``
            (``none`` means no baseline batch was available for this case)
        candidate_outcome: ``pass`` | ``fail`` | ``error``

    Returns one of: ``new_fail``, ``still_fail``, ``improved``,
        ``new_error``, ``still_error``, ``still_pass``.
    """
    if baseline_outcome == _OUTCOME_NONE:
        if candidate_outcome == _OUTCOME_ERROR:
            return "new_error"
        if candidate_outcome == _OUTCOME_FAIL:
            return "new_fail"
        return "still_pass"

    if candidate_outcome == _OUTCOME_PASS:
        if baseline_outcome in (_OUTCOME_FAIL, _OUTCOME_ERROR):
            return "improved"
        return "still_pass"

    if candidate_outcome == _OUTCOME_ERROR:
        if baseline_outcome == _OUTCOME_ERROR:
            return "still_error"
        return "new_error"

    # candidate_outcome == fail
    if baseline_outcome == _OUTCOME_PASS:
        return "new_fail"
    return "still_fail"


# ─── Detail extraction ────────────────────────────────────────────────────────

def _extract_candidate_detail(eval_run: dict | None) -> dict:
    """Extract compact candidate detail from an eval run record.

    Returns a dict with:
        failure_reason   – human-readable string of failed checks, or None
        answer_excerpt   – first 300 chars of the answer_preview, or None
        citations_count  – int or None
        retrieval_count  – int or None
        is_fallback      – bool or None
        citations_summary – list[{title, url}] for up to 3 citations, or []
    """
    if not eval_run:
        return {
            "failure_reason": None,
            "answer_excerpt": None,
            "citations_count": None,
            "retrieval_count": None,
            "is_fallback": None,
            "citations_summary": [],
        }

    checks = eval_run.get("checks") or {}
    snapshot = eval_run.get("result_snapshot") or {}

    # Build failure reason from failed, non-skipped checks
    failure_parts: list[str] = []
    for check_name, result in checks.items():
        if isinstance(result, dict) and not result.get("skipped") and not result.get("pass", True):
            reason = result.get("reason") or check_name
            failure_parts.append(f"{check_name}: {reason}")

    failure_reason = "; ".join(failure_parts) if failure_parts else None
    answer_excerpt = (snapshot.get("answer_preview") or "")[:300].strip() or None

    return {
        "failure_reason": failure_reason,
        "answer_excerpt": answer_excerpt,
        "citations_count": snapshot.get("citations_count"),
        "retrieval_count": snapshot.get("retrieval_count"),
        "is_fallback": snapshot.get("is_fallback"),
        "citations_summary": snapshot.get("citations_summary") or [],
    }


# ─── Triage item builder ──────────────────────────────────────────────────────

def _build_triage_items(
    candidate_batch_id: int,
    baseline_batch_id: int | None,
) -> list[dict]:
    """Build triage items by joining batch items, cases, and runs.

    MVP note:
    - Triages at most `_MAX_TRIAGE_ITEMS` candidate items and the matching baseline slice.
    - This keeps the admin triage view bounded and predictable for now.
    - If batches routinely exceed this cap later, add pagination/streaming rather than
      letting one gate run render an unbounded diagnostic payload.
    """
    from orchestrator import eval_case_store

    candidate_items = eval_case_store.list_eval_batch_items(candidate_batch_id, limit=_MAX_TRIAGE_ITEMS)
    baseline_items: list[dict] = (
        eval_case_store.list_eval_batch_items(baseline_batch_id, limit=_MAX_TRIAGE_ITEMS)
        if baseline_batch_id else []
    )

    # Index baseline items by eval_case_id for O(1) lookup
    baseline_by_case: dict[int, dict] = {
        it["eval_case_id"]: it for it in baseline_items
    }

    items: list[dict] = []
    for c_item in candidate_items:
        case_id = c_item["eval_case_id"]
        candidate_outcome = _item_outcome(c_item)

        b_item = baseline_by_case.get(case_id)
        baseline_outcome = _item_outcome(b_item) if b_item else _OUTCOME_NONE

        regression_class = classify_regression(baseline_outcome, candidate_outcome)

        # Load eval case for question / topic / root_cause
        case = eval_case_store.get_eval_case(case_id)
        case_dict = case or {}
        question = case_dict.get("question") or ""
        expected_topic = c_item.get("expected_topic") or case_dict.get("expected_topic")
        root_cause = c_item.get("root_cause") or case_dict.get("root_cause")
        eval_expectations = case_dict.get("eval_expectations") or {}
        feedback_id = case_dict.get("feedback_id")

        # Load candidate eval run for detail
        c_run_id = c_item.get("eval_run_id")
        c_eval_run = eval_case_store.get_eval_run(c_run_id) if c_run_id else None
        candidate_detail = _extract_candidate_detail(c_eval_run)

        item: dict = {
            "eval_case_id": case_id,
            "feedback_id": feedback_id,
            "question": question,
            "expected_topic": expected_topic,
            "root_cause": root_cause,
            "eval_expectations": eval_expectations,
            "candidate_outcome": candidate_outcome,
            "candidate_error": c_item.get("error"),
            "baseline_outcome": baseline_outcome,
            "regression_class": regression_class,
        }
        item.update(candidate_detail)
        items.append(item)

    return items


# ─── Public API ───────────────────────────────────────────────────────────────

def get_gate_run_triage(run_id: int) -> dict | None:
    """Return full triage data for a gate run.

    Returns ``None`` if the gate run does not exist.

    Response shape::

        {
            "gate_run":       <gate run record>,
            "config":         <gate config record>,
            "candidate_batch": <batch with summary, or None>,
            "baseline_batch":  <batch with summary, or None>,
            "decision_summary": {
                "decision", "decision_reason",
                "pass_rate_drop", "fail_count_delta", "error_count_delta",
                "trigger_source", "has_baseline"
            },
            "items": [<triage item>, ...]
        }
    """
    from orchestrator import eval_case_store, eval_gate_store

    gate_run = eval_gate_store.get_gate_run(run_id)
    if gate_run is None:
        return None

    config = eval_gate_store.get_gate_config(gate_run["config_id"])
    candidate_batch_id: int | None = gate_run.get("candidate_batch_id")
    baseline_batch_id: int | None = gate_run.get("baseline_batch_id")

    candidate_batch = (
        eval_case_store.get_eval_batch(candidate_batch_id) if candidate_batch_id else None
    )
    baseline_batch = (
        eval_case_store.get_eval_batch(baseline_batch_id) if baseline_batch_id else None
    )

    items = (
        _build_triage_items(candidate_batch_id, baseline_batch_id)
        if candidate_batch_id else []
    )

    decision_summary = {
        "decision": gate_run.get("decision"),
        "decision_reason": gate_run.get("decision_reason"),
        "pass_rate_drop": gate_run.get("pass_rate_drop"),
        "fail_count_delta": gate_run.get("fail_count_delta"),
        "error_count_delta": gate_run.get("error_count_delta"),
        "trigger_source": gate_run.get("trigger_source"),
        "has_baseline": baseline_batch_id is not None,
    }

    return {
        "gate_run": gate_run,
        "config": config,
        "candidate_batch": candidate_batch,
        "baseline_batch": baseline_batch,
        "decision_summary": decision_summary,
        "triage_meta": {
            "max_items": _MAX_TRIAGE_ITEMS,
            "returned_items": len(items),
            "truncated": bool(candidate_batch and candidate_batch.get("summary", {}).get("total_cases", 0) > len(items)),
        },
        "items": items,
    }


def filter_triage_items(
    items: list[dict],
    *,
    regression_class: str | None = None,
    root_cause: str | None = None,
    expected_topic: str | None = None,
    outcome: str | None = None,
) -> list[dict]:
    """Filter triage items by one or more optional criteria.

    All supplied filters are ANDed together.
    """
    result = items
    if regression_class:
        result = [it for it in result if it.get("regression_class") == regression_class]
    if root_cause:
        result = [it for it in result if it.get("root_cause") == root_cause]
    if expected_topic:
        result = [it for it in result if it.get("expected_topic") == expected_topic]
    if outcome:
        result = [it for it in result if it.get("candidate_outcome") == outcome]
    return result


# ─── Suggested next actions ───────────────────────────────────────────────────

_NEXT_ACTION_BY_ROOT_CAUSE: dict[str, str] = {
    "retrieval_miss": (
        "Retrieval miss – recrawl the topic or verify KB coverage for the missing content."
    ),
    "true_coverage_gap": (
        "True coverage gap – add a new source document that covers this topic."
    ),
    "bad_citation_fit": (
        "Bad citation fit – review citation ranking or chunking quality for this topic."
    ),
    "insufficient_context": (
        "Insufficient context – recrawl topic to add richer context documents."
    ),
    "hallucination": (
        "Hallucination – audit answer generation; check that retrieved context is relevant."
    ),
    "wrong_answer_from_context": (
        "Wrong answer from context – review answer generation; source may be misinterpreted."
    ),
    "stale_source_mix": (
        "Stale source mix – recrawl or refresh sources for this topic."
    ),
    "other": "Manual review required – no automated action mapped for this root cause.",
}


def suggest_next_action(root_cause: str | None) -> str:
    """Return a short suggested next-action string based on root_cause."""
    return _NEXT_ACTION_BY_ROOT_CAUSE.get(
        root_cause or "",
        "Review the eval case and pipeline logs for this failure.",
    )
