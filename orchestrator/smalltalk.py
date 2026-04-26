from __future__ import annotations

import re

GREETINGS = {
    "hi",
    "hello",
    "hey",
    "alo",
    "chao",
    "chào",
    "xin chao",
    "xin chào",
}
THANKS = {
    "thanks",
    "thank you",
    "cam on",
    "cảm ơn",
    "ok thanks",
}
GOODBYES = {
    "bye",
    "goodbye",
    "tam biet",
    "tạm biệt",
}


def _normalize(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"[!?.。]+", "", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def get_smalltalk_answer(text: str) -> str | None:
    normalized = _normalize(text)
    if normalized in GREETINGS:
        return "Chào bạn! Mình là chatbot RAG của repo này. Bạn có thể hỏi mình về nội dung đã nạp trong knowledge base, ví dụ Python, Machine Learning, chính sách hoàn tiền, Docker hoặc Spring Boot."
    if normalized in THANKS:
        return "Không có gì. Bạn cứ gửi tiếp câu hỏi hoặc tài liệu muốn kiểm thử nhé."
    if normalized in GOODBYES:
        return "Tạm biệt bạn. Khi cần kiểm thử chatbot hoặc nạp thêm dữ liệu, cứ quay lại nhé."
    if len(normalized.split()) <= 2 and normalized in {"ok", "oke", "uh", "ừ", "ừm"}:
        return "Ok bạn. Bạn muốn hỏi nội dung nào trong knowledge base?"
    return None
