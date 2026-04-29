"""Eval Runner – deterministic pass/fail evaluation against the current pipeline.

Runs an eval case's question through the existing RAG pipeline and checks the
result against the case's expectations using simple, deterministic rules.

Scoring rules:
  - should_not_fallback:   answer must NOT look like a fallback/no-info response
  - should_have_citations: citations_count > 0
  - min_retrieval_count:   retrieval_count >= min_retrieval_count
  - expected_topic:        detected_topic matches expected_topic (case-insensitive)

None expectation values are skipped (not checked).

No LLM judge is used. All checks are text-based and deterministic.
"""
from __future__ import annotations

from typing import Any

from orchestrator import eval_case_store

# ─── Fallback detection ───────────────────────────────────────────────────────

# These substrings indicate the pipeline returned a fallback/no-info response.
# Sourced from rag.generator._no_context_message and _fallback_answer.
_FALLBACK_PHRASES = (
    "chưa tìm thấy thông tin",
    "không tìm thấy thông tin",
    "chưa có đủ thông tin",
    "không đủ thông tin",
    "hiện tại tôi chưa",
)


def _is_fallback(answer: str) -> bool:
    """Return True if the answer looks like a pipeline fallback/no-info response."""
    lower = answer.lower()
    return any(phrase in lower for phrase in _FALLBACK_PHRASES)


# ─── Check functions ──────────────────────────────────────────────────────────

def _check_not_fallback(answer: str) -> tuple[bool, str]:
    if _is_fallback(answer):
        return False, "answer is a fallback/no-info response"
    return True, "answer is not a fallback response"


def _check_has_citations(citations_count: int) -> tuple[bool, str]:
    if citations_count > 0:
        return True, f"citations_count={citations_count} > 0"
    return False, "citations_count=0, no citations present"


def _check_min_retrieval(retrieval_count: int, min_count: int) -> tuple[bool, str]:
    if retrieval_count >= min_count:
        return True, f"retrieval_count={retrieval_count} >= min={min_count}"
    return False, f"retrieval_count={retrieval_count} < min={min_count}"


def _check_topic(detected: str | None, expected: str) -> tuple[bool, str]:
    det = (detected or "").strip().lower()
    exp = expected.strip().lower()
    if det == exp:
        return True, f"detected_topic='{detected}' matches expected='{expected}'"
    return False, f"detected_topic='{detected}' != expected='{expected}'"


# ─── Score a result against expectations ─────────────────────────────────────

def score_result(
    expectations: dict,
    *,
    answer: str,
    retrieval_count: int,
    citations_count: int,
    detected_topic: str | None,
) -> tuple[bool, dict[str, dict]]:
    """Apply deterministic checks against expectations.

    Returns (overall_pass: bool, checks: dict).
    Each check entry: {"pass": bool, "reason": str, "skipped": bool}.
    """
    checks: dict[str, dict] = {}

    # should_not_fallback
    snf = expectations.get("should_not_fallback")
    if snf is None:
        checks["should_not_fallback"] = {"pass": True, "reason": "not checked", "skipped": True}
    elif snf:
        passed, reason = _check_not_fallback(answer)
        checks["should_not_fallback"] = {"pass": passed, "reason": reason, "skipped": False}
    else:
        # should_not_fallback=False means "fallback is acceptable" — always passes
        checks["should_not_fallback"] = {
            "pass": True,
            "reason": "fallback acceptable for this case",
            "skipped": False,
        }

    # should_have_citations
    shc = expectations.get("should_have_citations")
    if shc is None:
        checks["should_have_citations"] = {"pass": True, "reason": "not checked", "skipped": True}
    elif shc:
        passed, reason = _check_has_citations(citations_count)
        checks["should_have_citations"] = {"pass": passed, "reason": reason, "skipped": False}
    else:
        checks["should_have_citations"] = {
            "pass": True,
            "reason": "citations not required for this case",
            "skipped": False,
        }

    # min_retrieval_count
    mrc = expectations.get("min_retrieval_count")
    if mrc is None:
        checks["min_retrieval_count"] = {"pass": True, "reason": "not checked", "skipped": True}
    else:
        passed, reason = _check_min_retrieval(retrieval_count, int(mrc))
        checks["min_retrieval_count"] = {"pass": passed, "reason": reason, "skipped": False}

    # expected_topic
    et = expectations.get("expected_topic")
    if not et:
        checks["expected_topic"] = {"pass": True, "reason": "not checked", "skipped": True}
    else:
        passed, reason = _check_topic(detected_topic, et)
        checks["expected_topic"] = {"pass": passed, "reason": reason, "skipped": False}

    # Overall pass: all non-skipped checks must pass
    overall = all(
        c["pass"] for c in checks.values() if not c.get("skipped")
    )
    return overall, checks


# ─── Pipeline bridge ──────────────────────────────────────────────────────────

def _chat_with_trace(question: str):
    """Lazy bridge to the current RAG pipeline for easier testing/mocking."""
    from rag.pipeline import chat_with_trace
    return chat_with_trace(question)


# ─── Public runner ────────────────────────────────────────────────────────────

def run_eval_case(case: dict) -> dict[str, Any]:
    """Run an eval case through the current RAG pipeline.

    Calls rag.pipeline.chat_with_trace with the case question, scores result
    against case expectations, persists the run via eval_case_store, and
    returns the run record.

    Raises RuntimeError if the pipeline call fails.
    Does NOT catch LLM/retrieval errors — callers (API layer) should handle.
    """
    question = case["question"]
    expectations = case.get("eval_expectations") or {}

    # Run through the current pipeline
    rag_result = _chat_with_trace(question)

    answer = rag_result.answer
    retrieval_count = rag_result.retrieval_count
    detected_topic = rag_result.detected_topic
    citations = [c.model_dump() for c in rag_result.citations]

    # Score
    overall_pass, checks = score_result(
        expectations,
        answer=answer,
        retrieval_count=retrieval_count,
        citations_count=len(citations),
        detected_topic=detected_topic,
    )

    # Compact result snapshot
    result_snapshot = {
        "answer_preview": answer[:300] if answer else "",
        "detected_topic": detected_topic,
        "retrieval_count": retrieval_count,
        "citations_count": len(citations),
        "citations_summary": [
            {"title": c.get("title", ""), "url": c.get("url", "")}
            for c in citations[:3]
        ],
        "is_fallback": _is_fallback(answer),
    }

    # Persist run
    run = eval_case_store.create_eval_run(
        eval_case_id=case["id"],
        passed=overall_pass,
        checks=checks,
        result_snapshot=result_snapshot,
    )
    return run
