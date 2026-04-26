import os
import re
import unicodedata
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from config.settings import settings

STOPWORDS = {
    "la", "co", "de", "khong", "va", "the", "nao", "mot", "nhung", "voi",
    "cua", "cho", "ve", "do", "duoc", "hay", "toi", "ban", "anh",
}
GARBAGE_PATTERNS = [
    r"the emerging market dynamics",
    r"cau hoi:\s*\d",
    r"tra loi ngan",
    r"phan chua thong tin",
    r"lich su tu choi",
    r"theo yeu cau",
    r"khong dung bullet",
    r"m[uú]d l[ụu]c h[iì]nh",
    # Model trả lại system prompt rules
    r"khuy[eế]n ngh[iị]\s*\d",
    r"quy t[aắ]c\s*[:\(]?\s*\d",
    r"theo huong dan",
    r"theo h\W*ng d[aâ]n",
    r"không nên bắt đầu",
    r"không nhắc lại",
    r"không tìm kiếm",
    r"không cần tập",
    r"khong nhac lai",
    r"khong tim kiem",
    r"khong can tap",
    # Model echo lại quy ước context
    r"context:?\s*$",
    r"=== context ===",
    r"=== answer ===",
]

SYSTEM_PROMPT = (
    "Bạn là trợ lý nghiệp vụ tiếng Việt. Luôn trả lời bằng tiếng Việt CÓ DẤU đầy đủ. "
    "Trả lời trực tiếp câu hỏi của người dùng bằng văn xuôi ngắn gọn. "
    "Sử dụng tài liệu nội bộ làm nguồn tham khảo nhưng KHÔNG được nhắc đến từ "
    "'CONTEXT', 'sample_docs', 'tài liệu', 'context', hay bất kỳ chi tiết kỹ thuật "
    "nào về cách câu trả lời được tạo ra. "
    "KHÔNG bắt đầu câu trả lời bằng 'Dựa trên...', 'Theo tài liệu...', 'Trong CONTEXT...'. "
    "KHÔNG viết ghi chú dạng '(Note: ...)' hay '(Lưu ý: ...)' ở cuối. "
    "Nếu thông tin không đủ, nói 'Tôi chưa có đủ thông tin về vấn đề này' và dừng. "
    "Không được bịa. Trả lời tự nhiên như một chuyên viên đang giải đáp trực tiếp."
)

CITATION_REQUEST_KEYWORDS = (
    "nguon",
    "tham khao",
    "trich dan",
    "trich nguon",
    "dan chung",
    "lay o dau",
    "lay tu dau",
    "tai lieu",
    "source",
    "sources",
    "citation",
    "citations",
    "reference",
    "references",
)


