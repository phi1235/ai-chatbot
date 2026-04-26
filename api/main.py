import json
from collections.abc import Iterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from config.settings import settings
from observability import metrics_registry
from orchestrator import handle_chat, handle_chat_stream, store
from orchestrator.rate_limiter import is_allowed
from rag.errors import RetrievalError
from schemas.chat import ChatRequest, ChatResponse

app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def _startup_warmup() -> None:
    """Preload embedding model + ChromaDB + BM25 index để request đầu không cold-start."""
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
    return {"deleted": session_id}


@app.patch("/sessions/{session_id}")
async def rename_session(session_id: str, body: dict):
    title = (body or {}).get("title", "")
    if not title:
        raise HTTPException(status_code=400, detail="title không được để trống.")
    store.update_title(session_id, title)
    return {"id": session_id, "title": title}
