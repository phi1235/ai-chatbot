from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from typing import Any

from guardrails import apply_input_guardrails, apply_output_guardrails
from observability import (
    get_logger,
    metrics_registry,
    set_request_id,
)
from orchestrator import store
from orchestrator.cache import CachedAnswer, answer_cache
from orchestrator.memory import session_memory
from orchestrator.smalltalk import get_smalltalk_answer
from schemas.chat import ChatRequest, ChatResponse, Citation, TraceInfo

logger = get_logger(__name__)


def _now_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _citations_from_dicts(items: list[dict[str, Any]]) -> list[Citation]:
    return [Citation(**item) for item in items]


def _persist_user(session_id: str, content: str) -> None:
    """Lưu user message + auto-title nếu là message đầu tiên."""
    is_first = store.session_message_count(session_id) == 0
    store.add_message(session_id, "user", content)
    if is_first:
        store.update_title(session_id, store.auto_title_from_first_message(content))


def _persist_assistant(
    session_id: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
    show_citations: bool = False,
    trace: dict[str, Any] | None = None,
    is_error: bool = False,
) -> None:
    store.add_message(
        session_id,
        "assistant",
        content,
        citations=citations,
        show_citations=show_citations,
        trace=trace,
        is_error=is_error,
    )


def _check_coverage_gap(
    *,
    question: str,
    answer: str,
    retrieval_count: int,
    citations: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    message_id: str | None = None,
    rewritten_query: str | None = None,
    detected_topic: str | None = None,
) -> None:
    """Run coverage gap detector. Silently swallows exceptions to never block chat."""
    try:
        from orchestrator.coverage_gap_detector import maybe_persist_gap

        gap_id = maybe_persist_gap(
            question=question,
            answer=answer,
            retrieval_count=retrieval_count,
            citations=citations,
            session_id=session_id,
            message_id=message_id,
            rewritten_query=rewritten_query,
            detected_topic=detected_topic,
        )
        if gap_id:
            logger.debug("coverage gap persisted", extra={"gap_id": gap_id})
    except Exception:
        logger.debug("coverage gap detection failed", exc_info=True)


