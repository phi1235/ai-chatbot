"""Tests cho orchestrator.cache - LRU + TTL answer cache."""
from __future__ import annotations

import time

from orchestrator.cache import AnswerCache, CachedAnswer


def _make(answer: str = "ans") -> CachedAnswer:
    return CachedAnswer(
        answer=answer,
        citations=[],
        detected_topic=None,
        retrieval_count=0,
    )


def test_set_and_get():
    c = AnswerCache(max_size=4, ttl_seconds=10)
    c.set("k1", _make("v1"))
    got = c.get("k1")
    assert got is not None and got.answer == "v1"


def test_miss_returns_none():
    c = AnswerCache(max_size=4, ttl_seconds=10)
    assert c.get("missing") is None


def test_lru_evicts_oldest():
    c = AnswerCache(max_size=2, ttl_seconds=60)
    c.set("a", _make("A"))
    c.set("b", _make("B"))
    c.set("c", _make("C"))  # 'a' phải bị evict
    assert c.get("a") is None
    assert c.get("b") is not None
    assert c.get("c") is not None


def test_lru_touch_on_get():
    c = AnswerCache(max_size=2, ttl_seconds=60)
    c.set("a", _make("A"))
    c.set("b", _make("B"))
    # Access 'a' để move to end
    assert c.get("a") is not None
    c.set("c", _make("C"))  # 'b' phải bị evict, không phải 'a'
    assert c.get("a") is not None
    assert c.get("b") is None
    assert c.get("c") is not None


def test_ttl_expiry():
    c = AnswerCache(max_size=4, ttl_seconds=0)
    c.set("k", _make())
    time.sleep(0.01)
    assert c.get("k") is None


def test_zero_size_disabled():
    c = AnswerCache(max_size=0, ttl_seconds=60)
    c.set("k", _make())
    assert c.get("k") is None


def test_make_key_normalizes_whitespace():
    k1 = AnswerCache.make_key("  Python   là gì?  ")
    k2 = AnswerCache.make_key("python là gì?")
    assert k1 == k2


def test_clear():
    c = AnswerCache(max_size=4, ttl_seconds=60)
    c.set("a", _make())
    c.set("b", _make())
    c.clear()
    assert c.get("a") is None
    assert c.get("b") is None
