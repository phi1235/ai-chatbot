import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from config.settings import settings
from schemas.chat import Citation
from rag.retriever import infer_topic, retrieve
from rag.generator import generate_answer, stream_answer, wants_citations


@dataclass(slots=True)
class RagResult:
    answer: str
    citations: list[Citation]
    detected_topic: str | None
    retrieval_count: int
    timings: dict[str, float] = field(default_factory=dict)
    chunks: list[dict[str, Any]] = field(default_factory=list)
    show_citations: bool = False


@dataclass(slots=True)
class RagStreamSetup:
    """Trả về sau khi đã retrieve xong, sẵn sàng stream answer."""
    chunks: list[dict[str, Any]]
    citations: list[Citation]
    detected_topic: str | None
    timings: dict[str, float]
    show_citations: bool = False


def _build_citations(chunks: list[dict]) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[tuple[str, str, str]] = set()
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        key = (
            str(metadata.get("title", "")),
            str(metadata.get("url", "")),
            str(metadata.get("section", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            Citation(
                title=metadata.get("title", "Untitled"),
                url=metadata.get("url", ""),
                section=metadata.get("section", ""),
                source=metadata.get("source", ""),
                score=chunk.get("score"),
            )
        )
        if len(citations) >= 3:
            break
    return citations


def chat(query: str) -> str:
    """RAG pipeline non-streaming, trả về answer string."""
    return chat_with_trace(query).answer


def chat_with_trace(
    query: str,
    history: list[dict[str, str]] | None = None,
    retrieval_query: str | None = None,
) -> RagResult:
    """
    `query`: câu hỏi gốc của user (dùng cho LLM cuối)
    `retrieval_query`: câu standalone (nếu khác) dùng cho retrieval. Mặc định = query.
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("Message không được để trống.")
    retrieval_q = (retrieval_query or normalized_query).strip()

    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    detected_topic = infer_topic(retrieval_q)
    timings["topic_detect_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    t1 = time.perf_counter()
    relevant_chunks = retrieve(
        retrieval_q,
        top_k=settings.retrieval_top_k,
        topic=detected_topic,
    )
    timings["retrieval_ms"] = round((time.perf_counter() - t1) * 1000, 2)

    t2 = time.perf_counter()
    answer = generate_answer(normalized_query, relevant_chunks, history)
    timings["llm_ms"] = round((time.perf_counter() - t2) * 1000, 2)

    return RagResult(
        answer=answer,
        citations=_build_citations(relevant_chunks),
        detected_topic=detected_topic,
        retrieval_count=len(relevant_chunks),
        timings=timings,
        chunks=relevant_chunks,
        show_citations=wants_citations(normalized_query),
    )


def prepare_stream(query: str) -> RagStreamSetup:
    """Chạy phần retrieval, trả về context để caller stream answer riêng."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("Message không được để trống.")

    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    detected_topic = infer_topic(normalized_query)
    timings["topic_detect_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    t1 = time.perf_counter()
    chunks = retrieve(
        normalized_query,
        top_k=settings.retrieval_top_k,
        topic=detected_topic,
    )
    timings["retrieval_ms"] = round((time.perf_counter() - t1) * 1000, 2)

    return RagStreamSetup(
        chunks=chunks,
        citations=_build_citations(chunks),
        detected_topic=detected_topic,
        timings=timings,
        show_citations=wants_citations(normalized_query),
    )


def stream_answer_for(
    query: str,
    chunks: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
) -> Iterator[str]:
    yield from stream_answer(query, chunks, history)


if __name__ == "__main__":
    query = "What is Python?"
    result = chat_with_trace(query)
    print(f"Q: {query}")
    print(f"A: {result.answer}")
    print(f"Timings: {result.timings}")
