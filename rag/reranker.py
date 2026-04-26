"""Cross-encoder re-ranker.

Khác với bi-encoder (sentence-transformers cho embedding):
- Bi-encoder: encode query + doc riêng → cosine similarity. Nhanh nhưng kém precision.
- Cross-encoder: encode (query, doc) cùng lúc → score chính xác hơn nhiều,
  nhưng chậm hơn O(N) (mỗi chunk 1 forward pass).

Pipeline RAG production:
    1. Hybrid retrieve (BM25 + vector + RRF) → top 20 candidates (nhanh)
    2. Cross-encoder rerank → top 3 (chậm hơn nhưng chỉ 20 pairs)

Default OFF vì cộng 200-500ms. Bật qua RERANKER_ENABLED=true.
"""
from __future__ import annotations

import logging
from threading import Lock
from typing import Any

from config.settings import settings

logger = logging.getLogger(__name__)

# Lazy init - chỉ load model lần đầu được dùng (~280MB download lần đầu)
_model: Any = None
_lock = Lock()


def _get_model() -> Any:
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        # Import lazy để khi RERANKER_ENABLED=false không tốn import time
        from sentence_transformers import CrossEncoder
        logger.info(f"Loading cross-encoder reranker: {settings.reranker_model}")
        _model = CrossEncoder(settings.reranker_model, max_length=512)
    return _model


def warmup() -> None:
    """Preload model + dummy inference để tránh cold start ở request đầu."""
    if not settings.reranker_enabled:
        return
    try:
        model = _get_model()
        model.predict([("warmup", "warmup")])
    except Exception as exc:
        logger.warning(f"Reranker warmup failed (sẽ retry khi query): {exc}")


def rerank(
    query: str,
    chunks: list[dict[str, Any]],
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Rerank chunks theo (query, content) score từ cross-encoder.

    Trả về top_k chunks điểm cao nhất, kèm field `rerank_score`.
    Nếu reranker chưa load được hoặc input rỗng → trả nguyên `chunks[:top_k]`.
    """
    if not chunks:
        return []
    if not settings.reranker_enabled:
        return chunks[:top_k]

    try:
        model = _get_model()
    except Exception as exc:
        logger.warning(f"Reranker không khả dụng, fallback về thứ tự gốc: {exc}")
        return chunks[:top_k]

    # Cross-encoder predict accept list of (query, doc) pairs
    pairs = [(query, c.get("content", "") or "") for c in chunks]
    try:
        scores = model.predict(pairs)
    except Exception as exc:
        logger.warning(f"Reranker predict failed, fallback: {exc}")
        return chunks[:top_k]

    # Pair score với chunk, sort giảm dần
    scored = []
    for chunk, score in zip(chunks, scores):
        c = dict(chunk)
        c["rerank_score"] = float(score)
        scored.append(c)
    scored.sort(key=lambda c: c["rerank_score"], reverse=True)
    return scored[:top_k]
