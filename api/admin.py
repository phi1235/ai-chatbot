"""Admin endpoints — backend cho admin portal UI.

Tách thành router riêng để: gắn auth dễ hơn về sau, group rõ ràng trong /docs.

Endpoints:
    GET    /admin/sources              - list tất cả topics + URLs
    POST   /admin/sources/{topic}      - add URL vào topic
    DELETE /admin/sources/{topic}      - xoá URL khỏi topic (body: location)
    POST   /admin/ingest               - trigger crawl + ingest cho 1 topic hoặc URL list
    POST   /admin/health-check         - run check_sources, trả JSON
    GET    /admin/stats                - chunks per topic, cache, BM25
    POST   /admin/cache/clear          - xoá answer cache
    POST   /admin/bm25/rebuild         - rebuild BM25 index từ Chroma
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from observability import get_logger

router = APIRouter(prefix="/admin", tags=["admin"])
logger = get_logger(__name__)

SOURCES_DIR = Path("sources")


# ─── Models ─────────────────────────────────────────────────────────────────
class SourceItem(BaseModel):
    location: str
    topic: str
    title: str = ""
    source: str = "website"


class IngestRequest(BaseModel):
    topic: str | None = None
    urls: list[SourceItem] | None = None
    reset: bool = False


class BatchRecrawlRequest(BaseModel):
    urls: list[str]


# ─── Sources CRUD ───────────────────────────────────────────────────────────
@router.get("/sources")
async def list_sources():
    """List tất cả topics + URLs. Trả về dạng grouped by topic."""
    if not SOURCES_DIR.exists():
        return {"topics": []}
    topics = []
    for path in sorted(SOURCES_DIR.glob("*.json")):
        topic_name = path.stem
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(items, list):
                items = []
        except json.JSONDecodeError:
            items = []
        topics.append({
            "topic": topic_name,
            "file": str(path),
            "count": len(items),
            "items": items,
        })
    return {"topics": topics}


@router.post("/sources/{topic}")
async def add_source(topic: str, item: SourceItem):
    """Thêm URL vào topic file. Tạo file nếu chưa có."""
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCES_DIR / f"{topic}.json"
    items: list[dict[str, Any]] = []
    if path.exists():
        try:
            items = json.loads(path.read_text(encoding="utf-8")) or []
        except json.JSONDecodeError:
            items = []

    new_item = item.model_dump()
    new_item["topic"] = topic  # đảm bảo topic khớp filename
    if not new_item.get("title"):
        new_item["title"] = item.location

    # Dedupe theo location
    if any(it.get("location") == item.location for it in items):
        raise HTTPException(status_code=409, detail="URL đã tồn tại trong topic này.")

    items.append(new_item)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"topic": topic, "added": new_item, "total": len(items)}


@router.delete("/sources/{topic}")
async def delete_source(topic: str, body: dict = Body(...)):
    """Xoá URL khỏi topic. Body: {"location": "..."}"""
    location = body.get("location")
    if not location:
        raise HTTPException(status_code=400, detail="Thiếu 'location' trong body.")
    path = SOURCES_DIR / f"{topic}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Topic không tồn tại: {topic}")
    items = json.loads(path.read_text(encoding="utf-8")) or []
    new_items = [it for it in items if it.get("location") != location]
    if len(new_items) == len(items):
        raise HTTPException(status_code=404, detail=f"Không tìm thấy URL: {location}")
    path.write_text(json.dumps(new_items, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"topic": topic, "removed": location, "remaining": len(new_items)}


# ─── Ingest ─────────────────────────────────────────────────────────────────
@router.post("/ingest")
async def trigger_ingest(req: IngestRequest):
    """Trigger crawl + chunk + embed. Truyền `topic` (lấy từ sources/<topic>.json),
    hoặc `urls` (list ad-hoc), hoặc cả 2.

    Lưu ý: `reset=true` qua HTTP bị TỪ CHỐI vì là thao tác destructive.
    Reset chỉ thực hiện qua CLI: `python ingest.py --reset`.
    """
    from crawler.fetch_data import crawl_sources
    from processor.chunker import process_documents
    from processor.embedder import embed_and_store

    if req.reset:
        raise HTTPException(
            status_code=403,
            detail=(
                "Reset KB qua HTTP đã bị tắt vì lý do an toàn. "
                "Dùng CLI: `python ingest.py --reset` từ server."
            ),
        )

    sources: list[dict[str, Any]] = []

    if req.topic:
        path = SOURCES_DIR / f"{req.topic}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Topic không tồn tại: {req.topic}")
        sources.extend(json.loads(path.read_text(encoding="utf-8")) or [])

    if req.urls:
        sources.extend([u.model_dump() for u in req.urls])

    if not sources:
        raise HTTPException(status_code=400, detail="Cần ít nhất `topic` hoặc `urls`.")

    documents = crawl_sources(sources)
    chunks = process_documents(documents)
    embed_and_store(chunks)

    return {
        "sources_count": len(sources),
        "documents_crawled": len(documents),
        "chunks_indexed": len(chunks),
        "reset": req.reset,
    }


# ─── Health Check ───────────────────────────────────────────────────────────
@router.post("/health-check")
async def run_health_check(body: dict = Body(default={})):
    """Chạy check_sources. Body: {"topic": "kubernetes" | null}"""
    import sys
    tools_path = Path(__file__).resolve().parent.parent / "tools"
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))

    import check_sources  # noqa
    summary = check_sources.check_sources(topic=body.get("topic"))
    from orchestrator import freshness_store

    checked_at = time.time()
    records = []
    for r in summary.results:
        mapped_status = "ERROR" if r.status == "UNKNOWN" else r.status
        error_message = r.detail if mapped_status == "ERROR" else ""
        records.append(
            {
                "url": r.location,
                "topic": r.topic,
                "status": mapped_status,
                "checked_at": checked_at,
                "http_status": r.http_status,
                "notes": r.detail,
                "error_message": error_message,
                "final_url": r.final_url,
            }
        )
    saved_count = freshness_store.save_many(records)
    logger.info(
        "Freshness snapshot updated",
        extra={
            "topic": body.get("topic") or "",
            "checked_urls": summary.total,
            "ok": summary.ok,
            "stale": summary.stale,
            "dead": summary.dead,
            "redirect": summary.redirect,
            "error": summary.unknown,
            "saved_records": saved_count,
        },
    )
    return {
        "total": summary.total,
        "ok": summary.ok,
        "stale": summary.stale,
        "dead": summary.dead,
        "redirect": summary.redirect,
        "unknown": summary.unknown,
        "results": [
            {
                "location": r.location,
                "topic": r.topic,
                "title": r.title,
                "status": r.status,
                "detail": r.detail,
                "final_url": r.final_url,
                "http_status": r.http_status,
                "diff_chars": r.diff_chars,
            }
            for r in summary.results
        ],
        "snapshot_saved": saved_count,
    }


@router.get("/freshness")
async def list_freshness(
    status: str | None = None,
    topic: str | None = None,
    limit: int = 200,
    offset: int = 0,
):
    from orchestrator import freshness_store

    allowed_status = {"OK", "STALE", "DEAD", "REDIRECT", "ERROR", "UNKNOWN"}
    if status and status.upper() not in allowed_status:
        raise HTTPException(status_code=400, detail="status không hợp lệ.")
    rows = freshness_store.list_latest(
        status=status.upper() if status else None,
        topic=topic,
        limit=limit,
        offset=offset,
    )
    return {
        "count": len(rows),
        "status": status.upper() if status else None,
        "topic": topic,
        "records": rows,
    }


@router.post("/freshness/recrawl")
async def batch_recrawl(req: BatchRecrawlRequest):
    urls = [u.strip() for u in req.urls if u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="Cần ít nhất 1 URL.")

    seen: set[str] = set()
    deduped_urls: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped_urls.append(url)

    sources = await list_sources()
    indexed: dict[str, dict[str, Any]] = {}
    for topic_entry in sources["topics"]:
        for item in topic_entry.get("items", []):
            location = (item or {}).get("location", "")
            if location and location not in indexed:
                indexed[location] = item

    selected = [indexed[url] for url in deduped_urls if url in indexed]
    missing = [url for url in deduped_urls if url not in indexed]
    if not selected:
        raise HTTPException(status_code=404, detail="Không tìm thấy URL nào trong sources.")

    from crawler.fetch_data import crawl_sources
    from processor.chunker import process_documents
    from processor.embedder import embed_and_store

    documents = crawl_sources(selected)
    chunks = process_documents(documents)
    embed_and_store(chunks)

    logger.info(
        "Freshness batch recrawl completed",
        extra={
            "requested_count": len(deduped_urls),
            "selected_count": len(selected),
            "missing_count": len(missing),
            "documents_crawled": len(documents),
            "chunks_indexed": len(chunks),
        },
    )

    return {
        "requested_count": len(deduped_urls),
        "selected_count": len(selected),
        "missing_count": len(missing),
        "missing_urls": missing,
        "documents_crawled": len(documents),
        "chunks_indexed": len(chunks),
    }


# ─── Stats ──────────────────────────────────────────────────────────────────
@router.get("/stats")
async def admin_stats():
    """Tổng quan số liệu KB + cache + sessions."""
    from observability import metrics_registry
    from orchestrator import store
    from orchestrator.cache import answer_cache
    from processor.embedder import collection

    # Chunks per topic
    try:
        all_data = collection.get(include=["metadatas"])
        metas = all_data.get("metadatas", []) or []
    except Exception:
        metas = []

    by_topic: dict[str, int] = {}
    by_session: dict[str, int] = {}
    for m in metas:
        topic = (m or {}).get("topic", "unknown")
        by_topic[topic] = by_topic.get(topic, 0) + 1
        sid = (m or {}).get("session_id", "")
        if sid:
            by_session[sid] = by_session.get(sid, 0) + 1

    # BM25 status
    bm25_ready = False
    bm25_chunks = 0
    try:
        from rag.hybrid import get_index
        idx = get_index()
        bm25_ready = idx.is_ready()
        bm25_chunks = len(idx.chunks)
    except Exception:
        pass

    # Cache + sessions
    cache_size = len(answer_cache._store)  # access internal OK cho admin
    sessions_count = len(store.list_sessions(limit=1000))

    return {
        "chunks": {
            "total": len(metas),
            "by_topic": dict(sorted(by_topic.items(), key=lambda x: -x[1])),
            "session_uploads": sum(by_session.values()),
        },
        "bm25": {
            "enabled_ready": bm25_ready,
            "indexed_chunks": bm25_chunks,
        },
        "cache": {
            "size": cache_size,
            "max_size": answer_cache._max_size,
            "ttl_seconds": answer_cache._ttl,
        },
        "sessions": {
            "count_with_messages": sessions_count,
        },
        "metrics": metrics_registry.snapshot(),
    }


# ─── Cache & BM25 management ────────────────────────────────────────────────
@router.post("/cache/clear")
async def clear_cache():
    from orchestrator.cache import answer_cache
    answer_cache.clear()
    return {"cleared": True}


@router.post("/bm25/rebuild")
async def rebuild_bm25():
    from rag.hybrid import rebuild_from_chroma
    idx = rebuild_from_chroma()
    return {"chunks_indexed": len(idx.chunks)}


# ─── Scheduler & Alerts ─────────────────────────────────────────────────────
@router.get("/scheduler/status")
async def get_scheduler_status():
    """Get scheduler current status: enabled, interval, last run, next run, alerts."""
    from orchestrator import scheduler, scheduler_state

    state = scheduler_state.read_state()
    return {
        "enabled": state.enabled,
        "interval_seconds": state.interval_seconds,
        "last_run_time": state.last_run_time,
        "next_run_time": state.next_run_time,
        "last_summary": state.last_summary,
        "alert_state": state.alert_state,
        "is_running": scheduler.is_running(),
    }


@router.post("/scheduler/config")
async def update_scheduler_config(body: dict = Body(...)):
    """Update scheduler enabled/interval.
    Body: {"enabled": bool, "interval_seconds": int}
    """
    from orchestrator import scheduler_state

    enabled = body.get("enabled")
    interval = body.get("interval_seconds")

    if enabled is None and interval is None:
        raise HTTPException(status_code=400, detail="Cần ít nhất 'enabled' hoặc 'interval_seconds'.")
    if interval is not None:
        try:
            interval = int(interval)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="interval_seconds phải là số nguyên.") from exc
        if interval < 60:
            raise HTTPException(status_code=400, detail="interval_seconds phải >= 60.")

    state = scheduler_state.update_state(
        enabled=enabled if enabled is not None else None,
        interval_seconds=interval if interval is not None else None,
    )

    logger.info(
        "Scheduler config updated",
        extra={
            "enabled": state.enabled,
            "interval_seconds": state.interval_seconds,
        },
    )
    return {
        "enabled": state.enabled,
        "interval_seconds": state.interval_seconds,
        "next_run_time": state.next_run_time,
    }


@router.post("/scheduler/run-now")
async def run_scheduler_now():
    """Manually trigger a health-check run immediately."""
    from orchestrator import scheduler

    try:
        summary = await scheduler.run_scheduler_cycle()
        logger.info(
            "Manual scheduler run completed",
            extra={
                "total": summary.get("total"),
                "ok": summary.get("ok"),
                "alert_state": summary.get("alert_state"),
            },
        )
        return {
            "total": summary.get("total"),
            "ok": summary.get("ok"),
            "stale": summary.get("stale"),
            "dead": summary.get("dead"),
            "redirect": summary.get("redirect"),
            "unknown": summary.get("unknown"),
            "snapshot_saved": summary.get("snapshot_saved"),
            "alert_state": summary.get("alert_state"),
            "alert_reason": summary.get("alert_reason"),
        }
    except Exception as exc:
        logger.error("Manual scheduler run failed", extra={"error": str(exc)}, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scheduler run failed: {exc}") from exc


# ─── Feedback ────────────────────────────────────────────────────────────────
class FeedbackRequest(BaseModel):
    session_id: str | None = None
    message_id: str | None = None
    question: str
    answer: str
    feedback_type: str  # 'up' | 'down'
    note: str | None = None


class ReviewRequest(BaseModel):
    review_note: str | None = None
    review_status: str = "reviewed"  # 'pending' | 'reviewed' | 'actioned'


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """Submit feedback (up/down) for a chatbot answer."""
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


@router.get("/feedback")
async def list_feedback(
    feedback_type: str | None = None,
    reviewed: bool | None = None,
    session_id: str | None = None,
    review_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List feedbacks with optional filters."""
    from orchestrator import feedback_store

    if feedback_type and feedback_type not in ("up", "down"):
        raise HTTPException(status_code=400, detail="feedback_type phải là 'up' hoặc 'down'.")
    if review_status and review_status not in ("pending", "reviewed", "actioned"):
        raise HTTPException(status_code=400, detail="review_status không hợp lệ.")

    items = feedback_store.list_feedbacks(
        feedback_type=feedback_type,
        reviewed=reviewed,
        session_id=session_id,
        review_status=review_status,
        limit=limit,
        offset=offset,
    )
    summary = feedback_store.count_summary()
    return {
        "count": len(items),
        "summary": summary,
        "items": items,
    }


