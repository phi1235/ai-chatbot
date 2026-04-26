"""Shared pytest fixtures.

Tách config để mỗi test khỏi đụng filesystem thật của user (chroma_store, sqlite).
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_storage(monkeypatch, tmp_path: Path):
    """Mỗi test có working dir riêng cho chroma + sqlite, tránh ảnh hưởng prod data."""
    storage_dir = tmp_path / "db"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHROMA_PATH", str(storage_dir / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION", "test_collection")
    monkeypatch.setenv("ANSWER_CACHE_TTL", "60")
    monkeypatch.setenv("ANSWER_CACHE_SIZE", "16")
    monkeypatch.setenv("EMBEDDING_CACHE_SIZE", "8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    yield


@pytest.fixture
def fake_chunks() -> list[dict]:
    return [
        {
            "content": "Kubernetes Pod là đơn vị nhỏ nhất, gói container.",
            "metadata": {"title": "K8s Pod", "url": "u1", "topic": "kubernetes"},
            "score": 0.9,
            "distance": 0.1,
        },
        {
            "content": "Deployment quản lý ReplicaSet và rolling update.",
            "metadata": {"title": "K8s Deployment", "url": "u2", "topic": "kubernetes"},
            "score": 0.8,
            "distance": 0.2,
        },
    ]
