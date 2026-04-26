from __future__ import annotations

import json
from uuid import uuid4

import httpx
import streamlit as st

DEFAULT_API_URL = "http://localhost:8000"
SUGGESTED_QUESTIONS = [
    "Python là gì?",
    "Machine Learning có những loại nào?",
    "Chính sách hoàn tiền áp dụng ra sao?",
    "Docker Compose dùng để làm gì?",
]


def init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "api_url" not in st.session_state:
        st.session_state.api_url = DEFAULT_API_URL
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid4())
    if "debug_mode" not in st.session_state:
        st.session_state.debug_mode = False
    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = None


@st.cache_resource
def get_http_client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0))


def check_api_status(api_url: str) -> tuple[bool, str]:
    try:
        response = get_http_client().get(api_url, timeout=5.0)
        response.raise_for_status()
        payload = response.json()
        return True, payload.get("message", "API is reachable")
    except Exception as exc:
        return False, str(exc)


def fetch_sessions(api_url: str) -> list[dict]:
    try:
        r = get_http_client().get(f"{api_url}/sessions", timeout=5.0)
        r.raise_for_status()
        return r.json().get("sessions", [])
    except Exception:
        return []


def fetch_session_messages(api_url: str, session_id: str) -> list[dict]:
    try:
        r = get_http_client().get(f"{api_url}/sessions/{session_id}/messages", timeout=5.0)
        r.raise_for_status()
        return r.json().get("messages", [])
    except Exception:
        return []


def delete_session_remote(api_url: str, session_id: str) -> bool:
    try:
        r = get_http_client().delete(f"{api_url}/sessions/{session_id}", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def switch_to_session(api_url: str, session_id: str) -> None:
    """Load messages của session từ backend rồi set vào state, AI sẽ tự đọc context khi user gõ tiếp."""
    msgs = fetch_session_messages(api_url, session_id)
    st.session_state.session_id = session_id
    st.session_state.messages = [
        {
            "role": m["role"],
            "content": m["content"],
            "citations": m.get("citations", []),
            "show_citations": m.get("show_citations", False),
            "trace": m.get("trace", {}),
            "is_error": m.get("is_error", False),
        }
        for m in msgs
    ]
    st.session_state.pending_prompt = None
    st.rerun()


def new_chat() -> None:
    st.session_state.session_id = str(uuid4())
    st.session_state.messages = []
    st.session_state.pending_prompt = None
    st.rerun()


def request_answer(api_url: str, prompt: str) -> dict:
    try:
        response = get_http_client().post(
            f"{api_url}/chat",
            json={"message": prompt, "session_id": st.session_state.session_id},
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        try:
            detail = exc.response.json().get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"API trả lỗi {exc.response.status_code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Không gọi được chatbot API: {exc}") from exc


def stream_answer_events(api_url: str, prompt: str):
    """
    Generator yield event dict từ /chat/stream (NDJSON).
    Caller có thể vừa hiển thị token vừa nhận meta/done event cuối.
    """
    payload = {"message": prompt, "session_id": st.session_state.session_id}
    timeout = httpx.Timeout(60.0, connect=5.0, read=120.0)
    try:
        with httpx.stream("POST", f"{api_url}/chat/stream", json=payload, timeout=timeout) as resp:
            if resp.status_code >= 400:
                detail = resp.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"API trả lỗi {resp.status_code}: {detail}")
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Không gọi được chatbot API: {exc}") from exc


def render_citations(citations: list[dict]) -> None:
    if not citations:
        return
    with st.expander("Nguồn tham khảo", expanded=False):
        for index, item in enumerate(citations, start=1):
            title = item.get("title") or "Untitled"
            url = item.get("url") or ""
            section = item.get("section") or ""
            score = item.get("score")
            meta = []
            if section:
                meta.append(section)
            if score:
                meta.append(f"score {score}")
            suffix = f" · {' · '.join(meta)}" if meta else ""
            if url:
                st.markdown(f"{index}. [{title}]({url}){suffix}")
            else:
                st.markdown(f"{index}. {title}{suffix}")


def render_trace(trace: dict) -> None:
    if st.session_state.debug_mode and trace:
        with st.expander("Debug trace", expanded=False):
            st.json(trace)


