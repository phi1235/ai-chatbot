from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None
    user_id: str | None = None
    stream: bool = False


class Citation(BaseModel):
    title: str
    url: str = ""
    section: str = ""
    source: str = ""
    score: float | None = None


class TraceInfo(BaseModel):
    request_id: str
    session_id: str
    detected_topic: str | None = None
    retrieval_count: int = 0
    latency_ms: float = 0.0
    safety_flags: list[str] = []
    timings: dict[str, float] = {}
    cache_hit: bool = False
    rewritten_query: str | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    trace: TraceInfo
