from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from crawler.fetch_data import crawl_sources
from processor.chunker import process_documents
from processor.embedder import clear_collection, embed_and_store

SOURCES_DIR = Path("sources")


def _load_source_file(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"File nguồn không hợp lệ: {path}")
    return payload


def load_sources(topic: str | None = None, source_file: str | None = None) -> list[dict[str, Any]]:
    if source_file:
        path = Path(source_file)
        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy file nguồn: {path}")
        return _load_source_file(path)

    if topic:
        path = SOURCES_DIR / f"{topic}.json"
        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy topic '{topic}' trong {SOURCES_DIR}/")
        return _load_source_file(path)

    sources: list[dict[str, Any]] = []
    for path in sorted(SOURCES_DIR.glob("*.json")):
        sources.extend(_load_source_file(path))
    return sources


def ingest(topic: str | None = None, source_file: str | None = None, reset: bool = False) -> None:
    sources = load_sources(topic=topic, source_file=source_file)
    if not sources:
        print("Không có nguồn nào để ingest.")
        return

    if reset:
        clear_collection()

    print(f"Đang crawl {len(sources)} nguồn...")
    documents = crawl_sources(sources)
    print(f"Đã clean {len(documents)} documents")

    chunks = process_documents(documents)
    print(f"Đã tạo {len(chunks)} chunks")

    embed_and_store(chunks)
    print("Ingest hoàn tất")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest dữ liệu theo topic: crawl -> clean -> chunk -> embed"
    )
    parser.add_argument(
        "--topic",
        help="Tên topic tương ứng file sources/<topic>.json",
    )
    parser.add_argument(
        "--source-file",
        help="Đường dẫn file JSON nguồn tùy chỉnh",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Xóa knowledge base hiện tại trước khi ingest",
    )
    args = parser.parse_args()
    ingest(topic=args.topic, source_file=args.source_file, reset=args.reset)


if __name__ == "__main__":
    main()
