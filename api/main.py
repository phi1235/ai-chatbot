import hashlib
import json
from collections.abc import Iterator
from datetime import datetime

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel as _BaseModel

from api.admin import router as admin_router
from config.settings import settings
from observability import metrics_registry
from orchestrator import handle_chat, handle_chat_stream, store
from orchestrator.rate_limiter import is_allowed
from rag.errors import RetrievalError
from schemas.chat import ChatRequest, ChatResponse

app = FastAPI(title=settings.app_name)
app.include_router(admin_router)


@app.on_event("startup")
async def _startup_warmup() -> None:
    """Preload embedding model + ChromaDB + BM25 index để request đầu không cold-start.
    Also start the background scheduler for periodic health checks.
    """
    try:
        from rag.retriever import warmup
        warmup()
    except Exception:
        pass
    if settings.hybrid_search_enabled:
        try:
            from rag.hybrid import load_or_build
            load_or_build()
        except Exception:
            pass
    if settings.reranker_enabled:
        try:
            from rag.reranker import warmup as rerank_warmup
            rerank_warmup()
        except Exception:
            pass
    try:
        from orchestrator import scheduler
        await scheduler.start_scheduler_task()
    except Exception:
        pass


@app.on_event("shutdown")
async def _shutdown_cleanup() -> None:
    """Stop background tasks on shutdown."""
    try:
        from orchestrator import scheduler
        await scheduler.stop_scheduler_task()
    except Exception:
        pass


