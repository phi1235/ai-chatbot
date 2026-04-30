from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from observability import get_logger

logger = get_logger(__name__)
SOURCES_DIR = Path("sources")


def load_source_items(topic: str) -> list[dict[str, Any]]:
    path = SOURCES_DIR / f"{topic}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Topic không tồn tại: {topic}")
    try:
        items = json.loads(path.read_text(encoding="utf-8")) or []
    except json.JSONDecodeError:
        items = []
    if not isinstance(items, list):
        items = []
    return items


def write_source_items(topic: str, items: list[dict[str, Any]]) -> None:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCES_DIR / f"{topic}.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def add_source_item(topic: str, location: str, title: str = "") -> dict[str, Any]:
    topic = topic.strip()
    location = location.strip()
    if not location:
        raise HTTPException(status_code=400, detail="action_payload.url là bắt buộc cho add_source.")
    if not topic:
        raise HTTPException(status_code=400, detail="action_payload.topic là bắt buộc cho add_source.")

    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCES_DIR / f"{topic}.json"
    items: list[dict[str, Any]] = []
    if path.exists():
        try:
            items = json.loads(path.read_text(encoding="utf-8")) or []
        except json.JSONDecodeError:
            items = []

    new_item = {
        "location": location,
        "topic": topic,
        "title": title.strip() or location,
        "source": "website",
    }
    if any(it.get("location") == location for it in items):
        raise HTTPException(status_code=409, detail="URL đã tồn tại trong topic này.")

    items.append(new_item)
    write_source_items(topic, items)
    return {"added": new_item, "topic": topic, "total": len(items)}


async def resolve_recrawl_sources(
    topic: str | None,
    urls: list[str] | None,
    *,
    list_sources_fn,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    recrawl_topic = (topic or "").strip()
    recrawl_urls = [u.strip() for u in (urls or []) if u.strip()]

    if not recrawl_topic and not recrawl_urls:
        raise HTTPException(
            status_code=400,
            detail="action_payload cần có 'topic' hoặc 'urls' cho recrawl.",
        )

    if recrawl_topic:
        sources.extend(load_source_items(recrawl_topic))

    if recrawl_urls:
        all_sources = await list_sources_fn()
        indexed: dict[str, dict[str, Any]] = {}
        for topic_entry in all_sources["topics"]:
            for item in topic_entry.get("items", []):
                loc = (item or {}).get("location", "")
                if loc and loc not in indexed:
                    indexed[loc] = item
        for u in recrawl_urls:
            if u in indexed:
                sources.append(indexed[u])

    if not sources:
        raise HTTPException(status_code=400, detail="Không tìm thấy source nào để recrawl.")
    return sources


def execute_recrawl(sources: list[dict[str, Any]]) -> dict[str, int]:
    from crawler.fetch_data import crawl_sources
    from processor.chunker import process_documents
    from processor.embedder import embed_and_store

    documents = crawl_sources(sources)
    chunks = process_documents(documents)
    embed_and_store(chunks)
    return {
        "sources_count": len(sources),
        "documents_crawled": len(documents),
        "chunks_indexed": len(chunks),
    }


__all__ = [
    "SOURCES_DIR",
    "add_source_item",
    "execute_recrawl",
    "load_source_items",
    "logger",
    "resolve_recrawl_sources",
    "time",
    "write_source_items",
]
