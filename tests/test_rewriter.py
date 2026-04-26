"""Tests cho orchestrator.rewriter - không gọi LLM thật, chỉ test heuristic + format."""
from __future__ import annotations

from orchestrator.rewriter import (
    _format_history,
    _looks_like_followup,
    rewrite_question,
)


def test_followup_detects_short_question():
    assert _looks_like_followup("Còn cái này?")


def test_followup_detects_pronoun_reference():
    assert _looks_like_followup("Cái đó có ưu điểm gì so với Spring Boot không nhỉ?")
    assert _looks_like_followup("Tại sao lại như vậy?")


def test_followup_skips_standalone_question():
    # Câu đủ dài, không chứa pronoun/hint phụ thuộc context
    long_q = "Trong Kubernetes, Deployment khác Pod ở vòng đời và mục đích sử dụng"
    assert not _looks_like_followup(long_q)


def test_followup_detects_english_hints():
    assert _looks_like_followup("what about Deployment?")


def test_format_history_truncates_long_content():
    history = [
        {"role": "user", "content": "Q?"},
        {"role": "assistant", "content": "A" * 500},
    ]
    out = _format_history(history)
    assert "User: Q?" in out
    assert "Assistant: " in out
    # Long content phải bị cắt
    assert "..." in out


def test_format_history_skips_empty():
    history = [
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "answer"},
    ]
    out = _format_history(history)
    assert "answer" in out
    assert "User:" not in out


def test_format_history_limit_max_turns():
    history = [{"role": "user", "content": f"q{i}"} for i in range(20)]
    out = _format_history(history, max_turns=3)
    # Chỉ giữ 3 turn cuối
    assert out.count("\n") + 1 <= 3
    assert "q19" in out
    assert "q0" not in out


def test_rewrite_skip_when_no_history():
    """Empty history -> skip rewrite, trả lại query gốc."""
    q, did = rewrite_question("Còn cái đó?", [])
    assert q == "Còn cái đó?"
    assert did is False


def test_rewrite_skip_when_standalone_question():
    """Câu đã đủ độc lập -> skip rewrite kể cả có history."""
    history = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]
    long_q = "Trong PostgreSQL, foreign key cascade hoạt động ra sao và có ảnh hưởng performance gì?"
    q, did = rewrite_question(long_q, history)
    assert q == long_q
    assert did is False