def _check_gateway(req: ChatRequest, request: Request, x_api_key: str | None) -> None:
    if settings.api_keys and x_api_key not in settings.api_keys:
        raise HTTPException(status_code=401, detail="API key không hợp lệ.")
    identity = req.user_id or req.session_id or (request.client.host if request.client else "anonymous")
    if not is_allowed(identity):
        raise HTTPException(status_code=429, detail="Bạn gửi quá nhiều request. Hãy thử lại sau.")


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    req: ChatRequest,
    request: Request,
    x_api_key: str | None = Header(default=None),
):
    """Chat endpoint non-streaming."""
    _check_gateway(req, request, x_api_key)
    try:
        return handle_chat(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RetrievalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _ndjson_stream(req: ChatRequest) -> Iterator[bytes]:
    """Wrap orchestrator stream events thành NDJSON bytes."""
    try:
        for event in handle_chat_stream(req):
            yield (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
    except ValueError as exc:
        yield (json.dumps({"type": "error", "message": str(exc)}) + "\n").encode("utf-8")
    except RetrievalError as exc:
        yield (json.dumps({"type": "error", "message": str(exc)}) + "\n").encode("utf-8")
    except RuntimeError as exc:
        yield (json.dumps({"type": "error", "message": str(exc)}) + "\n").encode("utf-8")


@app.post("/chat/stream")
async def chat_stream_endpoint(
    req: ChatRequest,
    request: Request,
    x_api_key: str | None = Header(default=None),
):
    """Chat endpoint streaming (NDJSON). Mỗi dòng là 1 JSON event:
        {"type": "meta", ...}
        {"type": "token", "content": "..."}
        {"type": "done", "trace": {...}, ...}
        {"type": "error", "message": "..."}
        {"type": "blocked", "message": "..."}
    """
    _check_gateway(req, request, x_api_key)
    return StreamingResponse(
        _ndjson_stream(req),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/")
async def root():
    return {
        "message": "AI Chatbot API is running with Gateway + Orchestrator + RAG + Guardrails + OpenRouter API",
        "environment": settings.environment,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/metrics")
async def metrics():
    return metrics_registry.snapshot()


# ─── Sessions / Conversations ───────────────────────────────────────────────
@app.get("/sessions")
async def list_sessions():
    """Liệt kê các session đã có message."""
    return {"sessions": store.list_sessions()}


@app.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """Lấy toàn bộ message của 1 session để UI restore."""
    return {"session_id": session_id, "messages": store.get_messages(session_id)}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    store.delete_session(session_id)
    # Cũng xoá chunks của file đã upload trong session đó
    try:
        from processor.embedder import delete_session_chunks
        delete_session_chunks(session_id)
    except Exception:
        pass
    return {"deleted": session_id}


@app.post("/sessions/{session_id}/upload")
async def upload_file(session_id: str, file: UploadFile = File(...)):
    """Upload PDF/DOCX/MD/TXT vào session knowledge base.

    File được parse → chunk → embed với metadata `session_id` để
    retriever ưu tiên khi user hỏi trong session đó.
    """
    from processor.chunker import process_documents
    from processor.embedder import embed_and_store
    from processor.file_parser import FileParseError, parse_file

    data = await file.read()
    filename = file.filename or "uploaded"

    try:
        text = parse_file(filename, data)
    except FileParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="File parse ra nội dung rỗng.")

    # Build doc_id ổn định theo (session_id, filename, content hash) để re-upload
    # cùng file ghi đè chứ không tạo duplicate
    digest = hashlib.sha1(f"{session_id}|{filename}|{text}".encode()).hexdigest()[:10]
    doc_id = f"upload-{session_id[:8]}-{digest}"
    doc = {
        "id": doc_id,
        "title": filename,
        "url": "",
        "content": text,
        "topic": "user_upload",
        "source": "upload",
        "updated_at": datetime.utcnow().date().isoformat(),
        "session_id": session_id,
    }
    chunks = process_documents([doc])
    # Truyền session_id qua từng chunk để embedder lưu vào metadata
    for c in chunks:
        c["session_id"] = session_id
    embed_and_store(chunks)

    # Đảm bảo session record tồn tại trong DB conversations để hiển thị trong sidebar
    store.ensure_session(session_id)

    return {
        "session_id": session_id,
        "filename": filename,
        "doc_id": doc_id,
        "chars": len(text),
        "chunks": len(chunks),
    }


@app.get("/sessions/{session_id}/uploads")
async def list_session_uploads(session_id: str):
    """Liệt kê file đã upload trong session (group by doc_id)."""
    from processor.embedder import collection
    try:
        result = collection.get(where={"session_id": session_id}, include=["metadatas"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    metas = result.get("metadatas", []) or []
    seen: dict[str, dict] = {}
    for m in metas:
        doc_id = (m or {}).get("doc_id", "")
        if doc_id and doc_id not in seen:
            seen[doc_id] = {
                "doc_id": doc_id,
                "filename": m.get("title", "unknown"),
                "updated_at": m.get("updated_at", ""),
            }
    files = list(seen.values())
    # Đếm chunks per doc_id
    for m in metas:
        doc_id = (m or {}).get("doc_id", "")
        if doc_id in seen:
            seen[doc_id]["chunks"] = seen[doc_id].get("chunks", 0) + 1
    return {"session_id": session_id, "files": files}


@app.delete("/sessions/{session_id}/uploads/{doc_id}")
async def delete_upload(session_id: str, doc_id: str):
    """Xoá 1 file upload (theo doc_id) khỏi session."""
    from processor.embedder import collection
    try:
        existing = collection.get(
            where={"$and": [{"session_id": session_id}, {"doc_id": doc_id}]},
            include=[],
        )
        ids = existing.get("ids", []) or []
        if ids:
            collection.delete(ids=ids)
            from processor.embedder import _rebuild_bm25_if_enabled
            _rebuild_bm25_if_enabled()
        return {"deleted": doc_id, "chunks": len(ids)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.patch("/sessions/{session_id}")
async def rename_session(session_id: str, body: dict):
    title = (body or {}).get("title", "")
    if not title:
        raise HTTPException(status_code=400, detail="title không được để trống.")
    store.update_title(session_id, title)
    return {"id": session_id, "title": title}


# ─── Feedback (user-facing) ─────────────────────────────────────────────────
class _FeedbackSubmit(_BaseModel):
    session_id: str | None = None
    message_id: str | None = None
    question: str
    answer: str
    feedback_type: str  # 'up' | 'down'
    note: str | None = None


@app.post("/feedback")
async def submit_feedback(req: _FeedbackSubmit):
    """User-facing endpoint to submit feedback for a chatbot answer."""
    from orchestrator import feedback_store

    if req.feedback_type not in ("up", "down"):
        raise HTTPException(status_code=400, detail="feedback_type phải là 'up' hoặc 'down'.")
    if not (req.question or "").strip() or not (req.answer or "").strip():
        raise HTTPException(status_code=400, detail="question và answer không được trống.")

    try:
        feedback_id = feedback_store.add_feedback(
            question=req.question,
            answer=req.answer,
            feedback_type=req.feedback_type,
            session_id=req.session_id,
            message_id=req.message_id,
            note=req.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"id": feedback_id, "feedback_type": req.feedback_type}
