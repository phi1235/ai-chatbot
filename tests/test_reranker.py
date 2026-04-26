"""Tests cho rag.reranker - mock CrossEncoder để khỏi load model thật (~280MB)."""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

import rag.reranker as reranker


@pytest.fixture(autouse=True)
def _enable_reranker(monkeypatch):
    """Enable reranker qua env + reload modules để Settings frozen pick up."""
    monkeypatch.setenv("RERANKER_ENABLED", "true")
    import config.settings as settings_mod
    importlib.reload(settings_mod)
    importlib.reload(reranker)
    yield


@pytest.fixture
def disabled(monkeypatch):
    """Disable reranker - dùng riêng cho test cần off state."""
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    import config.settings as settings_mod
    importlib.reload(settings_mod)
    importlib.reload(reranker)
    return reranker


@pytest.fixture
def fake_chunks():
    return [
        {"content": "Pod là đơn vị nhỏ nhất", "metadata": {"url": "u1"}, "score": 0.7},
        {"content": "Deployment quản lý ReplicaSet", "metadata": {"url": "u2"}, "score": 0.6},
        {"content": "Ronaldo là cầu thủ bóng đá", "metadata": {"url": "u3"}, "score": 0.5},
    ]


def _mock_model_with_scores(scores: list[float]) -> MagicMock:
    """Mock CrossEncoder.predict trả về scores cố định."""
    model = MagicMock()
    model.predict.return_value = scores
    return model


def test_rerank_reorders_by_score(monkeypatch, fake_chunks):
    """Mock model: chunk index 1 điểm cao nhất → phải lên top 1."""
    monkeypatch.setattr(reranker, "_model", _mock_model_with_scores([0.3, 0.95, 0.1]))
    out = reranker.rerank("Deployment là gì?", fake_chunks, top_k=2)
    assert len(out) == 2
    assert out[0]["metadata"]["url"] == "u2"  # cao nhất
    assert out[0]["rerank_score"] == pytest.approx(0.95)
    assert out[1]["metadata"]["url"] == "u1"


def test_rerank_truncates_to_top_k(monkeypatch, fake_chunks):
    monkeypatch.setattr(reranker, "_model", _mock_model_with_scores([0.5, 0.5, 0.5]))
    out = reranker.rerank("q", fake_chunks, top_k=1)
    assert len(out) == 1


def test_rerank_returns_empty_for_empty_input():
    assert reranker.rerank("q", [], top_k=3) == []


def test_rerank_disabled_returns_first_top_k(disabled, fake_chunks, monkeypatch):
    """Khi RERANKER_ENABLED=false, trả về thứ tự gốc, không gọi model."""
    fake_load = MagicMock()
    monkeypatch.setattr(disabled, "_get_model", fake_load)
    out = disabled.rerank("q", fake_chunks, top_k=2)
    assert len(out) == 2
    assert out[0]["metadata"]["url"] == "u1"
    assert out[1]["metadata"]["url"] == "u2"
    fake_load.assert_not_called()


def test_rerank_falls_back_when_model_load_fails(monkeypatch, fake_chunks):
    """Lỗi load model không fatal - fallback về thứ tự gốc."""
    def boom():
        raise RuntimeError("Mạng yếu")
    monkeypatch.setattr(reranker, "_get_model", boom)
    out = reranker.rerank("q", fake_chunks, top_k=2)
    assert len(out) == 2
    # Giữ thứ tự gốc
    assert out[0]["metadata"]["url"] == "u1"


def test_rerank_falls_back_when_predict_fails(monkeypatch, fake_chunks):
    bad_model = MagicMock()
    bad_model.predict.side_effect = RuntimeError("OOM")
    monkeypatch.setattr(reranker, "_model", bad_model)
    out = reranker.rerank("q", fake_chunks, top_k=2)
    assert len(out) == 2
    assert out[0]["metadata"]["url"] == "u1"


def test_rerank_attaches_score_field(monkeypatch, fake_chunks):
    monkeypatch.setattr(reranker, "_model", _mock_model_with_scores([0.3, 0.9, 0.6]))
    out = reranker.rerank("q", fake_chunks, top_k=3)
    for c in out:
        assert "rerank_score" in c
        assert isinstance(c["rerank_score"], float)


def test_rerank_does_not_mutate_input(monkeypatch, fake_chunks):
    monkeypatch.setattr(reranker, "_model", _mock_model_with_scores([0.1, 0.5, 0.9]))
    original_first = dict(fake_chunks[0])
    reranker.rerank("q", fake_chunks, top_k=3)
    # Input chunks gốc không có rerank_score
    assert "rerank_score" not in fake_chunks[0]
    assert fake_chunks[0] == original_first
