"""Coverage Gap Detector – heuristic nhẹ chạy sau mỗi chat response.

Kiểm tra tín hiệu retrieval / answer để quyết định có nên lưu gap candidate.

Heuristics MVP:
1. retrieval_count == 0 → gap (no_retrieval)
2. retrieval_count < MIN_RETRIEVAL_THRESHOLD → gap (low_retrieval)
3. Không có citations → gap (no_citations)
4. Tất cả citation scores dưới ngưỡng → gap (low_citation_scores)
5. Answer chứa fallback phrases → gap (fallback_answer)

Mỗi tín hiệu trả về tên signal; hàm detect() trả list signals.
Nếu list rỗng → không phải gap.
"""
from __future__ import annotations

from typing import Any

# ─── Configurable thresholds ────────────────────────────────────────────────
MIN_RETRIEVAL_COUNT = 1       # dưới ngưỡng này → low_retrieval
LOW_CITATION_SCORE = 0.3      # tất cả scores dưới ngưỡng này → low_citation_scores

# Phrases cho biết answer là fallback chung chung (trích từ rag/generator.py)
_FALLBACK_PHRASES = [
    "chưa tìm thấy thông tin đủ liên quan",
    "chưa tìm thấy thông tin phù hợp",
    "vui lòng cung cấp thêm tài liệu",
    "vui lòng đặt câu hỏi cụ thể hơn",
    "nạp thêm tài liệu đúng chủ đề",
]


def detect(
    *,
    retrieval_count: int,
    citations: list[dict[str, Any]] | None = None,
    answer: str = "",
) -> list[str]:
    """Run heuristic checks. Returns list of signal names (empty = no gap)."""
    signals: list[str] = []
    citations = citations or []

    # 1. No retrieval at all
    if retrieval_count == 0:
        signals.append("no_retrieval")
    # 2. Low retrieval (but not zero — that's already caught above)
    elif retrieval_count < MIN_RETRIEVAL_COUNT:
        signals.append("low_retrieval")

    # 3. No citations
    if not citations:
        if "no_retrieval" not in signals:
            signals.append("no_citations")
    else:
        # 4. All citation scores below threshold (only if scores are present)
        scores = [c.get("score") for c in citations if c.get("score") is not None]
        if scores and all(s < LOW_CITATION_SCORE for s in scores):
            signals.append("low_citation_scores")

    # 5. Fallback answer phrases
    if answer:
        answer_lower = answer.lower()
        if any(phrase in answer_lower for phrase in _FALLBACK_PHRASES):
            signals.append("fallback_answer")

    return signals


def maybe_persist_gap(
    *,
    question: str,
    answer: str,
    retrieval_count: int,
    citations: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    message_id: str | None = None,
    rewritten_query: str | None = None,
    detected_topic: str | None = None,
) -> int | None:
    """Detect + persist in one call. Returns gap_id if persisted, else None.

    Tách logic detect ra để test dễ; hàm này là convenience wrapper
    cho integration vào chat pipeline.
    """
    signals = detect(
        retrieval_count=retrieval_count,
        citations=citations,
        answer=answer,
    )
    if not signals:
        return None

    from orchestrator import coverage_gap_store

    # Rút gọn citations snapshot: chỉ giữ title, url, score
    citations_snapshot = [
        {
            "title": c.get("title", ""),
            "url": c.get("url", ""),
            "score": c.get("score"),
        }
        for c in (citations or [])
    ]

    return coverage_gap_store.add_gap(
        question=question,
        answer_excerpt=answer[:500] if answer else "",
        retrieval_count=retrieval_count,
        gap_signals=signals,
        citations_snapshot=citations_snapshot,
        session_id=session_id,
        message_id=message_id,
        rewritten_query=rewritten_query,
        detected_topic=detected_topic,
    )