def handle_chat(request: ChatRequest) -> ChatResponse:
    request_id = str(uuid.uuid4())
    set_request_id(request_id)
    session_id = request.session_id or str(uuid.uuid4())
    started = time.perf_counter()
    timings: dict[str, float] = {}
    metrics_registry.increment("chat_requests_total")

    t = time.perf_counter()
    input_check = apply_input_guardrails(request.message)
    timings["input_guardrails_ms"] = _now_ms(t)
    safety_flags = list(input_check.flags)
    if not input_check.allowed:
        metrics_registry.increment("chat_blocked_input_total")
        latency_ms = _now_ms(started)
        metrics_registry.observe_latency(latency_ms)
        return ChatResponse(
            answer=input_check.message,
            citations=[],
            trace=TraceInfo(
                request_id=request_id,
                session_id=session_id,
                latency_ms=latency_ms,
                safety_flags=safety_flags,
                timings=timings,
            ),
        )

    history_before = session_memory.get_context(session_id)
    _persist_user(session_id, input_check.text)

    t = time.perf_counter()
    smalltalk_answer = get_smalltalk_answer(input_check.text)
    timings["smalltalk_ms"] = _now_ms(t)
    if smalltalk_answer:
        _persist_assistant(session_id, smalltalk_answer)
        latency_ms = _now_ms(started)
        metrics_registry.observe_latency(latency_ms)
        metrics_registry.increment("chat_smalltalk_total")
        return ChatResponse(
            answer=smalltalk_answer,
            citations=[],
            trace=TraceInfo(
                request_id=request_id,
                session_id=session_id,
                detected_topic="smalltalk",
                retrieval_count=0,
                latency_ms=latency_ms,
                safety_flags=safety_flags,
                timings=timings,
            ),
        )

    # Query rewriting: viết lại follow-up thành câu hỏi standalone cho retrieval
    from orchestrator.rewriter import rewrite_question
    t_rw = time.perf_counter()
    standalone_query, did_rewrite = rewrite_question(input_check.text, history_before)
    timings["rewrite_ms"] = _now_ms(t_rw)
    if did_rewrite:
        metrics_registry.increment("chat_rewrite_total")

    # Answer cache (theo standalone query)
    cache_key = answer_cache.make_key(standalone_query)
    cached = answer_cache.get(cache_key)
    if cached:
        metrics_registry.increment("chat_cache_hit_total")
        _persist_assistant(session_id, cached.answer, citations=cached.citations, show_citations=False)
        latency_ms = _now_ms(started)
        metrics_registry.observe_latency(latency_ms)
        return ChatResponse(
            answer=cached.answer,
            citations=_citations_from_dicts(cached.citations),
            trace=TraceInfo(
                request_id=request_id,
                session_id=session_id,
                detected_topic=cached.detected_topic,
                retrieval_count=cached.retrieval_count,
                latency_ms=latency_ms,
                safety_flags=safety_flags,
                timings=timings,
                cache_hit=True,
                rewritten_query=standalone_query if did_rewrite else None,
            ),
        )

    from rag.pipeline import chat_with_trace

    rag_result = chat_with_trace(
        input_check.text,
        history=history_before,
        retrieval_query=standalone_query,
        session_id=session_id,
    )
    timings.update(rag_result.timings)

    t = time.perf_counter()
    output_check = apply_output_guardrails(rag_result.answer)
    timings["output_guardrails_ms"] = _now_ms(t)
    safety_flags.extend(output_check.flags)
    answer = output_check.text if output_check.allowed else output_check.message
    if not output_check.allowed:
        metrics_registry.increment("chat_blocked_output_total")
    else:
        # Chỉ cache khi output được phép (tránh cache nội dung bị block)
        answer_cache.set(
            cache_key,
            CachedAnswer(
                answer=answer,
                citations=[c.model_dump() for c in rag_result.citations],
                detected_topic=rag_result.detected_topic,
                retrieval_count=rag_result.retrieval_count,
            ),
        )

    latency_ms = _now_ms(started)
    metrics_registry.observe_latency(latency_ms)
    metrics_registry.increment("chat_success_total")
    logger.info(
        "chat completed",
        extra={
            "session_id": session_id,
            "topic": rag_result.detected_topic,
            "latency_ms": latency_ms,
            "rewritten": did_rewrite,
            "retrieval_count": rag_result.retrieval_count,
        },
    )
    trace_info = TraceInfo(
        request_id=request_id,
        session_id=session_id,
        detected_topic=rag_result.detected_topic,
        retrieval_count=rag_result.retrieval_count,
        latency_ms=latency_ms,
        safety_flags=safety_flags,
        timings=timings,
        rewritten_query=standalone_query if did_rewrite else None,
    )
    _persist_assistant(
        session_id,
        answer,
        citations=[c.model_dump() for c in rag_result.citations],
        show_citations=rag_result.show_citations,
        trace=trace_info.model_dump(),
    )

    # Coverage gap detection (fire-and-forget, never blocks response)
    _check_coverage_gap(
        question=input_check.text,
        answer=answer,
        retrieval_count=rag_result.retrieval_count,
        citations=[c.model_dump() for c in rag_result.citations],
        session_id=session_id,
        rewritten_query=standalone_query if did_rewrite else None,
        detected_topic=rag_result.detected_topic,
    )

    return ChatResponse(
        answer=answer,
        citations=rag_result.citations,
        trace=trace_info,
    )


