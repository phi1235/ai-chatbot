from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DATA_CLEAN_DIR = Path("data/clean")
MIN_CONTENT_LENGTH = 120
MENU_HINTS = {
    "menu",
    "footer",
    "header",
    "navigation",
    "sidebar",
    "privacy",
    "cookie",
    "copyright",
}
NOISE_PATTERNS = [
    r"^accept all",
    r"^all rights reserved",
    r"^skip to",
    r"^sign in$",
    r"^log in$",
    r"^subscribe$",
    r"^share$",
    r"^follow us",
    r"^cookie",
    r"^privacy policy$",
    r"^terms of use$",
    r"^advertisement$",
]


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)</(div|section|article|li|ul|ol|table|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return text


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _drop_duplicate_lines(text: str) -> str:
    seen: set[str] = set()
    kept: list[str] = []

    for line in text.splitlines():
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        lower = normalized.lower()
        if lower in seen:
            continue
        if len(normalized) < 80 and any(hint in lower for hint in MENU_HINTS):
            continue
        if any(re.search(pattern, lower) for pattern in NOISE_PATTERNS):
            continue
        alpha_count = sum(char.isalpha() for char in normalized)
        if alpha_count and alpha_count / max(len(normalized), 1) < 0.45:
            continue
        if len(normalized.split()) < 3 and len(normalized) < 24:
            continue
        seen.add(lower)
        kept.append(normalized)

    return "\n".join(kept).strip()


def _extract_title(doc: dict[str, Any], text: str) -> str:
    existing = (doc.get("title") or "").strip()
    if existing and existing != doc.get("url"):
        return existing

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:160] if first_line else existing or doc["id"]


def clean_document(doc: dict[str, Any], content_type: str | None = None) -> dict[str, Any] | None:
    """
    Làm sạch dữ liệu crawl và lưu vào data/clean.
    """
    raw_content = doc.get("content", "")
    if not isinstance(raw_content, str) or not raw_content.strip():
        return None

    looks_like_html = bool(content_type and "html" in content_type.lower()) or "<html" in raw_content.lower()
    cleaned_text = _strip_html(raw_content) if looks_like_html else raw_content
    cleaned_text = _normalize_whitespace(cleaned_text)
    cleaned_text = _drop_duplicate_lines(cleaned_text)

    if len(cleaned_text) < MIN_CONTENT_LENGTH:
        return None

    cleaned_doc = {
        "id": doc["id"],
        "title": _extract_title(doc, cleaned_text),
        "url": doc.get("url", ""),
        "content": cleaned_text,
        "source": doc.get("source", "website"),
        "updated_at": doc.get("updated_at"),
        "topic": doc.get("topic", "general"),
    }

    DATA_CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    clean_path = DATA_CLEAN_DIR / f"{doc['id']}.json"
    clean_path.write_text(
        json.dumps(cleaned_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cleaned_doc


if __name__ == "__main__":
    sample = {
        "id": "doc-001",
        "title": "Refund policy",
        "url": "https://example.com/refund",
        "content": "<html><body><header>Menu</header><h1>Refund Policy</h1><p>Customers can request a refund within 30 days.</p></body></html>",
        "source": "website",
        "updated_at": "2026-04-22",
        "topic": "policy",
    }
    result = clean_document(sample, content_type="text/html")
    print(result["content"] if result else "Document dropped")
