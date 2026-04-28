"""Heuristic recommendation engine for coverage gap clusters.

Given a cluster summary + source/topic context, produce an actionable
recommendation dict that tells admin what to do next.

Design:
- Pure functions, no side effects, easy to unit test.
- Heuristic rules only (no LLM, no embedding).
- Returns a recommendation dict with:
    recommended_action, recommendation_reason, candidate_topic,
    suggested_search_query, priority, signals.
"""
from __future__ import annotations

import json
from pathlib import Path

# ─── Topic / source inventory helpers ────────────────────────────────────────

def get_topic_source_context(sources_dir: str | Path = "sources") -> dict[str, int]:
    """Return {topic: source_count} for every known topic file.

    Scans ``sources/*.json`` – same convention as ``api/admin.py``.
    """
    sdir = Path(sources_dir)
    if not sdir.exists():
        return {}
    ctx: dict[str, int] = {}
    for p in sdir.glob("*.json"):
        topic = p.stem
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
            ctx[topic] = len(items) if isinstance(items, list) else 0
        except (json.JSONDecodeError, OSError):
            ctx[topic] = 0
    return ctx


# ─── Signal extraction ───────────────────────────────────────────────────────

def _extract_signals(cluster: dict, topic_sources: dict[str, int]) -> list[str]:
    """Derive a list of human-readable signal tags from cluster + context."""
    signals: list[str] = []
    topic = (cluster.get("detected_topic") or "").strip().lower()
    count = cluster.get("count", 0)

    # Topic presence
    if topic:
        signals.append("topic_detected")
        if topic in topic_sources:
            signals.append("topic_has_sources")
            if topic_sources[topic] <= 2:
                signals.append("topic_sources_thin")
        else:
            signals.append("topic_no_sources")
    else:
        signals.append("topic_unknown")

    # Repetition
    if count >= 5:
        signals.append("high_repetition")
    elif count >= 3:
        signals.append("moderate_repetition")
    else:
        signals.append("low_repetition")

    # Status breakdown – lots of 'new' means unresolved
    statuses = cluster.get("statuses", {})
    total_new = statuses.get("new", 0)
    if total_new > 0 and total_new >= count * 0.5:
        signals.append("mostly_unresolved")

    # Resolution breakdown – existing resolutions hint prior actions
    resolutions = cluster.get("resolutions", {})
    if resolutions:
        signals.append("has_prior_resolutions")

    return signals


# ─── Priority heuristic ──────────────────────────────────────────────────────

def _compute_priority(count: int, signals: list[str]) -> str:
    """Return 'high' | 'medium' | 'low'."""
    if count >= 5 or "high_repetition" in signals:
        return "high"
    if count >= 3 or "topic_detected" in signals:
        return "medium"
    return "low"


# ─── Search query builder ────────────────────────────────────────────────────

def _build_search_query(cluster: dict) -> str:
    """Build a suggested search query from cluster data."""
    topic = (cluster.get("detected_topic") or "").strip()
    rep_q = (cluster.get("representative_question") or "").strip()

    # Prefer representative question as search basis
    base = rep_q or cluster.get("cluster_key", "")
    # Strip topic prefix from cluster_key if it leaked in
    if ":" in base and not rep_q:
        base = base.split(":", 1)[1]

    parts = []
    if topic:
        parts.append(topic)
    if base:
        parts.append(base)
    parts.append("official docs")

    return " ".join(parts)


# ─── Core recommendation logic ───────────────────────────────────────────────

def recommend_for_cluster(
    cluster: dict,
    topic_sources: dict[str, int] | None = None,
) -> dict:
    """Produce a recommendation dict for a single cluster summary.

    Parameters
    ----------
    cluster : dict
        A cluster summary as returned by ``coverage_gap_store.list_clusters``.
        Expected keys: cluster_key, representative_question, detected_topic,
        count, statuses, resolutions, sample_gap_ids.
    topic_sources : dict[str, int] | None
        Topic → source-item-count mapping (from ``get_topic_source_context``).
        If ``None``, source-aware heuristics are skipped.

    Returns
    -------
    dict with keys:
        recommended_action, recommendation_reason, candidate_topic,
        suggested_search_query, priority, signals.
    """
    topic_sources = topic_sources or {}
    signals = _extract_signals(cluster, topic_sources)
    topic = (cluster.get("detected_topic") or "").strip().lower()
    count = cluster.get("count", 0)
    priority = _compute_priority(count, signals)
    search_query = _build_search_query(cluster)

    # ── Rule 1: recrawl ──────────────────────────────────────────────────
    # Topic exists, has sources, but gaps keep appearing → stale/insufficient
    if (
        "topic_detected" in signals
        and "topic_has_sources" in signals
        and "topic_sources_thin" not in signals
        and count >= 2
    ):
        return {
            "recommended_action": "recrawl",
            "recommendation_reason": (
                f"Topic '{topic}' already has sources, but this cluster "
                f"has {count} repeated gaps — existing content may be "
                "stale or insufficient. Recrawling may help."
            ),
            "candidate_topic": topic,
            "suggested_search_query": search_query,
            "priority": priority,
            "signals": signals,
        }

    # ── Rule 2: add_source ───────────────────────────────────────────────
    # Topic detected but no sources, or sources very thin
    if "topic_detected" in signals and (
        "topic_no_sources" in signals or "topic_sources_thin" in signals
    ):
        reason_detail = (
            "no source files yet" if "topic_no_sources" in signals
            else "very few sources"
        )
        return {
            "recommended_action": "add_source",
            "recommendation_reason": (
                f"Topic '{topic}' has {reason_detail}. "
                f"With {count} gap(s) in this cluster, adding a new source "
                "is the most effective next step."
            ),
            "candidate_topic": topic,
            "suggested_search_query": search_query,
            "priority": priority,
            "signals": signals,
        }

    # ── Rule 3: add_source (topic unknown but high repetition) ───────────
    if "topic_unknown" in signals and count >= 3:
        return {
            "recommended_action": "add_source",
            "recommendation_reason": (
                f"No topic detected, but {count} repeated gaps suggest "
                "a real knowledge gap. Consider identifying a topic and "
                "adding a relevant source."
            ),
            "candidate_topic": "",
            "suggested_search_query": search_query,
            "priority": priority,
            "signals": signals,
        }

    # ── Fallback: review_only ────────────────────────────────────────────
    return {
        "recommended_action": "review_only",
        "recommendation_reason": (
            "Not enough signal to recommend a specific action. "
            "Review the cluster manually to decide next steps."
        ),
        "candidate_topic": topic or "",
        "suggested_search_query": search_query,
        "priority": priority,
        "signals": signals,
    }
