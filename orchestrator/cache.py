"""LRU + TTL cache cho câu trả lời RAG.

Key dựa trên nội dung query (đã normalize). Không phân biệt user vì knowledge base chung.
Nếu sau này có data theo user, thêm user_id vào key.
"""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any

from config.settings import settings


@dataclass(slots=True)
class CachedAnswer:
    answer: str
    citations: list[dict[str, Any]]
    detected_topic: str | None
    retrieval_count: int
    expires_at: float = 0.0


class AnswerCache:
    def __init__(self, max_size: int, ttl_seconds: int) -> None:
        self._max_size = max(0, max_size)
        self._ttl = max(0, ttl_seconds)
        self._store: "OrderedDict[str, CachedAnswer]" = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def make_key(query: str) -> str:
        normalized = " ".join(query.lower().split())
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()

    def get(self, key: str) -> CachedAnswer | None:
        if self._max_size == 0:
            return None
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at < now:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return entry

    def set(self, key: str, value: CachedAnswer) -> None:
        if self._max_size == 0:
            return
        if not value.expires_at:
            value.expires_at = time.time() + self._ttl
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


answer_cache = AnswerCache(
    max_size=settings.answer_cache_size,
    ttl_seconds=settings.answer_cache_ttl,
)
