"""Hybrid search: BM25 (keyword) + Vector (semantic) với RRF fusion.

Tại sao cần hybrid:
    - Vector tìm theo nghĩa, mạnh ở câu hỏi conceptual.
    - BM25 tìm theo keyword chính xác, mạnh ở tên hàm/command/version/code.
    - RRF (Reciprocal Rank Fusion) merge 2 ranking → tận dụng cả 2.

Triển khai:
    - BM25Okapi từ rank_bm25 (in-memory, ~5KB lib, không cần Elasticsearch)
    - Persist tokenized corpus + metadata xuống pickle
    - Build từ Chroma collection (đảm bảo cùng nguồn dữ liệu)
"""
from __future__ import annotations

import logging
import pickle
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from rank_bm25 import BM25Okapi

from config.settings import settings

logger = logging.getLogger(__name__)

# Stopwords VN + EN cơ bản, tránh inflate score do từ cực phổ biến
_STOPWORDS = {
    # Vietnamese (đã bỏ dấu)
    "la", "co", "de", "khong", "va", "the", "nao", "mot", "nhung", "voi", "cua",
    "cho", "ve", "do", "duoc", "hay", "toi", "ban", "anh", "tu", "trong", "tren",
    "duoi", "nay", "kia", "ay", "thi", "ra", "vao", "den", "tai", "boi",
    # English
    "is", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for",
    "with", "by", "from", "as", "be", "are", "was", "were", "this", "that",
    "it", "what", "how", "when", "where", "why",
}


def _strip_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt cho BM25 match được cả có dấu lẫn không dấu."""
    nfkd = unicodedata.normalize("NFKD", text)
    no_marks = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return no_marks.replace("đ", "d").replace("Đ", "D")


def tokenize(text: str) -> list[str]:
    """
    Tokenize cho BM25:
    - Lowercase + bỏ dấu
    - Tách theo non-alphanumeric (giữ token chứa số như 'v3.1.1')
    - Bỏ stopwords và token < 2 ký tự
    - Camel/snake case không tách (giữ 'useState' nguyên)
    """
    normalized = _strip_diacritics(text.lower())
    # Match alnum sequence (giữ underscore, dot trong 'v1.2.3')
    raw = re.findall(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", normalized)
    return [t for t in raw if len(t) >= 2 and t not in _STOPWORDS]


@dataclass(slots=True)
class IndexedChunk:
    """Chunk đã tokenize sẵn để build BM25, kèm metadata để return."""
    content: str
    metadata: dict[str, Any]
    tokens: list[str]


@dataclass(slots=True)
class BM25Index:
    """Wrap rank_bm25 + corpus + metadata. Không thread-safe khi rebuild,
    cần lock bên ngoài; query thì OK đa luồng."""
    chunks: list[IndexedChunk]
    bm25: BM25Okapi | None

    @classmethod
    def empty(cls) -> BM25Index:
        return cls(chunks=[], bm25=None)

    def is_ready(self) -> bool:
        return self.bm25 is not None and len(self.chunks) > 0

    def search(
        self,
        query: str,
        top_k: int = 10,
        topic: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_ready():
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores = self.bm25.get_scores(query_tokens)  # numpy array, len = N

        # Pair (score, idx) rồi rank
        scored = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        results: list[dict[str, Any]] = []
        for idx, score in scored:
            if score <= 0:
                continue
            chunk = self.chunks[idx]
            if topic and chunk.metadata.get("topic") != topic:
                continue
            results.append({
                "content": chunk.content,
                "metadata": chunk.metadata,
                "bm25_score": float(score),
            })
            if len(results) >= top_k:
                break
        return results


# ─── Module-level singleton ─────────────────────────────────────────────────
_index: BM25Index = BM25Index.empty()
_lock = Lock()


def get_index() -> BM25Index:
    return _index


def load_or_build() -> BM25Index:
    """Load pickle nếu có, miss → build từ Chroma. Trả về index hiện tại."""
    global _index
    path = Path(settings.bm25_index_path)
    if path.exists():
        try:
            with path.open("rb") as f:
                data = pickle.load(f)
            _index = BM25Index(
                chunks=data["chunks"],
                bm25=BM25Okapi([c.tokens for c in data["chunks"]]) if data["chunks"] else None,
            )
            logger.info(f"BM25 index loaded: {len(_index.chunks)} chunks from {path}")
            return _index
        except Exception as exc:
            logger.warning(f"Không load được BM25 index, sẽ rebuild: {exc}")

    return rebuild_from_chroma()


def rebuild_from_chroma() -> BM25Index:
    """Iterate toàn bộ Chroma collection, tokenize, persist."""
    global _index
    # Import lazy để tránh circular
    from rag.retriever import collection

    with _lock:
        all_data = collection.get(include=["documents", "metadatas"])
        documents = all_data.get("documents", []) or []
        metadatas = all_data.get("metadatas", []) or []

        chunks: list[IndexedChunk] = []
        for doc, meta in zip(documents, metadatas):
            if not doc:
                continue
            tokens = tokenize(doc)
            if not tokens:
                continue
            chunks.append(IndexedChunk(content=doc, metadata=meta or {}, tokens=tokens))

        bm25 = BM25Okapi([c.tokens for c in chunks]) if chunks else None
        _index = BM25Index(chunks=chunks, bm25=bm25)

        # Persist
        path = Path(settings.bm25_index_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump({"chunks": chunks}, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"BM25 index rebuilt: {len(chunks)} chunks → {path}")

    return _index


# ─── RRF fusion ─────────────────────────────────────────────────────────────
def rrf_fuse(
    rankings: list[list[dict[str, Any]]],
    k: int | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """
    Reciprocal Rank Fusion: gộp nhiều ranking thành 1.

    score(doc) = Σ 1 / (k + rank_in_each_source)

    `k` lớn → giảm trọng số top results (60 là chuẩn paper).
    Doc nào xuất hiện nhiều nguồn + xếp cao trong từng nguồn sẽ điểm cao nhất.
    """
    if k is None:
        k = settings.rrf_k

    fused_scores: dict[str, float] = {}
    fused_chunks: dict[str, dict[str, Any]] = {}

    for ranking in rankings:
        for rank, chunk in enumerate(ranking):
            key = _chunk_key(chunk)
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            # Giữ chunk đầu tiên gặp (vector thường có 'score'/'distance', BM25 có 'bm25_score')
            if key not in fused_chunks:
                fused_chunks[key] = chunk

    # Sort theo fused score giảm dần
    sorted_keys = sorted(fused_scores.keys(), key=lambda k: fused_scores[k], reverse=True)
    out: list[dict[str, Any]] = []
    for key in sorted_keys[:top_k]:
        chunk = dict(fused_chunks[key])
        chunk["rrf_score"] = round(fused_scores[key], 4)
        out.append(chunk)
    return out


def _chunk_key(chunk: dict[str, Any]) -> str:
    """Khoá định danh duy nhất cho 1 chunk - dùng để dedupe khi merge."""
    md = chunk.get("metadata") or {}
    # Ưu tiên url + section nếu có (cùng url + section khả năng cao là cùng chunk)
    url = md.get("url", "")
    section = md.get("section", "")
    title = md.get("title", "")
    if url:
        return f"{url}|{section}"
    # Fallback: hash content preview
    return f"{title}|{(chunk.get('content') or '')[:80]}"
