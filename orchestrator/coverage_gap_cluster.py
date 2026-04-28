"""Heuristic clustering for coverage gaps.

Provides a stable, deterministic cluster key from a gap's question/query
and topic so that near-duplicate gaps are grouped together.

Cluster key = ``[topic:]normalized_text`` where *normalized_text* is:
- prefer ``rewritten_query`` over ``question``
- lowercase
- strip leading/trailing whitespace
- remove basic punctuation (keeps alphanumeric + spaces)
- collapse multiple spaces into one

The optional topic prefix prevents cross-topic collisions when the same
phrasing appears in different knowledge domains.
"""
from __future__ import annotations

import re
import unicodedata

# Pre-compiled patterns
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize a question/query string for clustering.

    >>> normalize_text("  How to deploy  Kubernetes pods??  ")
    'how to deploy kubernetes pods'
    >>> normalize_text("")
    ''
    """
    if not text:
        return ""
    # NFC normalize unicode first
    t = unicodedata.normalize("NFC", text)
    t = t.lower().strip()
    t = _PUNCT_RE.sub(" ", t)
    t = _SPACE_RE.sub(" ", t).strip()
    return t


def make_cluster_key(
    *,
    question: str,
    rewritten_query: str | None = None,
    detected_topic: str | None = None,
) -> str:
    """Build a stable cluster key for a coverage gap.

    Priority: ``rewritten_query`` > ``question``.
    If ``detected_topic`` is provided, it is prepended as ``topic:`` prefix.

    >>> make_cluster_key(question="How to deploy pods?")
    'how to deploy pods'
    >>> make_cluster_key(question="Q", rewritten_query="How to deploy K8s pods?", detected_topic="kubernetes")
    'kubernetes:how to deploy k8s pods'
    """
    raw = (rewritten_query or "").strip() or (question or "").strip()
    normalized = normalize_text(raw)

    topic = (detected_topic or "").strip().lower()
    if topic:
        return f"{topic}:{normalized}"
    return normalized