@router.post("/feedback/{feedback_id}/review")
async def review_feedback(feedback_id: int, req: ReviewRequest):
    """Mark a feedback as reviewed with optional note."""
    from orchestrator import feedback_store

    existing = feedback_store.get_feedback(feedback_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Feedback không tồn tại.")

    if req.review_status not in ("pending", "reviewed", "actioned"):
        raise HTTPException(status_code=400, detail="review_status không hợp lệ.")

    updated = feedback_store.mark_reviewed(
        feedback_id,
        review_note=req.review_note,
        review_status=req.review_status,
    )
    return updated


@router.get("/feedback/summary")
async def feedback_summary():
    """Quick summary counts for feedback dashboard."""
    from orchestrator import feedback_store
    return feedback_store.count_summary()


# ─── Coverage Gaps ───────────────────────────────────────────────────────────
class CoverageGapReviewRequest(BaseModel):
    status: str = "reviewed"  # new | reviewed | actioned | ignored
    resolution: str | None = None  # add_source | recrawl | out_of_scope | ...
    review_note: str | None = None


@router.get("/coverage-gaps")
async def list_coverage_gaps(
    status: str | None = None,
    detected_topic: str | None = None,
    resolution: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List coverage gap candidates with optional filters."""
    from orchestrator import coverage_gap_store

    valid_statuses = {"new", "reviewed", "actioned", "ignored"}
    if status and status not in valid_statuses:
        raise HTTPException(status_code=400, detail="status không hợp lệ.")

    items = coverage_gap_store.list_gaps(
        status=status,
        detected_topic=detected_topic,
        resolution=resolution,
        limit=limit,
        offset=offset,
    )
    summary = coverage_gap_store.count_summary()
    return {
        "count": len(items),
        "summary": summary,
        "items": items,
    }


@router.post("/coverage-gaps/{gap_id}/review")
async def review_coverage_gap(gap_id: int, req: CoverageGapReviewRequest):
    """Mark a coverage gap as reviewed with optional resolution and note."""
    from orchestrator import coverage_gap_store

    existing = coverage_gap_store.get_gap(gap_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Coverage gap không tồn tại.")

    try:
        updated = coverage_gap_store.review_gap(
            gap_id,
            status=req.status,
            resolution=req.resolution,
            review_note=req.review_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return updated


@router.get("/coverage-gaps/summary")
async def coverage_gaps_summary():
    """Quick summary counts for coverage gaps dashboard."""
    from orchestrator import coverage_gap_store
    return coverage_gap_store.count_summary()
