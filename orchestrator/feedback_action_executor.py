"""Feedback Action Execution Bridge.

Lightweight bridge that maps feedback action items into existing operational
workflows. Reuses coverage_gap_store and the crawl/chunk/embed pipeline.

MVP supports only two execution paths:
  - create_coverage_gap: create a coverage gap record from feedback context
  - recrawl_source: topic-based recrawl when detected_topic is available

All other action types are blocked with a clear reason.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_EXECUTABLE_ACTIONS = frozenset({"create_coverage_gap", "recrawl_source"})


def execute_action_item(
    action_id: int,
    *,
    sources_dir: Path | None = None,
) -> dict:
    """Execute a feedback action item via the appropriate bridge.

    Inspects the item's suggested_action and delegates to the matching bridge.
    Returns the updated action item dict with execution metadata set.
    Raises ValueError if the action item is not found.
    """
    from orchestrator import feedback_action_store

    item = feedback_action_store.get_action_item(action_id)
    if not item:
        raise ValueError(f"Action item #{action_id} not found.")

    suggested_action = item.get("suggested_action", "")

    if suggested_action == "create_coverage_gap":
        return _bridge_create_coverage_gap(item, feedback_action_store)
    elif suggested_action == "recrawl_source":
        return _bridge_recrawl_source(
            item, sources_dir or Path("sources"), feedback_action_store
        )
    else:
        # Unsupported action type — fail clearly and safely
        return feedback_action_store.set_execution_metadata(
            action_id,
            execution_status="blocked",
            execution_result={
                "reason": (
                    f"Action type '{suggested_action}' is not executable via bridge. "
                    "MVP supports: create_coverage_gap, recrawl_source."
                )
            },
        )


# ─── Bridge: create_coverage_gap ─────────────────────────────────────────────

def _bridge_create_coverage_gap(item: dict, store: Any) -> dict:
    """Create a coverage gap record from feedback action context.

    Uses query_hint as the representative question, falls back to topic-based
    or feedback-based description. Maps root_cause to gap signals.
    """
    from orchestrator import coverage_gap_store

    action_id = item["id"]
    query_hint = (item.get("query_hint") or "").strip()
    detected_topic = (item.get("detected_topic") or "").strip() or None

    # Build representative question from available context
    if query_hint:
        question = query_hint
    elif detected_topic:
        question = f"Coverage gap for topic: {detected_topic}"
    else:
        question = f"Coverage gap from feedback #{item['feedback_id']}"

    # Map root_cause to gap signals
    root_cause = (item.get("root_cause") or "").strip()
    gap_signals: list[str] = []
    if root_cause in ("retrieval_miss", "true_coverage_gap"):
        gap_signals.append(root_cause)
    gap_signals.append("feedback_action_queue")

    gap_id = coverage_gap_store.add_gap(
        question=question,
        rewritten_query=query_hint or None,
        detected_topic=detected_topic,
        answer_excerpt="",
        retrieval_count=0,
        gap_signals=gap_signals,
        feedback_type="down",
    )

    payload = {
        "gap_id": gap_id,
        "question": question,
        "detected_topic": detected_topic,
        "root_cause": root_cause or None,
    }
    result = {
        "coverage_gap_id": gap_id,
        "summary": f"coverage gap #{gap_id} created",
    }

    return store.set_execution_metadata(
        action_id,
        execution_status="executed",
        execution_type="coverage_gap_review",
        execution_payload=payload,
        execution_result=result,
        executed_at=time.time(),
    )


# ─── Bridge: recrawl_source ───────────────────────────────────────────────────

def _bridge_recrawl_source(item: dict, sources_dir: Path, store: Any) -> dict:
    """Trigger a topic-based recrawl from feedback action context.

    Requires detected_topic and a matching sources/<topic>.json file.
    Blocks with a clear reason if context is insufficient.
    """
    action_id = item["id"]
    topic = (item.get("detected_topic") or "").strip()

    if not topic:
        return store.set_execution_metadata(
            action_id,
            execution_status="blocked",
            execution_type="recrawl",
            execution_result={
                "reason": "Missing detected_topic — cannot resolve sources to recrawl."
            },
        )

    topic_path = sources_dir / f"{topic}.json"
    if not topic_path.exists():
        return store.set_execution_metadata(
            action_id,
            execution_status="blocked",
            execution_type="recrawl",
            execution_result={"reason": f"No sources file found for topic '{topic}'."},
        )

    try:
        sources = json.loads(topic_path.read_text(encoding="utf-8")) or []
    except Exception as exc:
        return store.set_execution_metadata(
            action_id,
            execution_status="blocked",
            execution_type="recrawl",
            execution_result={
                "reason": f"Failed to load sources for topic '{topic}': {exc}"
            },
        )

    if not sources:
        return store.set_execution_metadata(
            action_id,
            execution_status="blocked",
            execution_type="recrawl",
            execution_result={"reason": f"No sources configured for topic '{topic}'."},
        )

    recrawl_result = _do_recrawl(sources)
    docs_count = recrawl_result.get("documents_crawled", 0)

    return store.set_execution_metadata(
        action_id,
        execution_status="executed",
        execution_type="recrawl",
        execution_payload={"topic": topic, "sources_count": len(sources)},
        execution_result={
            **recrawl_result,
            "summary": f"recrawled {docs_count} docs",
        },
        executed_at=time.time(),
    )


def _do_recrawl(sources: list[dict]) -> dict:
    """Run the crawl → chunk → embed pipeline. Extracted for testability."""
    from crawler.fetch_data import crawl_sources
    from processor.chunker import process_documents
    from processor.embedder import embed_and_store

    documents = crawl_sources(sources)
    chunks = process_documents(documents)
    embed_and_store(chunks)
    return {
        "sources_count": len(sources),
        "documents_crawled": len(documents),
        "chunks_indexed": len(chunks),
    }
