from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from api.admin.routes.sources import list_sources
from api.admin_shared import logger, time

router = APIRouter()


@router.post("/health-check")
async def run_health_check(body: dict = Body(default={})):
    """Chạy check_sources. Body: {"topic": "kubernetes" | null}"""
    tools_path = Path(__file__).resolve().parents[3] / "tools"
    module_path = tools_path / "check_sources.py"
    if not module_path.exists():
        raise HTTPException(status_code=500, detail="Missing tools/check_sources.py")

    check_sources = sys.modules.get("check_sources")
    if check_sources is None:
        spec = importlib.util.spec_from_file_location("check_sources", module_path)
        if spec is None or spec.loader is None:
            raise HTTPException(status_code=500, detail="Failed to load check_sources module")
        check_sources = importlib.util.module_from_spec(spec)
        sys.modules["check_sources"] = check_sources
        spec.loader.exec_module(check_sources)

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
async def batch_recrawl(req: dict):
    urls = [u.strip() for u in req.get("urls", []) if u.strip()]
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


@router.get("/stats")
async def admin_stats():
    """Tổng quan số liệu KB + cache + sessions."""
    from observability import metrics_registry
    from orchestrator import store
    from orchestrator.cache import answer_cache
    from processor.embedder import collection

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

    bm25_ready = False
    bm25_chunks = 0
    try:
        from rag.hybrid import get_index
        idx = get_index()
        bm25_ready = idx.is_ready()
        bm25_chunks = len(idx.chunks)
    except Exception:
        pass

    cache_size = len(answer_cache._store)
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


@router.get("/scheduler/status")
async def get_scheduler_status():
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
