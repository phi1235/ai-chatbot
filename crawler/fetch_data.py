from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from processor.cleaner import clean_document

DATA_RAW_DIR = Path("data/raw")
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
}


@dataclass(slots=True)
class SourceSpec:
    location: str
    topic: str
    source: str = "website"
    title: str | None = None
    updated_at: str | None = None


def _is_url(location: str) -> bool:
    return location.startswith("http://") or location.startswith("https://")


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    compact = "-".join(part for part in cleaned.split("-") if part)
    return compact or "document"


def _build_doc_id(location: str, topic: str) -> str:
    digest = hashlib.sha1(f"{location}|{topic}".encode()).hexdigest()[:10]
    return f"{_slugify(topic)}-{digest}"


def _read_source(location: str, timeout: float = 20.0) -> tuple[str, str]:
    if _is_url(location):
        response = httpx.get(
            location,
            timeout=timeout,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        return response.text, content_type

    path = Path(location)
    return path.read_text(encoding="utf-8"), path.suffix.lower()


def _raw_payload(doc_id: str, spec: SourceSpec, raw_content: str) -> dict[str, Any]:
    return {
        "id": doc_id,
        "title": spec.title or spec.location,
        "url": spec.location if _is_url(spec.location) else "",
        "path": spec.location if not _is_url(spec.location) else "",
        "content": raw_content,
        "source": spec.source,
        "updated_at": spec.updated_at or datetime.now().date().isoformat(),
        "topic": spec.topic,
    }


def crawl_sources(sources: list[SourceSpec | dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Nạp dữ liệu từ URL hoặc file local, lưu raw JSON và trả về document đã clean.
    """
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    documents: list[dict[str, Any]] = []

    for item in sources:
        spec = item if isinstance(item, SourceSpec) else SourceSpec(**item)
        doc_id = _build_doc_id(spec.location, spec.topic)
        try:
            raw_content, content_type = _read_source(spec.location)
            raw_doc = _raw_payload(doc_id, spec, raw_content)

            # Lưu raw dạng .json.gz để tiết kiệm dung lượng (~80% so với .json)
            # Nếu đã có file .json cũ, vẫn dùng được - script migrate sẽ xử lý
            raw_path = DATA_RAW_DIR / f"{doc_id}.json.gz"
            with gzip.open(raw_path, "wt", encoding="utf-8") as f:
                json.dump(raw_doc, f, ensure_ascii=False)

            cleaned = clean_document(raw_doc, content_type=content_type)
            if cleaned:
                documents.append(cleaned)
                print(f"[OK] {spec.location}")
            else:
                print(f"[SKIP] Noi dung qua ngan hoac khong hop le: {spec.location}")
        except Exception as exc:
            print(f"[ERROR] Khong crawl duoc {spec.location}: {exc}")

    return documents


if __name__ == "__main__":
    sample_sources = [
        {
            "location": "README.md",
            "topic": "project",
            "source": "local_file",
            "title": "AI Chatbot README",
        }
    ]
    results = crawl_sources(sample_sources)
    print(f"Processed {len(results)} documents")