def add_user_message(content: str) -> None:
    st.session_state.messages.append({"role": "user", "content": content})


def add_assistant_message(payload: dict) -> None:
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": payload.get("answer", ""),
            "citations": payload.get("citations", []),
            "trace": payload.get("trace", {}),
            "is_error": payload.get("is_error", False),
        }
    )


def queue_prompt(prompt: str) -> None:
    clean_prompt = prompt.strip()
    if not clean_prompt:
        st.warning("Câu hỏi không được để trống.")
        return
    # Append user message ngay để rerun render hiển thị câu hỏi liền,
    # rồi mới stream assistant message ở bước sau.
    add_user_message(clean_prompt)
    st.session_state.pending_prompt = clean_prompt
    st.rerun()


def process_pending_prompt() -> None:
    """Stream assistant message cho `pending_prompt`. User message đã được loop ở trên render."""
    pending_prompt = st.session_state.pending_prompt
    if not pending_prompt:
        return

    st.session_state.pending_prompt = None

    typing_html = (
        '<div class="typing-indicator">'
        '<span>Đang suy nghĩ</span>'
        '<span class="dots"><span></span><span></span><span></span></span>'
        '</div>'
    )

    # Stream assistant message - render đúng vị trí trong chat-shell sau loop
    with st.chat_message("assistant", avatar="✨"):
        placeholder = st.empty()
        # Hiện typing indicator ngay khi mở bubble, trước khi token đầu tiên về
        placeholder.markdown(typing_html, unsafe_allow_html=True)

        citations: list[dict] = []
        show_citations = False
        trace: dict = {}
        buffer: list[str] = []
        is_error = False
        error_message = ""

        try:
            event_iter = stream_answer_events(st.session_state.api_url, pending_prompt)
            for event in event_iter:
                etype = event.get("type")
                if etype == "meta":
                    citations = event.get("citations", []) or []
                    show_citations = bool(event.get("show_citations", False))
                elif etype == "token":
                    buffer.append(event.get("content", ""))
                    # Caret nhấp nháy thay cho typing dots khi token bắt đầu chảy
                    placeholder.markdown(
                        "".join(buffer) + '<span class="stream-caret">▍</span>',
                        unsafe_allow_html=True,
                    )
                elif etype == "blocked":
                    buffer = [event.get("message", "")]
                    placeholder.markdown("".join(buffer))
                elif etype == "done":
                    trace = event.get("trace", {})
                    final_answer = event.get("answer") or "".join(buffer)
                    buffer = [final_answer]
                    placeholder.markdown(final_answer)
                elif etype == "error":
                    is_error = True
                    error_message = event.get("message", "Có lỗi xảy ra.")
                    break
        except RuntimeError as exc:
            is_error = True
            error_message = str(exc)

        if is_error:
            placeholder.empty()
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": error_message,
                    "citations": [],
                    "trace": {},
                    "is_error": True,
                }
            )
            st.rerun()
            return

        final_answer = "".join(buffer)
        placeholder.markdown(final_answer)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": final_answer,
                "citations": citations,
                "show_citations": show_citations,
                "trace": trace,
                "is_error": False,
            }
        )
    # Rerun để vòng for ở dưới render lại đầy đủ (kèm citations/trace) thay vì hiện 2 lần
    st.rerun()


def render_suggested_questions() -> None:
    columns = st.columns(2, gap="small")
    for index, sample in enumerate(SUGGESTED_QUESTIONS):
        with columns[index % 2]:
            if st.button(sample, key=f"suggested-{index}", use_container_width=True):
                queue_prompt(sample)


