"""Admin Portal — quản trị KB, sources, sessions, cache.

Truy cập: http://localhost:8501/Admin
Backend endpoints dưới /admin/* (api/admin.py).
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx
import streamlit as st

DEFAULT_API_URL = os.getenv("DEFAULT_API_URL") or f"http://localhost:{os.getenv('UVICORN_PORT', '8000')}"

st.set_page_config(
    page_title="Admin · AI Knowledge Assistant",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def http() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0))


def api_url() -> str:
    return st.session_state.get("api_url", DEFAULT_API_URL).rstrip("/")


# ─── API helpers ────────────────────────────────────────────────────────────
def get_sources() -> list[dict]:
    try:
        r = http().get(f"{api_url()}/admin/sources")
        r.raise_for_status()
        return r.json().get("topics", [])
    except Exception as exc:
        st.error(f"Không lấy được sources: {exc}")
        return []


def add_url(topic: str, location: str, title: str = "") -> tuple[bool, str]:
    try:
        r = http().post(
            f"{api_url()}/admin/sources/{topic}",
            json={"location": location, "topic": topic, "title": title or location, "source": "website"},
        )
        if r.status_code == 200:
            return True, f"Đã thêm vào {topic}"
        return False, r.json().get("detail", r.text)
    except Exception as exc:
        return False, str(exc)


def delete_url(topic: str, location: str) -> bool:
    try:
        r = http().request(
            "DELETE",
            f"{api_url()}/admin/sources/{topic}",
            json={"location": location},
        )
        return r.status_code == 200
    except Exception:
        return False


def trigger_ingest(topic: str | None = None, urls: list[dict] | None = None, reset: bool = False) -> dict | None:
    try:
        body: dict = {"reset": reset}
        if topic:
            body["topic"] = topic
        if urls:
            body["urls"] = urls
        r = http().post(
            f"{api_url()}/admin/ingest", json=body,
            timeout=httpx.Timeout(600.0, connect=5.0, read=600.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Ingest thất bại: {exc}")
        return None


def run_health(topic: str | None = None) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/health-check",
            json={"topic": topic} if topic else {},
            timeout=httpx.Timeout(300.0, connect=5.0, read=300.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Health check thất bại: {exc}")
        return None


def get_stats() -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/stats")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được stats: {exc}")
        return None


def get_sessions() -> list[dict]:
    try:
        r = http().get(f"{api_url()}/sessions")
        r.raise_for_status()
        return r.json().get("sessions", [])
    except Exception:
        return []


def delete_session(sid: str) -> bool:
    try:
        return http().delete(f"{api_url()}/sessions/{sid}").status_code == 200
    except Exception:
        return False


def clear_cache() -> bool:
    try:
        return http().post(f"{api_url()}/admin/cache/clear").status_code == 200
    except Exception:
        return False


def rebuild_bm25() -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/bm25/rebuild",
            timeout=httpx.Timeout(120.0, connect=5.0, read=120.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Rebuild thất bại: {exc}")
        return None


def check_backend() -> bool:
    try:
        r = http().get(f"{api_url()}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


# ─── CSS ────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    :root {
        --canvas: #faf9f7;
        --surface: #ffffff;
        --text: #1f1f1f;
        --text-muted: #6b6b6b;
        --text-subtle: #9a9a9a;
        --border: #ececec;
        --border-strong: #d9d9d9;
        --accent: #cc785c;
        --accent-soft: #f6efeb;
        --ok: #16a34a;
        --warn: #d97706;
        --danger: #dc2626;
    }

    .stApp {
        background: var(--canvas);
        color: var(--text);
        font-family: 'Inter', -apple-system, sans-serif;
    }
    .block-container {
        max-width: 1200px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }

    /* Hide Streamlit chrome */
    #MainMenu, footer { visibility: hidden; }
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stHeader"] {
        background: transparent;
        height: auto;
    }

    /* Sidebar - dạng admin nav, FORCE always visible */
    [data-testid="stSidebar"] {
        background: var(--surface);
        border-right: 1px solid var(--border);
        min-width: 260px !important;
        max-width: 280px !important;
        width: 260px !important;
        transform: translateX(0) !important;
        visibility: visible !important;
        display: block !important;
        position: relative !important;
    }
    [data-testid="stSidebar"][aria-expanded="false"] {
        margin-left: 0 !important;
        transform: translateX(0) !important;
    }
    [data-testid="stSidebar"] > div:first-child {
        padding: 1.2rem 0.8rem;
    }
    /* Ẩn nút collapse mặc định của Streamlit - sidebar luôn cứng */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }

    /* Brand block */
    .brand {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        padding: 0.4rem 0.6rem 1.2rem 0.6rem;
        border-bottom: 1px solid var(--border);
        margin-bottom: 1rem;
    }
    .brand-mark {
        width: 32px; height: 32px;
        border-radius: 8px;
        background: var(--accent);
        color: white;
        display: flex; align-items: center; justify-content: center;
        font-weight: 700;
        font-size: 1rem;
    }
    .brand-text {
        font-weight: 600;
        font-size: 0.95rem;
        line-height: 1.2;
    }
    .brand-sub {
        font-size: 0.72rem;
        color: var(--text-subtle);
        margin-top: 0.1rem;
    }

    /* Section label trong sidebar */
    .nav-label {
        font-size: 0.7rem;
        font-weight: 600;
        color: var(--text-subtle);
        letter-spacing: 0.08em;
        text-transform: uppercase;
        padding: 0 0.6rem 0.4rem;
        margin-top: 0.5rem;
    }

    /* Nav button styling - radio styled as nav items */
    [data-testid="stSidebar"] [role="radiogroup"] {
        gap: 0.15rem !important;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        padding: 0.55rem 0.7rem;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.12s ease;
        display: flex;
        align-items: center;
        margin: 0 !important;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: var(--canvas);
    }
    [data-testid="stSidebar"] [role="radiogroup"] label[data-checked="true"],
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
        background: var(--accent-soft);
        color: var(--accent);
        font-weight: 500;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {
        display: none !important;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label > div:last-child p {
        font-size: 0.92rem;
        margin: 0;
    }

    /* Status pill ở dưới sidebar */
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.4rem 0.7rem;
        border-radius: 8px;
        background: var(--canvas);
        border: 1px solid var(--border);
        font-size: 0.78rem;
        margin: 0.3rem 0.6rem;
    }
    .status-pill.online .dot { background: var(--ok); }
    .status-pill.offline .dot { background: var(--danger); }
    .status-pill .dot {
        width: 8px; height: 8px;
        border-radius: 50%;
    }

    /* Page header */
    .page-header {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        padding-bottom: 1rem;
        border-bottom: 1px solid var(--border);
        margin-bottom: 1.5rem;
    }
    .page-title {
        font-size: 1.5rem;
        font-weight: 600;
        letter-spacing: -0.02em;
        margin: 0;
        color: var(--text);
    }
    .page-subtitle {
        color: var(--text-muted);
        font-size: 0.92rem;
        margin: 0.25rem 0 0;
    }

    /* Card */
    .admin-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1.2rem;
        margin-bottom: 1rem;
    }
    .card-title {
        font-size: 0.95rem;
        font-weight: 600;
        margin: 0 0 0.6rem;
        color: var(--text);
    }

    /* Buttons */
    .stButton > button {
        border-radius: 8px;
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--text);
        font-weight: 500;
        font-size: 0.88rem;
        padding: 0.5rem 0.9rem;
        transition: all 0.12s ease;
    }
    .stButton > button:hover {
        border-color: var(--border-strong);
        background: var(--canvas);
    }
    .stButton > button[kind="primary"] {
        background: var(--accent);
        color: white;
        border: none;
    }
    .stButton > button[kind="primary"]:hover {
        background: #b66b50;
        border: none;
    }

    /* Inputs */
    [data-baseweb="input"] {
        border-radius: 8px !important;
        border-color: var(--border) !important;
    }
    [data-baseweb="input"]:focus-within {
        border-color: var(--accent) !important;
    }
    [data-baseweb="select"] {
        border-radius: 8px !important;
    }

    /* Metrics */
    [data-testid="stMetric"] {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 0.9rem 1.1rem;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.78rem;
        color: var(--text-muted);
        font-weight: 500;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.6rem;
        font-weight: 600;
        color: var(--text);
        letter-spacing: -0.02em;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.78rem;
        color: var(--text-subtle);
    }

    /* Status icons trong list */
    .status-row {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        padding: 0.5rem 0.7rem;
        border-radius: 6px;
        margin-bottom: 0.2rem;
        font-size: 0.86rem;
    }
    .status-row:hover { background: var(--canvas); }
    .status-row .badge {
        flex-shrink: 0;
        font-weight: 600;
        font-size: 0.72rem;
        padding: 0.15rem 0.5rem;
        border-radius: 4px;
        min-width: 70px;
        text-align: center;
    }
    .status-row.ok .badge       { background: #ecfdf5; color: var(--ok); }
    .status-row.stale .badge    { background: #fef3c7; color: var(--warn); }
    .status-row.dead .badge     { background: #fee2e2; color: var(--danger); }
    .status-row.redirect .badge { background: #fef3c7; color: var(--warn); }
    .status-row.unknown .badge  { background: #f3f4f6; color: var(--text-muted); }
    .status-row .topic { color: var(--text-muted); font-size: 0.78rem; flex-shrink: 0; }
    .status-row .url {
        flex-grow: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .status-row .detail { color: var(--text-subtle); font-size: 0.78rem; }

    /* Expander */
    [data-testid="stExpander"] {
        border: 1px solid var(--border);
        border-radius: 10px;
        background: var(--surface);
        margin-bottom: 0.4rem;
    }
    [data-testid="stExpander"] summary {
        font-weight: 500;
        font-size: 0.9rem;
    }

    /* Table */
    [data-testid="stDataFrame"] {
        border: 1px solid var(--border);
        border-radius: 10px;
        overflow: hidden;
    }

    /* Form */
    [data-testid="stForm"] {
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1.2rem;
        background: var(--surface);
    }

    /* URL list item trong topic expander */
    .url-item {
        font-size: 0.82rem;
        color: var(--text);
        padding: 0.35rem 0;
        line-height: 1.4;
    }
    .url-item .url-title { font-weight: 500; }
    .url-item .url-link { color: var(--text-subtle); font-size: 0.76rem; }

    /* Hide form border when inside cards */
    [data-testid="stForm"] [data-testid="stForm"] {
        border: none;
        padding: 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─── Sidebar Navigation ─────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div class="brand">'
        '  <div class="brand-mark">A</div>'
        '  <div>'
        '    <div class="brand-text">Admin Portal</div>'
        '    <div class="brand-sub">AI Knowledge Assistant</div>'
        '  </div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="nav-label">Quản lý</div>', unsafe_allow_html=True)
    page = st.radio(
        "Navigation",
        options=[
            "Dashboard",
            "Sources",
            "Health Check",
            "Sessions",
            "Maintenance",
        ],
        label_visibility="collapsed",
        key="admin_nav",
    )

    st.markdown('<div style="flex-grow:1; min-height: 2rem"></div>', unsafe_allow_html=True)

    backend_ok = check_backend()
    pill_class = "online" if backend_ok else "offline"
    pill_text = "Backend online" if backend_ok else "Backend offline"
    st.markdown(
        f'<div class="status-pill {pill_class}"><span class="dot"></span>{pill_text}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="status-pill" style="font-size:0.72rem; color: var(--text-subtle)">'
        f'{api_url()}</div>',
        unsafe_allow_html=True,
    )


# ─── Helpers cho main render ────────────────────────────────────────────────
def render_page_header(title: str, subtitle: str = "", actions: callable = None):
    cols = st.columns([4, 1])
    with cols[0]:
        st.markdown(
            f'<div class="page-header">'
            f'<div><h1 class="page-title">{title}</h1>'
            f'<p class="page-subtitle">{subtitle}</p></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    if actions:
        with cols[1]:
            actions()


def status_row_html(r: dict) -> str:
    cls = r["status"].lower()
    icon = {"OK": "✓", "STALE": "⚠", "DEAD": "✗", "REDIRECT": "↪", "UNKNOWN": "?"}.get(r["status"], "·")
    return (
        f'<div class="status-row {cls}">'
        f'  <span class="badge">{icon} {r["status"]}</span>'
        f'  <span class="topic">[{r["topic"]}]</span>'
        f'  <span class="url">{r["location"][:90]}</span>'
        f'  <span class="detail">{r["detail"]}</span>'
        f'</div>'
    )


# ─── Page: Dashboard ────────────────────────────────────────────────────────
def page_dashboard():
    render_page_header(
        "Dashboard",
        "Tổng quan hệ thống Knowledge Base",
    )

    stats = get_stats()
    if not stats:
        st.warning("Chưa lấy được stats. Kiểm tra backend.")
        return

    # Top metrics row
    c = st.columns(4)
    c[0].metric("Total chunks", f"{stats['chunks']['total']:,}")
    c[1].metric("Topics", len(stats["chunks"]["by_topic"]))
    c[2].metric("Sessions", stats["sessions"]["count_with_messages"])
    c[3].metric(
        "Cache size",
        f"{stats['cache']['size']}",
        f"max {stats['cache']['max_size']}",
    )

    st.markdown("&nbsp;")

    col_left, col_right = st.columns([3, 2], gap="medium")

    with col_left:
        st.markdown('<div class="card-title">Chunks per topic</div>', unsafe_allow_html=True)
        if stats["chunks"]["by_topic"]:
            st.bar_chart(stats["chunks"]["by_topic"], height=280)
        else:
            st.caption("Chưa có data.")

    with col_right:
        st.markdown('<div class="card-title">Hệ thống</div>', unsafe_allow_html=True)
        bm25 = stats["bm25"]
        bm25_status = "✓ Ready" if bm25["enabled_ready"] else "✗ Not ready"
        st.metric("BM25 Index", bm25_status, f"{bm25['indexed_chunks']:,} chunks")

        metrics = stats.get("metrics", {})
        st.metric(
            "Latency trung bình",
            f"{metrics.get('latency_avg_ms', 0):.0f} ms",
            f"max {metrics.get('latency_max_ms', 0):.0f} ms",
        )

    counters = (stats.get("metrics") or {}).get("counters", {})
    if counters:
        st.markdown("&nbsp;")
        st.markdown('<div class="card-title">Counters</div>', unsafe_allow_html=True)
        st.dataframe(
            {"Counter": list(counters.keys()), "Value": list(counters.values())},
            hide_index=True, use_container_width=True,
        )


# ─── Helpers cho multi-URL input ────────────────────────────────────────────
def parse_url_lines(text: str) -> list[tuple[str, str]]:
    """Parse textarea: mỗi dòng 1 URL.

    Format hỗ trợ:
        https://example.com/page
        https://example.com/page | Tiêu đề tuỳ chỉnh
        # comment - bỏ qua

    Trả về list[(url, title)]. Title rỗng nếu không có "|".
    """
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            url, title = (s.strip() for s in line.split("|", 1))
        else:
            url, title = line, ""
        if url:
            out.append((url, title))
    return out


def bulk_add_urls(
    topic: str, url_lines: list[tuple[str, str]], crawl_after: bool,
) -> tuple[int, int, list[str]]:
    """Thêm nhiều URL vào 1 topic. Trả về (added, skipped, errors)."""
    added = 0
    skipped = 0
    errors: list[str] = []
    for url, title in url_lines:
        ok, msg = add_url(topic, url, title)
        if ok:
            added += 1
        elif "đã tồn tại" in msg.lower() or "already" in msg.lower():
            skipped += 1
        else:
            errors.append(f"{url}: {msg}")

    if crawl_after and added > 0:
        with st.spinner(f"Đang crawl + index {topic}..."):
            res = trigger_ingest(topic=topic)
        if res:
            st.info(
                f"Đã crawl: {res['documents_crawled']} docs, "
                f"{res['chunks_indexed']} chunks"
            )
    return added, skipped, errors


# ─── Page: Sources ──────────────────────────────────────────────────────────
def page_sources():
    render_page_header(
        "Sources",
        "Quản lý nguồn dữ liệu được crawl vào knowledge base",
    )

    # ─── Form: Thêm topic + nhiều URL ──────────────────────────────────────
    st.markdown('<div class="card-title">Thêm topic mới (hoặc thêm vào topic có sẵn)</div>', unsafe_allow_html=True)
    with st.form("add_topic_form", clear_on_submit=True):
        new_topic = st.text_input(
            "Tên topic", placeholder="vd: kubernetes, react, fastapi",
        )
        url_block = st.text_area(
            "Danh sách URL (mỗi dòng 1 URL)",
            placeholder=(
                "https://docs.example.com/page-1\n"
                "https://docs.example.com/page-2 | Tiêu đề tuỳ chỉnh\n"
                "# Dòng bắt đầu '#' sẽ bị bỏ qua\n"
                "https://docs.example.com/page-3"
            ),
            height=150,
            help='Format: "URL" hoặc "URL | Title". Comment bằng "#".',
        )
        bcols = st.columns([2, 1])
        with bcols[0]:
            crawl_after_add = st.checkbox(
                "Crawl + index ngay sau khi thêm", value=True,
                help="Tự động re-crawl toàn bộ topic ngay sau khi thêm xong.",
            )
        with bcols[1]:
            submit = st.form_submit_button(
                "Thêm vào sources", type="primary", use_container_width=True,
            )
        if submit:
            topic_clean = (new_topic or "").strip()
            url_lines = parse_url_lines(url_block or "")
            if not topic_clean:
                st.error("Cần nhập tên topic.")
            elif not url_lines:
                st.error("Cần ít nhất 1 URL.")
            else:
                added, skipped, errors = bulk_add_urls(
                    topic_clean, url_lines, crawl_after_add,
                )
                msg_parts = []
                if added:
                    msg_parts.append(f"thêm {added}")
                if skipped:
                    msg_parts.append(f"đã có {skipped}")
                if errors:
                    msg_parts.append(f"lỗi {len(errors)}")
                summary = " · ".join(msg_parts) or "không có thay đổi"
                if errors:
                    st.warning(f"{summary}")
                    with st.expander("Chi tiết lỗi"):
                        for e in errors:
                            st.text(f"- {e}")
                else:
                    st.success(summary)

    st.markdown("&nbsp;")
    st.markdown('<div class="card-title">Crawl ad-hoc (không lưu vào sources file)</div>', unsafe_allow_html=True)
    with st.form("adhoc_crawl"):
        c = st.columns([1, 3, 1])
        with c[0]:
            adhoc_topic = st.text_input(
                "Topic", value="general", key="adhoc_topic", label_visibility="collapsed",
                placeholder="topic",
            )
        with c[1]:
            adhoc_url = st.text_input(
                "URL", placeholder="https://...", key="adhoc_url", label_visibility="collapsed",
            )
        with c[2]:
            adhoc_submit = st.form_submit_button("Crawl ngay", use_container_width=True)
        if adhoc_submit and adhoc_url:
            with st.spinner("Đang crawl + index..."):
                res = trigger_ingest(urls=[{
                    "location": adhoc_url.strip(),
                    "topic": adhoc_topic.strip() or "general",
                    "title": adhoc_url.strip(),
                    "source": "website",
                }])
            if res:
                st.success(f"{res['documents_crawled']} docs, {res['chunks_indexed']} chunks")

    st.markdown("&nbsp;")
    st.markdown('<div class="card-title">Topics hiện có</div>', unsafe_allow_html=True)

    topics_all = get_sources()
    if not topics_all:
        st.info("Chưa có topic nào. Thêm URL ở form trên để tạo topic mới.")
        return

    # ─── Search + filter ──────────────────────────────────────────────────
    fcols = st.columns([3, 1, 1])
    with fcols[0]:
        search_q = st.text_input(
            "Tìm topic",
            placeholder="Nhập tên topic hoặc URL để lọc...",
            key="topic_search",
            label_visibility="collapsed",
        )
    with fcols[1]:
        sort_by = st.selectbox(
            "Sắp xếp",
            options=["Tên (A→Z)", "Tên (Z→A)", "URLs nhiều nhất", "URLs ít nhất"],
            label_visibility="collapsed",
            key="topic_sort",
        )
    with fcols[2]:
        page_size = st.selectbox(
            "Mỗi trang",
            options=[5, 10, 20, 50],
            index=1,
            label_visibility="collapsed",
            key="topic_page_size",
        )

    # Filter
    q = (search_q or "").strip().lower()
    if q:
        def match(t):
            if q in t["topic"].lower():
                return True
            return any(
                q in (it.get("location") or "").lower()
                or q in (it.get("title") or "").lower()
                for it in t.get("items", [])
            )
        topics = [t for t in topics_all if match(t)]
    else:
        topics = list(topics_all)

    # Sort
    if sort_by == "Tên (A→Z)":
        topics.sort(key=lambda t: t["topic"].lower())
    elif sort_by == "Tên (Z→A)":
        topics.sort(key=lambda t: t["topic"].lower(), reverse=True)
    elif sort_by == "URLs nhiều nhất":
        topics.sort(key=lambda t: t["count"], reverse=True)
    else:  # URLs ít nhất
        topics.sort(key=lambda t: t["count"])

    # Pagination
    total = len(topics)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page_key = "topic_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 1
    # Reset page khi search/sort/page_size đổi
    state_sig = f"{q}|{sort_by}|{page_size}|{len(topics_all)}"
    if st.session_state.get("topic_state_sig") != state_sig:
        st.session_state["topic_state_sig"] = state_sig
        st.session_state[page_key] = 1
    current_page = min(st.session_state[page_key], total_pages)

    start = (current_page - 1) * page_size
    end = start + page_size
    visible = topics[start:end]

    # Header thông tin filter
    filter_info = f"{total} / {len(topics_all)} topic" if q else f"{total} topic"
    st.caption(f"{filter_info} · Trang {current_page}/{total_pages}")

    if not visible:
        st.info("Không có topic nào khớp filter.")
        return

    for t in visible:
        with st.expander(f"**{t['topic']}** · {t['count']} URLs", expanded=False):
            cols = st.columns([3, 1])
            with cols[0]:
                st.caption(f"File: `{t['file']}`")
            with cols[1]:
                if st.button("Re-crawl topic", key=f"recrawl-{t['topic']}", use_container_width=True):
                    with st.spinner(f"Đang re-crawl {t['topic']}..."):
                        res = trigger_ingest(topic=t["topic"])
                    if res:
                        st.success(f"{res['documents_crawled']} docs, {res['chunks_indexed']} chunks")

            # Form thêm URL vào topic hiện tại
            with st.form(f"add_to_{t['topic']}", clear_on_submit=True):
                st.caption(f"Thêm URL vào topic `{t['topic']}` (mỗi dòng 1 URL):")
                more_urls = st.text_area(
                    "URLs",
                    placeholder="https://...\nhttps://... | Title",
                    height=100,
                    key=f"more-{t['topic']}",
                    label_visibility="collapsed",
                )
                ac = st.columns([2, 1])
                with ac[0]:
                    crawl_now = st.checkbox(
                        "Crawl ngay sau khi thêm", value=True,
                        key=f"crawl-now-{t['topic']}",
                    )
                with ac[1]:
                    if st.form_submit_button("Thêm", use_container_width=True):
                        url_lines = parse_url_lines(more_urls or "")
                        if not url_lines:
                            st.error("Chưa nhập URL nào.")
                        else:
                            added, skipped, errors = bulk_add_urls(
                                t["topic"], url_lines, crawl_now,
                            )
                            if added:
                                st.success(f"Thêm {added} URLs vào {t['topic']}")
                            if skipped:
                                st.info(f"{skipped} URLs đã có sẵn (bỏ qua)")
                            if errors:
                                st.warning(f"{len(errors)} URLs lỗi")
                                with st.expander("Chi tiết"):
                                    for e in errors:
                                        st.text(f"- {e}")
                            if added or errors:
                                st.rerun()

            # Danh sách URL đã có với checkbox để chọn re-crawl
            if not t["items"]:
                st.caption("(rỗng)")
            else:
                topic = t["topic"]
                sel_state_key = f"sel_urls_{topic}"
                if sel_state_key not in st.session_state:
                    st.session_state[sel_state_key] = set()
                selected: set = st.session_state[sel_state_key]

                # Toolbar: chọn tất cả + re-crawl selected
                tcols = st.columns([2, 2, 2, 1])
                with tcols[0]:
                    if st.button(
                        "Chọn tất cả",
                        key=f"selall-{topic}",
                        use_container_width=True,
                        disabled=len(selected) == len(t["items"]),
                    ):
                        st.session_state[sel_state_key] = {it["location"] for it in t["items"]}
                        st.rerun()
                with tcols[1]:
                    if st.button(
                        "Bỏ chọn",
                        key=f"selnone-{topic}",
                        use_container_width=True,
                        disabled=len(selected) == 0,
                    ):
                        st.session_state[sel_state_key] = set()
                        st.rerun()
                with tcols[2]:
                    if st.button(
                        f"Re-crawl đã chọn ({len(selected)})",
                        key=f"recrawl-sel-{topic}",
                        use_container_width=True,
                        disabled=len(selected) == 0,
                        type="primary",
                    ):
                        urls_to_crawl = [
                            {
                                "location": it["location"],
                                "topic": topic,
                                "title": it.get("title", it["location"]),
                                "source": it.get("source", "website"),
                            }
                            for it in t["items"]
                            if it["location"] in selected
                        ]
                        with st.spinner(f"Re-crawl {len(urls_to_crawl)} URLs..."):
                            res = trigger_ingest(urls=urls_to_crawl)
                        if res:
                            st.success(
                                f"{res['documents_crawled']} docs, "
                                f"{res['chunks_indexed']} chunks"
                            )
                            st.session_state[sel_state_key] = set()

                # List URLs với checkbox per row
                for item in t["items"]:
                    loc = item["location"]
                    row = st.columns([0.5, 4.5, 1])
                    with row[0]:
                        checked = st.checkbox(
                            "Sel",
                            value=loc in selected,
                            key=f"chk-{topic}-{loc}",
                            label_visibility="collapsed",
                        )
                        # Sync selection state
                        if checked and loc not in selected:
                            selected.add(loc)
                        elif not checked and loc in selected:
                            selected.discard(loc)
                    with row[1]:
                        st.markdown(
                            f'<div class="url-item">'
                            f'<div class="url-title">{item.get("title", loc)}</div>'
                            f'<div class="url-link">{loc}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    with row[2]:
                        rcols = st.columns(2, gap="small")
                        with rcols[0]:
                            if st.button(
                                "↻",
                                key=f"recrawl-one-{topic}-{loc}",
                                help="Re-crawl URL này",
                                use_container_width=True,
                            ):
                                with st.spinner(f"Re-crawl {loc[:50]}..."):
                                    res = trigger_ingest(urls=[{
                                        "location": loc,
                                        "topic": topic,
                                        "title": item.get("title", loc),
                                        "source": item.get("source", "website"),
                                    }])
                                if res:
                                    st.success(f"{res['chunks_indexed']} chunks")
                        with rcols[1]:
                            if st.button(
                                "✕",
                                key=f"del-{topic}-{loc}",
                                help="Xoá URL khỏi sources",
                                use_container_width=True,
                            ):
                                if delete_url(topic, loc):
                                    selected.discard(loc)
                                    st.rerun()

    # ─── Pagination controls ──────────────────────────────────────────────
    if total_pages > 1:
        st.markdown("&nbsp;")
        pcols = st.columns([1, 1, 3, 1, 1])
        with pcols[0]:
            if st.button("« Đầu", disabled=current_page == 1, use_container_width=True, key="pg_first"):
                st.session_state[page_key] = 1
                st.rerun()
        with pcols[1]:
            if st.button("‹ Trước", disabled=current_page == 1, use_container_width=True, key="pg_prev"):
                st.session_state[page_key] = current_page - 1
                st.rerun()
        with pcols[2]:
            jump = st.number_input(
                "Trang", min_value=1, max_value=total_pages, value=current_page,
                step=1, label_visibility="collapsed", key="pg_jump",
            )
            if jump != current_page:
                st.session_state[page_key] = int(jump)
                st.rerun()
        with pcols[3]:
            if st.button("Sau ›", disabled=current_page >= total_pages, use_container_width=True, key="pg_next"):
                st.session_state[page_key] = current_page + 1
                st.rerun()
        with pcols[4]:
            if st.button("Cuối »", disabled=current_page >= total_pages, use_container_width=True, key="pg_last"):
                st.session_state[page_key] = total_pages
                st.rerun()


# ─── Page: Health Check ─────────────────────────────────────────────────────
def page_health():
    render_page_header(
        "Health Check",
        "Kiểm tra URLs còn live, detect content thay đổi",
    )

    topics = get_sources()
    topic_names = ["(tất cả)"] + [t["topic"] for t in topics]

    cols = st.columns([2, 1, 1])
    with cols[0]:
        selected = st.selectbox("Topic", topic_names, label_visibility="collapsed")
    with cols[1]:
        run_btn = st.button("Chạy check", type="primary", use_container_width=True)
    with cols[2]:
        if "health_result" in st.session_state:
            if st.button("Xoá kết quả", use_container_width=True):
                del st.session_state["health_result"]
                st.rerun()

    selected_topic = None if selected == "(tất cả)" else selected

    if run_btn:
        with st.spinner("Đang check (1-2 phút)..."):
            result = run_health(selected_topic)
        if result:
            st.session_state["health_result"] = result
            st.session_state["health_run_at"] = datetime.now().strftime("%H:%M:%S")

    if "health_result" not in st.session_state:
        st.info("Chưa có kết quả. Click 'Chạy check' để bắt đầu.")
        return

    result = st.session_state["health_result"]
    run_at = st.session_state.get("health_run_at", "")

    st.caption(f"Last run: {run_at}")
    m_cols = st.columns(5)
    m_cols[0].metric("Total", result["total"])
    m_cols[1].metric("OK", result["ok"])
    m_cols[2].metric("Stale", result["stale"])
    m_cols[3].metric("Dead", result["dead"])
    m_cols[4].metric("Redirect", result["redirect"])

    st.markdown("&nbsp;")
    st.markdown('<div class="card-title">Filter</div>', unsafe_allow_html=True)
    f_cols = st.columns(5)
    show_ok = f_cols[0].checkbox("OK", value=False)
    show_stale = f_cols[1].checkbox("Stale", value=True)
    show_dead = f_cols[2].checkbox("Dead", value=True)
    show_redirect = f_cols[3].checkbox("Redirect", value=True)
    show_unknown = f_cols[4].checkbox("Unknown", value=True)

    wanted = set()
    if show_ok:
        wanted.add("OK")
    if show_stale:
        wanted.add("STALE")
    if show_dead:
        wanted.add("DEAD")
    if show_redirect:
        wanted.add("REDIRECT")
    if show_unknown:
        wanted.add("UNKNOWN")

    visible_rows = [r for r in result["results"] if r["status"] in wanted]
    if not visible_rows:
        st.caption("(không có entry nào với filter hiện tại)")
        return

    # Selection state cho Health rows
    health_sel_key = "health_selected_urls"
    if health_sel_key not in st.session_state:
        st.session_state[health_sel_key] = set()
    health_selected: set = st.session_state[health_sel_key]

    # Toolbar trên list: chọn tất cả stale, bỏ chọn, re-crawl đã chọn
    actionable = [r for r in visible_rows if r["status"] in ("STALE", "REDIRECT", "DEAD")]
    tcols = st.columns([2, 2, 2, 1])
    with tcols[0]:
        if st.button(
            f"Chọn tất cả STALE ({sum(1 for r in actionable if r['status'] == 'STALE')})",
            use_container_width=True,
            key="health_sel_stale",
            disabled=not any(r["status"] == "STALE" for r in actionable),
        ):
            st.session_state[health_sel_key] = {
                r["location"] for r in actionable if r["status"] == "STALE"
            }
            st.rerun()
    with tcols[1]:
        if st.button(
            "Bỏ chọn tất cả",
            use_container_width=True,
            key="health_sel_none",
            disabled=len(health_selected) == 0,
        ):
            st.session_state[health_sel_key] = set()
            st.rerun()
    with tcols[2]:
        if st.button(
            f"Re-crawl đã chọn ({len(health_selected)})",
            type="primary",
            use_container_width=True,
            key="health_recrawl_selected",
            disabled=len(health_selected) == 0,
        ):
            urls_to_update = [
                {"location": r["location"], "topic": r["topic"], "title": r["title"], "source": "website"}
                for r in result["results"]
                if r["location"] in health_selected
            ]
            with st.spinner(f"Re-crawl {len(urls_to_update)} URLs..."):
                res = trigger_ingest(urls=urls_to_update)
            if res:
                st.success(f"{res['documents_crawled']} docs, {res['chunks_indexed']} chunks")
                st.session_state[health_sel_key] = set()

    # Render từng row: STALE/REDIRECT/DEAD có checkbox + nút re-crawl đơn lẻ;
    # OK/UNKNOWN chỉ hiển thị
    for r in visible_rows:
        loc = r["location"]
        is_actionable = r["status"] in ("STALE", "REDIRECT", "DEAD")
        if is_actionable:
            cols = st.columns([0.4, 6, 0.6])
            with cols[0]:
                checked = st.checkbox(
                    "Sel",
                    value=loc in health_selected,
                    key=f"hchk-{loc}",
                    label_visibility="collapsed",
                )
                if checked and loc not in health_selected:
                    health_selected.add(loc)
                elif not checked and loc in health_selected:
                    health_selected.discard(loc)
            with cols[1]:
                st.markdown(status_row_html(r), unsafe_allow_html=True)
            with cols[2]:
                if st.button(
                    "↻",
                    key=f"hrec-{loc}",
                    help="Re-crawl URL này",
                    use_container_width=True,
                ):
                    with st.spinner(f"Re-crawl {loc[:50]}..."):
                        res = trigger_ingest(urls=[{
                            "location": loc, "topic": r["topic"],
                            "title": r["title"], "source": "website",
                        }])
                    if res:
                        st.success(f"{res['chunks_indexed']} chunks")
        else:
            # OK / UNKNOWN: chỉ hiển thị, không cần action
            st.markdown(status_row_html(r), unsafe_allow_html=True)


# ─── Page: Sessions ─────────────────────────────────────────────────────────
def page_sessions():
    render_page_header(
        "Sessions",
        "Cuộc trò chuyện đã lưu trong DB",
    )

    sessions = get_sessions()
    if not sessions:
        st.info("Chưa có session nào.")
        return

    st.caption(f"{len(sessions)} sessions")

    for s in sessions:
        cols = st.columns([4, 2, 2, 1])
        cols[0].markdown(f"**{s['title']}**")
        cols[1].caption(f"{s['message_count']} tin nhắn")
        cols[2].caption(s["id"][:8])
        with cols[3]:
            if st.button("Xoá", key=f"delsess-{s['id']}"):
                if delete_session(s["id"]):
                    st.rerun()


# ─── Page: Maintenance ──────────────────────────────────────────────────────
def page_maintenance():
    render_page_header(
        "Maintenance",
        "Bảo trì cache, BM25 index, reset hệ thống",
    )

    cols = st.columns(2, gap="medium")

    with cols[0]:
        st.markdown('<div class="card-title">Answer Cache</div>', unsafe_allow_html=True)
        st.caption("Xoá cache câu trả lời. Lần hỏi tiếp theo sẽ gọi LLM lại.")
        if st.button("Clear cache", use_container_width=True):
            if clear_cache():
                st.success("Đã xoá cache")

    with cols[1]:
        st.markdown('<div class="card-title">BM25 Index</div>', unsafe_allow_html=True)
        st.caption("Rebuild BM25 từ Chroma. Chạy khi nghi ngờ index lệch.")
        if st.button("Rebuild BM25", use_container_width=True):
            with st.spinner("Đang rebuild..."):
                res = rebuild_bm25()
            if res:
                st.success(f"Rebuild xong với {res['chunks_indexed']:,} chunks")

    st.markdown("&nbsp;")
    st.markdown('<div class="card-title">Reset toàn bộ Knowledge Base</div>', unsafe_allow_html=True)
    st.caption("Xoá toàn bộ Chroma collection và re-ingest từ tất cả sources/*.json. Mất 5-10 phút.")
    confirm = st.checkbox("Tôi hiểu thao tác này không thể hoàn tác", key="confirm_reset")
    if st.button("Reset & Re-ingest All", disabled=not confirm, type="primary"):
        with st.spinner("Đang reset + crawl + re-embed (5-10 phút)..."):
            topics = get_sources()
            if topics:
                first = topics[0]["topic"]
                trigger_ingest(topic=first, reset=True)
                for t in topics[1:]:
                    if t["count"] > 0:
                        trigger_ingest(topic=t["topic"])
        st.success("Reset hoàn tất")


# ─── Render selected page ───────────────────────────────────────────────────
PAGE_RENDERERS = {
    "Dashboard": page_dashboard,
    "Sources": page_sources,
    "Health Check": page_health,
    "Sessions": page_sessions,
    "Maintenance": page_maintenance,
}

if not backend_ok:
    st.error(f"Không kết nối được backend tại {api_url()}. Khởi động backend rồi refresh.")
else:
    PAGE_RENDERERS[page]()
