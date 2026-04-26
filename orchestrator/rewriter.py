"""Query rewriter: chuyển câu hỏi follow-up thành câu hỏi độc lập có đủ ngữ cảnh.

Ví dụ:
    History: User hỏi về Pod, Bot trả lời.
    New query: "Còn Deployment thì sao?"
    -> Rewrite: "Trong Kubernetes, Deployment là gì và khác Pod ra sao?"

Skip nếu:
- History rỗng (câu đầu)
- Câu hỏi đã đủ độc lập (không có đại từ tham chiếu, đủ noun)

Caller chịu trách nhiệm gọi rewrite trước khi retrieve.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from config.settings import settings
from rag.generator import _get_client

REWRITE_SYSTEM = (
    "Bạn là module viết lại câu hỏi cho hệ thống RAG. Dựa trên lịch sử hội thoại và "
    "câu hỏi mới của người dùng, hãy viết lại câu hỏi đó thành một câu hỏi độc lập "
    "(standalone question) chứa đủ ngữ cảnh để hiểu mà không cần đọc lịch sử. "
    "Giữ nguyên ngôn ngữ gốc của người dùng. "
    "Nếu câu hỏi đã đủ độc lập, trả lời lại nguyên văn câu hỏi đó. "
    "CHỈ trả lời câu hỏi đã viết lại, không thêm giải thích, không có dấu nháy, "
    "không thêm tiền tố như 'Câu hỏi:' hay 'Standalone:'."
)

# Đại từ tham chiếu / cụm phụ thuộc ngữ cảnh - dấu hiệu cần rewrite
FOLLOWUP_HINTS = (
    "nó", "đó", "này", "đấy", "vậy", "thế", "kia",
    "còn", "thì sao", "thì như nào", "thì sao nhỉ",
    "cái đó", "cái này", "cái kia", "cái ấy",
    "tiếp theo", "tiếp tục", "kế tiếp",
    "more", "what about", "and ", "also",
    "tại sao", "sao lại", "vì sao",  # có thể đang hỏi tiếp về thứ vừa đề cập
)


def _looks_like_followup(query: str) -> bool:
    """Heuristic nhanh: câu hỏi có vẻ phụ thuộc ngữ cảnh trước đó?"""
    lowered = query.lower().strip()
    # Câu rất ngắn (< 5 từ) có khả năng cao là follow-up
    if len(re.findall(r"\S+", lowered)) < 5:
        return True
    return any(hint in lowered for hint in FOLLOWUP_HINTS)


def _format_history(history: Iterable[dict[str, str]], max_turns: int = 6) -> str:
    """Format history thành string ngắn để đưa vào prompt rewrite."""
    items = list(history)[-max_turns:]
    lines: list[str] = []
    for turn in items:
        role = "User" if turn.get("role") == "user" else "Assistant"
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        # Cắt ngắn để tiết kiệm token
        if len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def rewrite_question(query: str, history: list[dict[str, str]]) -> tuple[str, bool]:
    """
    Trả về (standalone_query, did_rewrite).

    Skip rewrite (trả về query gốc) khi:
    - History rỗng
    - Heuristic cho thấy câu hỏi đã độc lập (đủ dài và không có pronoun)
    """
    if not history or not _looks_like_followup(query):
        return query, False

    history_text = _format_history(history)
    if not history_text:
        return query, False

    user_content = (
        f"Lịch sử hội thoại:\n{history_text}\n\n"
        f"Câu hỏi follow-up: {query}\n\n"
        f"Câu hỏi độc lập:"
    )

    try:
        response = _get_client().chat.completions.create(
            model=settings.openrouter_model,
            messages=[
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            max_tokens=120,
            temperature=0.0,
        )
    except Exception:
        # Lỗi rewrite không fatal - fallback dùng query gốc
        return query, False

    if not response.choices:
        return query, False
    rewritten = (response.choices[0].message.content or "").strip()
    # Bỏ dấu nháy nếu LLM lỡ thêm
    rewritten = rewritten.strip('"\'`')
    if not rewritten or len(rewritten) > 500:
        return query, False
    return rewritten, True