st.set_page_config(
    page_title="AI Knowledge Assistant",
    page_icon="✦",
    layout="centered",
    initial_sidebar_state="expanded",
)
init_state()

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    :root {
        --bg: #ffffff;
        --canvas: #faf9f7;
        --surface: #ffffff;
        --text: #1f1f1f;
        --text-muted: #6b6b6b;
        --text-subtle: #9a9a9a;
        --border: #ececec;
        --border-strong: #d9d9d9;
        --user-bubble: #f4f4f4;
        --accent: #cc785c;
        --accent-soft: #f6efeb;
        --danger: #dc2626;
    }

    /* Base */
    .stApp {
        background: var(--canvas);
        color: var(--text);
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        font-feature-settings: "cv02", "cv03", "cv04", "cv11";
    }
    .block-container {
        max-width: 760px;
        padding-top: 1.5rem;
        padding-bottom: 7rem;
    }

    /* Hide Streamlit chrome */
    #MainMenu, footer { visibility: hidden; }
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stHeader"] {
        background: transparent;
        height: auto;
    }

    /* Sidebar — FORCE always visible, không cho collapse */
    [data-testid="stSidebar"] {
        background: var(--surface);
        border-right: 1px solid var(--border);
        min-width: 280px !important;
        max-width: 320px !important;
        width: 280px !important;
        transform: translateX(0) !important;
        visibility: visible !important;
        display: block !important;
        position: relative !important;
    }
    [data-testid="stSidebar"][aria-expanded="false"] {
        margin-left: 0 !important;
        transform: translateX(0) !important;
    }
    /* Ẩn nút collapse mặc định của Streamlit (đã có nút "+ New chat" trong sidebar) */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }
    [data-testid="stSidebar"] * { color: var(--text); }
    [data-testid="stSidebar"] h2 {
        font-size: 1rem;
        font-weight: 600;
        margin-bottom: 0.25rem;
    }
    [data-testid="stSidebar"] [data-baseweb="input"] {
        background: var(--canvas);
        border-radius: 8px;
        border: 1px solid var(--border);
    }
    [data-testid="stSidebar"] input { color: var(--text) !important; }

    /* Top header */
    .app-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.25rem 0 1rem 0;
        border-bottom: 1px solid var(--border);
        margin-bottom: 1.5rem;
    }
    .app-title {
        display: flex;
        align-items: center;
        gap: 0.55rem;
        font-size: 0.95rem;
        font-weight: 600;
        color: var(--text);
        letter-spacing: -0.01em;
    }
    .app-title .mark {
        width: 22px;
        height: 22px;
        border-radius: 6px;
        background: var(--accent);
        color: #fff;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 0.78rem;
        font-weight: 700;
    }
    .app-status {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.78rem;
        color: var(--text-muted);
    }
    .app-status .dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #16a34a;
    }
    .app-status.offline .dot { background: var(--danger); }

    /* Empty state */
    .empty-state {
        text-align: center;
        padding: 4.5rem 1rem 2rem 1rem;
    }
    .empty-state h1 {
        font-size: 1.85rem;
        font-weight: 600;
        color: var(--text);
        letter-spacing: -0.025em;
        margin: 0 0 0.5rem 0;
    }
    .empty-state p {
        color: var(--text-muted);
        font-size: 0.95rem;
        margin: 0 0 2.25rem 0;
    }
    .empty-state-prompts-label {
        font-size: 0.78rem;
        font-weight: 500;
        color: var(--text-subtle);
        text-align: left;
        margin-bottom: 0.6rem;
        letter-spacing: 0.02em;
    }

    /* Suggested prompt buttons */
    .stButton > button {
        border-radius: 12px;
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--text);
        font-weight: 400;
        font-size: 0.92rem;
        text-align: left;
        justify-content: flex-start;
        min-height: 3.2rem;
        padding: 0.7rem 0.95rem;
        box-shadow: none;
        transition: all 0.15s ease;
    }
    .stButton > button:hover {
        border-color: var(--border-strong);
        background: var(--canvas);
        color: var(--text);
    }
    .stButton > button:focus:not(:active) {
        border-color: var(--accent);
        box-shadow: 0 0 0 1px var(--accent-soft);
        color: var(--text);
    }
    /* Sidebar buttons (session list) */
    [data-testid="stSidebar"] .stButton > button {
        text-align: left;
        justify-content: flex-start;
        font-size: 0.86rem;
        font-weight: 400;
        min-height: 2.4rem;
        padding: 0.45rem 0.7rem;
        border-radius: 8px;
        background: transparent;
        border: 1px solid transparent;
        color: var(--text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: var(--canvas);
        border-color: var(--border);
    }
    /* Primary button: New chat */
    [data-testid="stSidebar"] .stButton > button[kind="primary"] {
        background: var(--accent);
        color: #fff;
        border: none;
        font-weight: 500;
        text-align: center;
        justify-content: center;
        margin-bottom: 1rem;
    }
    [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
        background: #b66b50;
        color: #fff;
        border: none;
    }
    /* Section label */
    .sidebar-section-label {
        font-size: 0.72rem;
        font-weight: 600;
        color: var(--text-subtle);
        letter-spacing: 0.06em;
        margin: 0.4rem 0 0.4rem 0.2rem;
    }
    /* Sidebar expander (Cài đặt) */
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        border: none;
        background: transparent;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        padding: 0.4rem 0.2rem;
    }

    /* Chat messages — Claude-like */
    .stChatMessage {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0.4rem 0 !important;
        margin-bottom: 1.1rem !important;
    }

    /* User message: subtle right-aligned bubble */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
        flex-direction: row-reverse;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"])
        [data-testid="stChatMessageContent"] {
        background: var(--user-bubble);
        border-radius: 18px;
        padding: 0.75rem 1.05rem;
        max-width: 85%;
        margin-left: auto;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"])
        [data-testid="chatAvatarIcon-user"] { display: none; }

    /* Assistant message: no bubble, just text on canvas */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"])
        [data-testid="stChatMessageContent"] {
        background: transparent;
        padding: 0;
    }
    [data-testid="stChatMessage"] [data-testid="stChatMessageAvatar"] {
        background: transparent !important;
        border: 1px solid var(--border);
        border-radius: 8px;
        width: 28px;
        height: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* Message typography */
    [data-testid="stChatMessageContent"] p {
        font-size: 1rem;
        line-height: 1.7;
        color: var(--text);
        margin: 0 0 0.6rem 0;
    }
    [data-testid="stChatMessageContent"] p:last-child { margin-bottom: 0; }
    [data-testid="stChatMessageContent"] code {
        background: var(--canvas);
        border: 1px solid var(--border);
        padding: 0.1rem 0.35rem;
        border-radius: 4px;
        font-size: 0.88em;
    }
    [data-testid="stChatMessageContent"] pre {
        background: #1f1f1f;
        color: #f4f4f4;
        padding: 0.9rem 1rem;
        border-radius: 10px;
        font-size: 0.88rem;
        line-height: 1.55;
    }

    /* Chat input */
    [data-testid="stChatInput"] {
        background: var(--surface);
        border: 1px solid var(--border-strong);
        border-radius: 16px;
        padding: 0.25rem;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
    }
    [data-testid="stChatInput"]:focus-within {
        border-color: var(--accent);
        box-shadow: 0 4px 20px rgba(204, 120, 92, 0.12);
    }
    [data-testid="stChatInput"] textarea {
        font-family: 'Inter', sans-serif !important;
        font-size: 0.98rem !important;
        color: var(--text) !important;
    }

    /* Expander (citations / debug trace) */
    [data-testid="stExpander"] {
        border: 1px solid var(--border);
        border-radius: 10px;
        background: var(--surface);
        margin-top: 0.5rem;
    }
    [data-testid="stExpander"] summary {
        font-size: 0.85rem;
        color: var(--text-muted);
        font-weight: 500;
    }
    [data-testid="stExpander"] summary:hover { color: var(--text); }

    /* Typing indicator (3 chấm nhảy) */
    .typing-indicator {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        color: var(--text-muted);
        font-size: 0.92rem;
        padding: 0.15rem 0;
    }
    .typing-indicator .dots {
        display: inline-flex;
        gap: 0.22rem;
    }
    .typing-indicator .dots span {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--accent);
        animation: typingBounce 1.2s infinite ease-in-out both;
    }
    .typing-indicator .dots span:nth-child(1) { animation-delay: -0.32s; }
    .typing-indicator .dots span:nth-child(2) { animation-delay: -0.16s; }
    .typing-indicator .dots span:nth-child(3) { animation-delay: 0s; }
    @keyframes typingBounce {
        0%, 80%, 100% { transform: scale(0.5); opacity: 0.4; }
        40% { transform: scale(1); opacity: 1; }
    }

    /* Caret nhấp nháy khi đang stream token */
    .stream-caret {
        display: inline-block;
        width: 0.55ch;
        color: var(--accent);
        animation: caretBlink 1s steps(1) infinite;
    }
    @keyframes caretBlink { 50% { opacity: 0; } }

    /* Status messages in sidebar */
    [data-testid="stAlert"] {
        border-radius: 8px;
        font-size: 0.85rem;
        padding: 0.55rem 0.75rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

api_ok, api_message = check_api_status(st.session_state.api_url)

# ─── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    # Nút "Cuộc trò chuyện mới"
    if st.button("＋  Cuộc trò chuyện mới", use_container_width=True, type="primary"):
        new_chat()

    st.markdown('<div class="sidebar-section-label">LỊCH SỬ</div>', unsafe_allow_html=True)

    sessions = fetch_sessions(st.session_state.api_url) if api_ok else []
    if not sessions:
        st.caption("Chưa có cuộc trò chuyện nào")
    else:
        active_sid = st.session_state.session_id
        for s in sessions:
            sid = s["id"]
            title = s.get("title") or "Cuộc trò chuyện"
            is_active = sid == active_sid
            cols = st.columns([0.82, 0.18], gap="small")
            with cols[0]:
                btn_label = ("● " if is_active else "") + title
                if st.button(
                    btn_label,
                    key=f"sess-{sid}",
                    use_container_width=True,
                    help=f"{s.get('message_count', 0)} tin nhắn",
                ):
                    if not is_active:
                        switch_to_session(st.session_state.api_url, sid)
            with cols[1]:
                if st.button("✕", key=f"del-{sid}", help="Xóa cuộc trò chuyện"):
                    delete_session_remote(st.session_state.api_url, sid)
                    if is_active:
                        new_chat()
                    else:
                        st.rerun()

    st.divider()
    with st.expander("Cài đặt", expanded=False):
        st.session_state.api_url = st.text_input(
            "API endpoint",
            value=st.session_state.api_url,
            help="FastAPI backend, mặc định http://localhost:8000",
        ).rstrip("/")

        st.session_state.debug_mode = st.toggle(
            "Hiện debug trace",
            value=st.session_state.debug_mode,
            help="Hiện trace kỹ thuật dưới mỗi câu trả lời.",
        )

    st.caption(f"Phiên: `{st.session_state.session_id[:8]}`")
    if not api_ok:
        st.caption(f"⚠️ {api_message}")

# ─── Header ─────────────────────────────────────────────────────────────────
status_class = "" if api_ok else "offline"
status_text = "Sẵn sàng" if api_ok else "Mất kết nối"
st.markdown(
    f"""
    <div class="app-header">
        <div class="app-title">
            <span class="mark">✦</span>
            <span>AI Knowledge Assistant</span>
        </div>
        <div class="app-status {status_class}">
            <span class="dot"></span>
            <span>{status_text}</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ─── Empty state ────────────────────────────────────────────────────────────
if not st.session_state.messages:
    st.markdown(
        """
        <div class="empty-state">
            <h1>Tôi có thể giúp gì cho bạn?</h1>
            <p>Hỏi bất kỳ câu hỏi nào dựa trên kho tri thức đã nạp.</p>
        </div>
        <div class="empty-state-prompts-label">GỢI Ý</div>
        """,
        unsafe_allow_html=True,
    )
    render_suggested_questions()

# ─── Conversation ───────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    avatar = "🧑" if msg["role"] == "user" else "✨"
    with st.chat_message(msg["role"], avatar=avatar):
        if msg["role"] == "assistant" and msg.get("is_error"):
            st.error(msg["content"])
        else:
            st.markdown(msg["content"])
        if msg["role"] == "assistant":
            if msg.get("show_citations"):
                render_citations(msg.get("citations", []))
            render_trace(msg.get("trace", {}))

# Stream assistant message cho pending prompt (xuất hiện ngay sau user message ở loop trên)
process_pending_prompt()

prompt = st.chat_input("Nhập câu hỏi của bạn...")
if prompt:
    queue_prompt(prompt)
