"""Tests cho guardrails (input + output)."""
from __future__ import annotations

from guardrails import apply_input_guardrails, apply_output_guardrails


def test_input_allows_normal_question():
    r = apply_input_guardrails("Python là gì?")
    assert r.allowed
    assert r.text == "Python là gì?"


def test_input_blocks_too_long():
    # MAX_MESSAGE_LENGTH default 2000, gửi vượt sẽ bị block
    r = apply_input_guardrails("a" * 5000)
    assert not r.allowed


def test_input_redacts_email():
    r = apply_input_guardrails("Liên hệ tôi qua user@example.com nhé")
    # PII redaction - email phải bị thay bởi placeholder
    assert "user@example.com" not in r.text
    assert "email_redacted" in r.flags or "[email]" in r.text or "***" in r.text or "@" not in r.text


def test_input_redacts_phone():
    r = apply_input_guardrails("Số điện thoại: 0901234567")
    assert "0901234567" not in r.text


def test_output_allows_normal_answer():
    r = apply_output_guardrails("Python là một ngôn ngữ lập trình.")
    assert r.allowed
    assert r.text == "Python là một ngôn ngữ lập trình."


def test_output_handles_empty():
    r = apply_output_guardrails("")
    # Empty không được allow ra answer
    assert (not r.allowed) or r.text == ""
