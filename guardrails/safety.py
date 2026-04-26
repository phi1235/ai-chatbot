from __future__ import annotations

import re
from dataclasses import dataclass, field

from config.settings import settings

JAILBREAK_PATTERNS = [
    r"ignore (all )?(previous|above) instructions",
    r"bypass (the )?(rules|policy|guardrails)",
    r"developer mode",
    r"system prompt",
    r"prompt injection",
]
TOXIC_PATTERNS = [
    r"\bkill yourself\b",
    r"\bđồ ngu\b",
]
PII_PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("phone", re.compile(r"(?<!\d)(?:\+?84|0)(?:\d[ .-]?){8,10}\d(?!\d)")),
]


@dataclass(slots=True)
class GuardrailResult:
    allowed: bool
    text: str
    flags: list[str] = field(default_factory=list)
    message: str = ""


def _find_policy_flags(text: str) -> list[str]:
    lowered = text.lower()
    flags: list[str] = []
    if any(re.search(pattern, lowered) for pattern in JAILBREAK_PATTERNS):
        flags.append("prompt_injection")
    if any(re.search(pattern, lowered) for pattern in TOXIC_PATTERNS):
        flags.append("toxic_content")
    if len(text) > settings.max_message_length:
        flags.append("message_too_long")
    return flags


def _redact_pii(text: str) -> tuple[str, list[str]]:
    redacted = text
    flags: list[str] = []
    if not settings.pii_redaction_enabled:
        return redacted, flags
    for label, pattern in PII_PATTERNS:
        if pattern.search(redacted):
            flags.append(f"pii_{label}")
            redacted = pattern.sub(f"[{label.upper()}_REDACTED]", redacted)
    return redacted, flags


def apply_input_guardrails(text: str) -> GuardrailResult:
    normalized = text.strip()
    flags = _find_policy_flags(normalized)
    redacted, pii_flags = _redact_pii(normalized)
    flags.extend(pii_flags)
    blocking_flags = {"prompt_injection", "toxic_content", "message_too_long"}
    if blocking_flags & set(flags):
        return GuardrailResult(
            allowed=False,
            text=redacted,
            flags=flags,
            message="Yêu cầu bị chặn bởi guardrails đầu vào. Hãy diễn đạt lại câu hỏi an toàn và cụ thể hơn.",
        )
    return GuardrailResult(allowed=True, text=redacted, flags=flags)


def apply_output_guardrails(text: str) -> GuardrailResult:
    flags = _find_policy_flags(text)
    redacted, pii_flags = _redact_pii(text)
    flags.extend(pii_flags)
    if "toxic_content" in flags:
        return GuardrailResult(
            allowed=False,
            text=redacted,
            flags=flags,
            message="Câu trả lời đã bị chặn do không đạt chính sách an toàn đầu ra.",
        )
    return GuardrailResult(allowed=True, text=redacted, flags=flags)