def handle_chat_stream(request: ChatRequest) -> Iterator[dict[str, Any]]:
    """
    Streaming version. Yield events:
        {"type": "meta", "trace": {...}, "citations": [...]}
        {"type": "token", "content": "..."}
        {"type": "done", "trace": {...}, "answer": "...", "safety_flags": [...]}
        {"type": "error", "message": "..."}

    Caller (FastAPI endpoint) chịu trách nhiệm serialize JSON + flush.
    """
    request_id = str(uuid.uuid4())
    set_request_id(request_id)
    session_id = request.session_id or str(uuid.uuid4())
    started = time.perf_counter()
    timings: dict[str, float] = {}
    metrics_registry.increment("chat_requests_total")
    metrics_registry.increment("chat_stream_total")

    t = time.perf_counter()
    input_check = apply_input_guardrails(request.message)
    timings["input_guardrails_ms"] = _now_ms(t)
    safety_flags = list(input_check.flags)

    if not input_check.allowed:
        metrics_registry.increment("chat_blocked_input_total")
        yield {"type": "token", "content": input_check.message}
        yield {
            "type": "done",
            "answer": input_check.message,
            "trace": {
                "request_id": request_id,
                "session_id": session_id,
                "latency_ms": _now_ms(started),
                "safety_flags": safety_flags,
                "timings": timings,
            },
        }
        return

    # Lấy history TRƯỚC khi add turn mới (để khỏi tự include câu user vừa hỏi)
    history_before = session_memory.get_context(session_id)
    _persist_user(session_id, input_check.text)

    t = time.perf_counter()
    smalltalk_answer = get_smalltalk_answer(input_check.text)
    timings["smalltalk_ms"] = _now_ms(t)
    if smalltalk_answer:
        _persist_assistant(session_id, smalltalk_answer)
        metrics_registry.increment("chat_smalltalk_total")
        yield {"type": "token", "content": smalltalk_answer}
        yield {
            "type": "done",
            "answer": smalltalk_answer,
            "trace": {
                "request_id": request_id,
                "session_id": session_id,
                "detected_topic": "smalltalk",
                "retrieval_count": 0,
                "latency_ms": _now_ms(started),
                "safety_flags": safety_flags,
                "timings": timings,
            },
        }
        return

    # Query rewriting: nếu có history, viết lại câu hỏi follow-up thành standalone
    # Standalone query dùng cho retrieval + cache key. Original query vẫn dùng cho LLM cuối
    # (để LLM thấy đúng phong cách user gõ + nhận history qua messages).
    from orchestrator.rewriter import rewrite_question
    t_rw = time.perf_counter()
    standalone_query, did_rewrite = rewrite_question(input_check.text, history_before)
    timings["rewrite_ms"] = _now_ms(t_rw)
    if did_rewrite:
        metrics_registry.increment("chat_rewrite_total")

    # Cache check (theo standalone query - cùng câu chuẩn hóa thì có thể cache lại)
    cache_key = answer_cache.make_key(standalone_query)
    cached = answer_cache.get(cache_key)
    if cached:
        from rag.generator import wants_citations
        metrics_registry.increment("chat_cache_hit_total")
        _persist_assistant(session_id, cached.answer, citations=cached.citations, show_citations=False)
        yield {
            "type": "meta",
            "citations": cached.citations,
            "detected_topic": cached.detected_topic,
            "retrieval_count": cached.retrieval_count,
            "cache_hit": True,
            "show_citations": wants_citations(input_check.text),
        }
        yield {"type": "token", "content": cached.answer}
        yield {
            "type": "done",
            "answer": cached.answer,
            "trace": {
                "request_id": request_id,
                "session_id": session_id,
                "detected_topic": cached.detected_topic,
                "retrieval_count": cached.retrieval_count,
                "latency_ms": _now_ms(started),
                "safety_flags": safety_flags,
                "timings": timings,
                "cache_hit": True,
                "rewritten_query": standalone_query if did_rewrite else None,
            },
        }
        return

    # Retrieval với standalone query (đảm bảo có đủ ngữ cảnh)
    from rag.pipeline import prepare_stream, stream_answer_for

    try:
        setup = prepare_stream(standalone_query, session_id=session_id)
    except Exception as exc:
        yield {"type": "error", "message": str(exc)}
        return
    timings.update(setup.timings)

    yield {
        "type": "meta",
        "citations": [c.model_dump() for c in setup.citations],
        "detected_topic": setup.detected_topic,
        "retrieval_count": len(setup.chunks),
        "cache_hit": False,
        "show_citations": setup.show_citations,
        "rewritten_query": standalone_query if did_rewrite else None,
    }

    # Stream LLM với history (LLM thấy được hội thoại trước để trả lời mạch lạc)
    t_llm = time.perf_counter()
    buffer: list[str] = []
    try:
        for token in stream_answer_for(input_check.text, setup.chunks, history_before):
            buffer.append(token)
            yield {"type": "token", "content": token}
    except Exception as exc:
        yield {"type": "error", "message": str(exc)}
        return
    timings["llm_ms"] = _now_ms(t_llm)

    raw_answer = "".join(buffer).strip()

    # Strip meta-leak (model yếu hay nhắc "CONTEXT", "sample_docs", "(Note:...)").
    # Garbage check sau khi strip - vì strip có thể đã làm answer ổn.
    from rag.generator import _fallback_answer, _looks_like_garbage, strip_meta_leak
    raw_answer = strip_meta_leak(raw_answer)
    is_garbage = _looks_like_garbage(raw_answer) if raw_answer else True
    if is_garbage:
        metrics_registry.increment("chat_garbage_output_total")
        fallback = _fallback_answer(setup.chunks, input_check.text)
        yield {
            "type": "blocked",
            "message": fallback,
            "reason": "Model output looked like prompt-leak / garbage.",
        }
        final_answer = fallback
        safety_flags.append("garbage_output")
    else:
        # Output guardrail (sau khi stream xong)
        t = time.perf_counter()
        output_check = apply_output_guardrails(raw_answer)
        timings["output_guardrails_ms"] = _now_ms(t)
        safety_flags.extend(output_check.flags)

        if not output_check.allowed:
            metrics_registry.increment("chat_blocked_output_total")
            final_answer = output_check.message
            yield {
                "type": "blocked",
                "message": final_answer,
                "reason": "Output guardrail rejected the streamed answer.",
            }
        else:
            final_answer = output_check.text or raw_answer
            answer_cache.set(
                cache_key,
                CachedAnswer(
                    answer=final_answer,
                    citations=[c.model_dump() for c in setup.citations],
                    detected_topic=setup.detected_topic,
                    retrieval_count=len(setup.chunks),
                ),
            )

    latency_ms = _now_ms(started)
    metrics_registry.observe_latency(latency_ms)
    metrics_registry.increment("chat_success_total")

    trace_dict = {
        "request_id": request_id,
        "session_id": session_id,
        "detected_topic": setup.detected_topic,
        "retrieval_count": len(setup.chunks),
        "latency_ms": latency_ms,
        "safety_flags": safety_flags,
        "timings": timings,
        "cache_hit": False,
        "rewritten_query": standalone_query if did_rewrite else None,
    }
    _persist_assistant(
        session_id,
        final_answer,
        citations=[c.model_dump() for c in setup.citations],
        show_citations=setup.show_citations,
        trace=trace_dict,
        is_error="garbage_output" in safety_flags,
    )

    # Coverage gap detection (fire-and-forget, never blocks response)
    _check_coverage_gap(
        question=input_check.text,
        answer=final_answer,
        retrieval_count=len(setup.chunks),
        citations=[c.model_dump() for c in setup.citations],
        session_id=session_id,
        rewritten_query=standalone_query if did_rewrite else None,
        detected_topic=setup.detected_topic,
    )

    yield {
        "type": "done",
        "answer": final_answer,
        "trace": trace_dict,
    }
