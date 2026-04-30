from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from api.admin_shared import SOURCES_DIR, add_source_item

router = APIRouter()


class SourceItem(BaseModel):
    location: str
    topic: str
    title: str = ""
    source: str = "website"


class IngestRequest(BaseModel):
    topic: str | None = None
    urls: list[SourceItem] | None = None
    reset: bool = False


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
    return add_source_item(topic=topic, location=item.location, title=item.title)


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