def _strip_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt để so khớp keyword đơn giản (nguồn -> nguon)."""
    nfkd = unicodedata.normalize("NFKD", text)
    no_marks = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    # đ/Đ không phải combining mark, xử lý riêng
    return no_marks.replace("đ", "d").replace("Đ", "D")


def wants_citations(query: str) -> bool:
    """Heuristic: user có đang yêu cầu đưa nguồn không (hỗ trợ cả có dấu lẫn không dấu)?"""
    normalized = _strip_diacritics(query.lower())
    return any(kw in normalized for kw in CITATION_REQUEST_KEYWORDS)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("Thiếu OPENROUTER_API_KEY trong môi trường.")
        _client = OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=api_key,
            timeout=settings.llm_request_timeout,
        )
    return _client


def _build_context(context_chunks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    max_chars = settings.max_context_chars
    for index, chunk in enumerate(context_chunks, start=1):
        metadata = chunk.get("metadata", {})
        title = metadata.get("title", "Untitled")
        section = metadata.get("section", "")
        url = metadata.get("url", "")
        label = f"[{index}] {title}"
        if section:
            label += f" / {section}"
        if url:
            label += f" / {url}"
        content = chunk.get("content", "") or ""
        if max_chars and len(content) > max_chars:
            content = content[:max_chars].rsplit(" ", 1)[0] + "..."
        parts.append(f"{label}\n{content}")
    return "\n\n".join(parts)


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9]{2,}", text.lower())
        if token not in STOPWORDS
    }


def _is_context_relevant(query: str, context_chunks: list[dict[str, Any]]) -> bool:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return True

    context_text = " ".join(
        " ".join(
            [
                chunk.get("content", ""),
                str(chunk.get("metadata", {}).get("title", "")),
                str(chunk.get("metadata", {}).get("section", "")),
                str(chunk.get("metadata", {}).get("topic", "")),
            ]
        )
        for chunk in context_chunks
    )
    context_tokens = _tokenize(context_text)
    overlap = query_tokens & context_tokens
    return len(overlap) >= 1


def _fallback_answer(context_chunks: list[dict[str, Any]], query: str = "") -> str:
    base = (
        "Hiện tại tôi chưa tìm thấy thông tin đủ liên quan trong kho tri thức để trả lời "
        "câu hỏi này một cách chính xác. Bạn vui lòng đặt câu hỏi cụ thể hơn hoặc nạp thêm "
        "tài liệu đúng chủ đề."
    )
    # Chỉ kèm danh sách nguồn khi người dùng có ý hỏi về nguồn
    if query and wants_citations(query) and context_chunks:
        sources: list[str] = []
        for chunk in context_chunks[:3]:
            metadata = chunk.get("metadata", {})
            title = metadata.get("title", "Untitled")
            url = metadata.get("url", "")
            sources.append(f"- {title}" + (f": {url}" if url else ""))
        if sources:
            joined = "\n".join(sources)
            base += f"\n\nNguồn liên quan gần nhất:\n{joined}"
    return base


# Pattern bắt câu mở đầu meta thường gặp. Yêu cầu match đến dấu phân cách
# (`,`, `:`, `.`, hoặc xuống dòng) sau keyword để không cắt nửa câu.
_META_OPENING_PATTERNS = [
    re.compile(
        r"^\s*Dựa\s+trên\b[^\n]*?\b(?:CONTEXT|context|sample_docs|tài\s*liệu|nội\s*dung\s*được\s*cung\s*cấp)\b[^\n]*?[,:.]\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Theo\b[^\n]*?\b(?:CONTEXT|context|sample_docs|tài\s*liệu)\b[^\n]*?[,:.]\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Trong\s+(?:CONTEXT|context|sample_docs)\b[^\n]*?[,:.]\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*câu\s+trả\s+lời\b[^\n]*?\blà\s*[:]\s*",
        re.IGNORECASE,
    ),
]
# Pattern bắt footnote meta ở cuối "(Note: ...)" / "(Lưu ý: ...)" mention internal terms
_META_FOOTNOTE_PATTERNS = [
    re.compile(r"\n*\s*\(\s*(?:Note|Lưu\s*ý|Ghi\s*chú)\s*:[^)]*?(?:CONTEXT|context|sample_docs|tài\s*liệu|nội\s*dung\s*được\s*cung)[^)]*?\)\s*$", re.IGNORECASE | re.DOTALL),
]


def strip_meta_leak(answer: str) -> str:
    """Bỏ câu mở đầu meta + footnote tham chiếu term nội bộ.

    Model yếu hay leak: 'Dựa trên CONTEXT...', '(Note: trong sample_docs...)'.
    Strip thay vì block để giữ được phần answer hợp lý ở giữa.
    """
    text = answer
    # Strip footnote ở cuối trước (tránh ảnh hưởng pattern khác)
    for pat in _META_FOOTNOTE_PATTERNS:
        text = pat.sub("", text)
    # Strip opening meta sentences (lặp 1-2 lần vì có thể có 2 câu liên tiếp)
    for _ in range(2):
        for pat in _META_OPENING_PATTERNS:
            new = pat.sub("", text, count=1)
            if new != text:
                text = new
                break
    return text.strip()


def _looks_like_garbage(answer: str) -> bool:
    lowered = answer.lower()
    if any(re.search(pattern, lowered) for pattern in GARBAGE_PATTERNS):
        return True
    if len(re.findall(r"[A-Za-zÀ-ỹ]", answer)) < 20:
        return True
    return False


def _build_messages(
    query: str,
    context_chunks: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
) -> list[dict]:
    system = SYSTEM_PROMPT
    if wants_citations(query):
        system += " Cuối câu trả lời, hãy thêm dòng bắt đầu bằng 'Nguồn tham khảo:' và liệt kê tối đa 3 nguồn."
    else:
        system += " Không thêm dòng 'Nguồn tham khảo:' hay liệt kê nguồn ở cuối."

    messages: list[dict] = [{"role": "system", "content": system}]

    # Inject lịch sử hội thoại (4 turn gần nhất) để câu trả lời tự nhiên, hiểu ngữ cảnh
    if history:
        for turn in history[-4:]:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                # Cắt ngắn để khống chế token
                if len(content) > 400:
                    content = content[:400] + "..."
                messages.append({"role": role, "content": content})

    user_content = (
        f"CONTEXT:\n{_build_context(context_chunks)}\n\n"
        f"Câu hỏi: {query}"
    )
    messages.append({"role": "user", "content": user_content})
    return messages


def _completion_kwargs(messages: list[dict], stream: bool) -> dict:
    kwargs: dict[str, Any] = {
        "model": settings.openrouter_model,
        "messages": messages,
        "max_tokens": settings.max_response_tokens,
        "temperature": 0.3,
        "stream": stream,
    }
    if settings.enable_llm_reasoning:
        kwargs["extra_body"] = {"reasoning": {"enabled": True}}
    return kwargs


def _no_context_message() -> str:
    return (
        "Hiện tại tôi chưa tìm thấy thông tin phù hợp trong kho tri thức để trả lời câu hỏi này. "
        "Bạn vui lòng cung cấp thêm tài liệu hoặc đặt câu hỏi cụ thể hơn để tôi hỗ trợ tiếp."
    )


def generate_answer(
    query: str,
    context_chunks: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
) -> str:
    """Gọi OpenRouter (non-stream) và trả về đáp án full."""
    if not context_chunks:
        return _no_context_message()
    if not _is_context_relevant(query, context_chunks):
        return _fallback_answer(context_chunks, query)

    try:
        response = _get_client().chat.completions.create(
            **_completion_kwargs(_build_messages(query, context_chunks, history), stream=False)
        )
    except Exception as exc:
        raise RuntimeError(f"Gọi OpenRouter API thất bại: {exc}") from exc

    answer = ""
    if response.choices:
        answer = (response.choices[0].message.content or "").strip()
    if not answer:
        raise RuntimeError("OpenRouter API không trả về nội dung trả lời.")
    answer = strip_meta_leak(answer)
    if _looks_like_garbage(answer):
        return _fallback_answer(context_chunks, query)
    return answer


def stream_answer(
    query: str,
    context_chunks: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
) -> Iterator[str]:
    """
    Stream câu trả lời theo từng delta. Yield string tokens.

    Lưu ý: nếu context không đủ relevant, yield 1 lần fallback rồi dừng (không gọi LLM).
    Caller cần tự buffer toàn bộ output để chạy guardrail cuối stream.
    """
    if not context_chunks:
        yield _no_context_message()
        return
    if not _is_context_relevant(query, context_chunks):
        yield _fallback_answer(context_chunks, query)
        return

    try:
        stream = _get_client().chat.completions.create(
            **_completion_kwargs(_build_messages(query, context_chunks, history), stream=True)
        )
    except Exception as exc:
        raise RuntimeError(f"Gọi OpenRouter API thất bại: {exc}") from exc

    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        token = getattr(delta, "content", None)
        if token:
            yield token


if __name__ == "__main__":
    query = "What is Python?"
    context = [
        {
            "content": "Python is a high-level programming language.",
            "metadata": {"title": "Python Basics", "url": "https://example.com/python"},
        }
    ]
    answer = generate_answer(query, context)
    print(f"Answer: {answer}")
