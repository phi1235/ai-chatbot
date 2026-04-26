from __future__ import annotations

import re
from typing import Any

MAX_CHUNK_LENGTH = 900
MIN_CHUNK_LENGTH = 180


def _looks_like_heading(block: str) -> bool:
    stripped = block.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    if len(stripped) <= 80 and stripped == stripped.title():
        return True
    if len(stripped) <= 80 and stripped.endswith(":"):
        return True
    return False


def _split_blocks(text: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]


def _split_large_block(block: str, max_length: int) -> list[str]:
    if len(block) <= max_length:
        return [block]

    sentences = re.split(r"(?<=[.!?])\s+", block)
    groups: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_length:
            current = candidate
            continue
        if current:
            groups.append(current)
        current = sentence

    if current:
        groups.append(current)
    return groups


def chunk_document(
    doc: dict[str, Any],
    max_length: int = MAX_CHUNK_LENGTH,
    min_length: int = MIN_CHUNK_LENGTH,
) -> list[dict[str, Any]]:
    """
    Chia document theo heading, section, paragraph group rồi mới giới hạn độ dài.
    """
    blocks = _split_blocks(doc["content"])
    chunks: list[dict[str, Any]] = []
    current_heading = doc["title"]
    current_parts: list[str] = []

    def flush() -> None:
        combined = "\n\n".join(part for part in current_parts if part.strip()).strip()
        if not combined:
            return
        if chunks and len(combined) < min_length:
            chunks[-1]["content"] = f"{chunks[-1]['content']}\n\n{combined}".strip()
            return

        chunk_index = len(chunks) + 1
        chunks.append(
            {
                "chunk_id": f"{doc['id']}-chunk-{chunk_index:02d}",
                "doc_id": doc["id"],
                "title": doc["title"],
                "section": current_heading,
                "content": combined,
                "topic": doc.get("topic", "general"),
                "url": doc.get("url", ""),
                "source": doc.get("source", "website"),
                "updated_at": doc.get("updated_at"),
            }
        )

    for block in blocks:
        if _looks_like_heading(block):
            if current_parts:
                flush()
                current_parts = []
            current_heading = block.lstrip("#").strip(": ").strip()
            continue

        for piece in _split_large_block(block, max_length):
            candidate = "\n\n".join(current_parts + [piece]).strip()
            if current_parts and len(candidate) > max_length:
                flush()
                current_parts = [piece]
            else:
                current_parts.append(piece)

    if current_parts:
        flush()

    return chunks


def process_documents(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_chunks: list[dict[str, Any]] = []
    for doc in docs:
        all_chunks.extend(chunk_document(doc))
    return all_chunks


if __name__ == "__main__":
    sample_doc = {
        "id": "doc-001",
        "title": "Refund policy",
        "topic": "policy",
        "url": "https://example.com/refund",
        "content": """
Refund Policy

Eligibility

Customers can request a refund within 30 days of purchase. The request must include the order number and reason.

Exceptions

Digital goods are not refundable after activation. Trial plans are excluded from refund coverage.
""".strip(),
    }
    chunks = process_documents([sample_doc])
    print(f"Created {len(chunks)} chunks from document")
    print(chunks[0]["content"])
