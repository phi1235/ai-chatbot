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


def get_freshness(
    status: str | None = None,
    topic: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if topic:
            params["topic"] = topic
        r = http().get(f"{api_url()}/admin/freshness", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được freshness data: {exc}")
        return None


def batch_recrawl(urls: list[str]) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/freshness/recrawl",
            json={"urls": urls},
            timeout=httpx.Timeout(600.0, connect=5.0, read=600.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Batch recrawl thất bại: {exc}")
        return None


def get_scheduler_status() -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/scheduler/status")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được trạng thái scheduler: {exc}")
        return None


def update_scheduler_config(enabled: bool, interval_seconds: int) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/scheduler/config",
            json={"enabled": enabled, "interval_seconds": interval_seconds},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cập nhật scheduler thất bại: {exc}")
        return None


def run_scheduler_now() -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/scheduler/run-now",
            timeout=httpx.Timeout(300.0, connect=5.0, read=300.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Chạy scheduler thất bại: {exc}")
        return None


def get_feedback_list(
    feedback_type: str | None = None,
    reviewed: bool | None = None,
    review_status: str | None = None,
    root_cause: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if feedback_type:
            params["feedback_type"] = feedback_type
        if reviewed is not None:
            params["reviewed"] = str(reviewed).lower()
        if review_status:
            params["review_status"] = review_status
        if root_cause:
            params["root_cause"] = root_cause
        r = http().get(f"{api_url()}/admin/feedback", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được feedback: {exc}")
        return None


def review_feedback_item(
    feedback_id: int, review_note: str, review_status: str, root_cause: str | None = None,
) -> dict | None:
    try:
        body: dict = {"review_note": review_note, "review_status": review_status}
        if root_cause:
            body["root_cause"] = root_cause
        r = http().post(
            f"{api_url()}/admin/feedback/{feedback_id}/review",
            json=body,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Review thất bại: {exc}")
        return None


def create_feedback_action_item(feedback_id: int) -> dict | None:
    try:
        r = http().post(f"{api_url()}/admin/feedback/{feedback_id}/action-item")
        if r.status_code == 409:
            st.warning(r.json().get("detail", "Active action item already exists for this feedback."))
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Create action item failed: {exc}")
        return None


def get_feedback_actions(
    status: str | None = None,
    suggested_action: str | None = None,
    root_cause: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if suggested_action:
            params["suggested_action"] = suggested_action
        if root_cause:
            params["root_cause"] = root_cause
        r = http().get(f"{api_url()}/admin/feedback-actions", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch action items: {exc}")
        return None


def update_feedback_action_status(
    action_id: int, status: str, owner_note: str | None = None
) -> dict | None:
    try:
        body: dict = {"status": status}
        if owner_note:
            body["owner_note"] = owner_note
        r = http().post(
            f"{api_url()}/admin/feedback-actions/{action_id}/status",
            json=body,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Update status failed: {exc}")
        return None


def execute_feedback_action(action_id: int) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/feedback-actions/{action_id}/execute",
            timeout=httpx.Timeout(120.0, connect=5.0, read=120.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Execute failed: {exc}")
        return None


def get_coverage_gaps(
    status: str | None = None,
    detected_topic: str | None = None,
    resolution: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if detected_topic:
            params["detected_topic"] = detected_topic
        if resolution:
            params["resolution"] = resolution
        r = http().get(f"{api_url()}/admin/coverage-gaps", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được coverage gaps: {exc}")
        return None


def review_coverage_gap(gap_id: int, status: str, resolution: str | None, review_note: str) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/coverage-gaps/{gap_id}/review",
            json={"status": status, "resolution": resolution, "review_note": review_note},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Review thất bại: {exc}")
        return None


def action_coverage_gap(
    gap_id: int, resolution: str, action_payload: dict, review_note: str = "",
) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/coverage-gaps/{gap_id}/action",
            json={
                "resolution": resolution,
                "action_payload": action_payload,
                "review_note": review_note or None,
            },
            timeout=httpx.Timeout(600.0, connect=5.0, read=600.0),
        )
        if r.status_code == 409:
            st.warning(r.json().get("detail", "URL đã tồn tại."))
            return None
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:
            pass
        st.error(f"Action thất bại: {detail or exc}")
        return None
    except Exception as exc:
        st.error(f"Action thất bại: {exc}")
        return None


def get_coverage_gaps_summary() -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/coverage-gaps/summary")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được summary: {exc}")
        return None


def get_coverage_gap_clusters(
    detected_topic: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if detected_topic:
            params["detected_topic"] = detected_topic
        if status:
            params["status"] = status
        r = http().get(f"{api_url()}/admin/coverage-gap-clusters", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được clusters: {exc}")
        return None


def get_coverage_gap_cluster_detail(cluster_key: str, limit: int = 50) -> dict | None:
    try:
        r = http().get(
            f"{api_url()}/admin/coverage-gap-clusters/{cluster_key}",
            params={"limit": limit},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được cluster detail: {exc}")
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
            "Freshness Center",
            "Coverage Gaps",
            "Feedback",
            "Action Queue",
            "Eval Cases",
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
    topic = r.get("topic") or "-"
    location = r.get("location") or r.get("url") or ""
    detail = r.get("detail") or r.get("notes") or r.get("error_message") or ""
    return (
        f'<div class="status-row {cls}">'
        f'  <span class="badge">{r["status"]}</span>'
        f'  <span class="topic">[{topic}]</span>'
        f'  <span class="url">{location[:90]}</span>'
        f'  <span class="detail">{detail}</span>'
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


# ─── Page: Freshness Center ────────────────────────────────────────────────
def page_freshness_center():
    render_page_header(
        "Freshness Center",
        "Theo dõi độ tươi của sources, scheduler và re-crawl có chọn lọc",
    )

    scheduler_payload = get_scheduler_status() or {}
    scheduler_alert_state = scheduler_payload.get("alert_state") or "OK"
    scheduler_last_summary = scheduler_payload.get("last_summary") or {}
    scheduler_last_run = scheduler_payload.get("last_run_time")
    scheduler_next_run = scheduler_payload.get("next_run_time")

    with st.expander("Scheduler & Alerts", expanded=True):
        current_enabled = bool(scheduler_payload.get("enabled", False))
        current_interval = int(scheduler_payload.get("interval_seconds") or 3600)
        interval_options = [300, 900, 1800, 3600, 7200, 21600, 43200, 86400]

        sched_cols = st.columns([1.2, 1.3, 1.3, 2.2])
        with sched_cols[0]:
            enabled_choice = st.toggle("Bật scheduler", value=current_enabled, key="scheduler_enabled_toggle")
        with sched_cols[1]:
            interval_choice = st.selectbox(
                "Chu kỳ",
                options=interval_options,
                index=interval_options.index(current_interval) if current_interval in interval_options else 3,
                format_func=lambda v: {
                    300: "5 phút",
                    900: "15 phút",
                    1800: "30 phút",
                    3600: "1 giờ",
                    7200: "2 giờ",
                    21600: "6 giờ",
                    43200: "12 giờ",
                    86400: "24 giờ",
                }[v],
                key="scheduler_interval_select",
            )
        with sched_cols[2]:
            if st.button("Lưu scheduler", use_container_width=True):
                updated = update_scheduler_config(enabled_choice, interval_choice)
                if updated:
                    st.success("Đã cập nhật scheduler.")
                    st.rerun()
        with sched_cols[3]:
            if st.button("Chạy ngay", type="primary", use_container_width=True):
                with st.spinner("Đang chạy scheduler..."):
                    run_now_result = run_scheduler_now()
                if run_now_result:
                    st.success(
                        f"Đã chạy xong. {run_now_result.get('snapshot_saved', 0)} records saved. "
                        f"Alert: {run_now_result.get('alert_state', 'OK')}"
                    )
                    st.session_state.pop("freshness_records_cache", None)
                    st.rerun()

        info_cols = st.columns(4)
        info_cols[0].metric("Scheduler", "ON" if current_enabled else "OFF")
        info_cols[1].metric("Alert", scheduler_alert_state)
        info_cols[2].metric(
            "Last run",
            datetime.fromtimestamp(float(scheduler_last_run)).strftime("%Y-%m-%d %H:%M:%S")
            if scheduler_last_run else "-",
        )
        info_cols[3].metric(
            "Next run",
            datetime.fromtimestamp(float(scheduler_next_run)).strftime("%Y-%m-%d %H:%M:%S")
            if scheduler_next_run else "-",
        )

        if scheduler_last_summary:
            summary_cols = st.columns(6)
            summary_cols[0].metric("Total", scheduler_last_summary.get("total", 0))
            summary_cols[1].metric("OK", scheduler_last_summary.get("ok", 0))
            summary_cols[2].metric("Stale", scheduler_last_summary.get("stale", 0))
            summary_cols[3].metric("Dead", scheduler_last_summary.get("dead", 0))
            summary_cols[4].metric("Redirect", scheduler_last_summary.get("redirect", 0))
            summary_cols[5].metric("Error", scheduler_last_summary.get("unknown", 0))

    topics = get_sources()
    topic_names = ["(tất cả)"] + [t["topic"] for t in topics]
    status_options = ["(tất cả)", "OK", "STALE", "DEAD", "REDIRECT", "ERROR"]

    fcols = st.columns([2, 2, 1, 1])
    with fcols[0]:
        selected_topic = st.selectbox("Topic", topic_names, key="freshness_topic_filter")
    with fcols[1]:
        selected_status = st.selectbox("Status", status_options, key="freshness_status_filter")
    with fcols[2]:
        limit = st.selectbox("Số dòng", [25, 50, 100, 200], index=1, key="freshness_limit")
    with fcols[3]:
        refresh_clicked = st.button("Làm mới", use_container_width=True)

    action_cols = st.columns([1.2, 1.2, 3])
    with action_cols[0]:
        if st.button("Chạy health-check", type="primary", use_container_width=True):
            topic_arg = None if selected_topic == "(tất cả)" else selected_topic
            with st.spinner("Đang chạy health-check..."):
                health_result = run_health(topic_arg)
            if health_result:
                saved = health_result.get("snapshot_saved", 0)
                st.success(f"Health-check xong. Đã lưu {saved} records.")
                st.session_state.pop("freshness_records_cache", None)
    with action_cols[1]:
        clear_selection = st.button("Bỏ chọn", use_container_width=True)
    if refresh_clicked:
        st.session_state.pop("freshness_records_cache", None)

    topic_arg = None if selected_topic == "(tất cả)" else selected_topic
    status_arg = None if selected_status == "(tất cả)" else selected_status
    cache_key = f"{topic_arg}|{status_arg}|{limit}"

    if st.session_state.get("freshness_records_cache_key") != cache_key:
        st.session_state.pop("freshness_records_cache", None)
        st.session_state["freshness_records_cache_key"] = cache_key

    if "freshness_records_cache" not in st.session_state:
        st.session_state["freshness_records_cache"] = get_freshness(
            status=status_arg,
            topic=topic_arg,
            limit=limit,
            offset=0,
        )

    payload = st.session_state.get("freshness_records_cache") or {}
    records = payload.get("records", [])

    if not records:
        st.info("Chưa có freshness records với bộ lọc hiện tại.")
        return

    sel_key = "freshness_selected_urls"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = set()
    selected_urls: set[str] = set(st.session_state[sel_key])

    if clear_selection:
        st.session_state[sel_key] = set()
        selected_urls = set()

    summary_cols = st.columns(4)
    summary_cols[0].metric("Records", len(records))
    summary_cols[1].metric("Selected", len(selected_urls))
    summary_cols[2].metric("Topic", topic_arg or "All")
    summary_cols[3].metric("Status", status_arg or "All")

    toolbar_cols = st.columns([1.4, 1.4, 2.2, 3])
    with toolbar_cols[0]:
        if st.button("Chọn lỗi/stale", use_container_width=True):
            st.session_state[sel_key] = {
                r["url"]
                for r in records
                if r.get("status") in {"STALE", "DEAD", "ERROR", "REDIRECT"} and r.get("url")
            }
            st.rerun()
    with toolbar_cols[1]:
        if st.button("Chọn tất cả", use_container_width=True):
            st.session_state[sel_key] = {r["url"] for r in records if r.get("url")}
            st.rerun()
    with toolbar_cols[2]:
        if st.button(
            f"Re-crawl đã chọn ({len(selected_urls)})",
            type="primary",
            use_container_width=True,
            disabled=len(selected_urls) == 0,
        ):
            with st.spinner(f"Đang re-crawl {len(selected_urls)} URLs..."):
                result = batch_recrawl(sorted(selected_urls))
            if result:
                st.success(
                    f"Re-crawl xong: {result['documents_crawled']} docs, "
                    f"{result['chunks_indexed']} chunks."
                )
                missing_count = result.get("missing_count", 0)
                if missing_count:
                    st.warning(f"Có {missing_count} URLs không còn trong sources.")
                st.session_state[sel_key] = set()
                st.session_state.pop("freshness_records_cache", None)

    table_rows: list[dict] = []
    for row in records:
        url = row.get("url", "")
        checked = url in selected_urls
        checked_at = row.get("checked_at")
        checked_text = ""
        if checked_at:
            try:
                checked_text = datetime.fromtimestamp(float(checked_at)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                checked_text = str(checked_at)
        table_rows.append(
            {
                "Chọn": checked,
                "Status": row.get("status", ""),
                "Topic": row.get("topic") or "",
                "URL": url,
                "HTTP": row.get("http_status") or "",
                "Checked at": checked_text,
                "Notes": row.get("error_message") or row.get("notes") or "",
                "_url": url,
            }
        )

    edited = st.data_editor(
        table_rows,
        use_container_width=True,
        hide_index=True,
        key="freshness_table_editor",
        disabled=["Status", "Topic", "URL", "HTTP", "Checked at", "Notes", "_url"],
        column_config={
            "Chọn": st.column_config.CheckboxColumn("Chọn"),
            "Status": st.column_config.TextColumn("Status"),
            "Topic": st.column_config.TextColumn("Topic"),
            "URL": st.column_config.TextColumn("URL", width="large"),
            "HTTP": st.column_config.TextColumn("HTTP"),
            "Checked at": st.column_config.TextColumn("Checked at", width="medium"),
            "Notes": st.column_config.TextColumn("Notes", width="large"),
            "_url": None,
        },
    )

    updated_selection = {
        row.get("_url", "")
        for row in edited
        if row.get("Chọn") and row.get("_url")
    }
    if updated_selection != set(st.session_state[sel_key]):
        st.session_state[sel_key] = updated_selection

    with st.expander("Chi tiết records", expanded=False):
        for row in records:
            st.markdown(status_row_html(row), unsafe_allow_html=True)


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
    st.markdown(
        '<div class="card-title">Reset toàn bộ Knowledge Base</div>',
        unsafe_allow_html=True,
    )
    st.info(
        "Reset KB là thao tác **destructive** — không có trong UI để tránh "
        "click nhầm hoặc bị xâm nhập gây mất data.\n\n"
        "Chỉ thực hiện qua CLI từ server admin:\n"
        "```bash\n"
        "python ingest.py --reset\n"
        "```\n"
        "Hoặc reset 1 topic cụ thể:\n"
        "```bash\n"
        "python ingest.py --topic <ten-topic> --reset\n"
        "```"
    )


# ─── Cluster sub-view for Coverage Gaps ──────────────────────────────────────
def _render_cluster_view(raw_items: list[dict]):
    """Render the cluster-first view inside Coverage Gaps page."""

    # Filters for clusters
    all_topics = sorted({it.get("detected_topic") or "" for it in raw_items} - {""})
    fcols = st.columns([1, 1, 1, 1])
    with fcols[0]:
        cl_topic = st.selectbox(
            "Topic",
            options=["Tất cả"] + all_topics,
            key="cl_filter_topic",
            label_visibility="collapsed",
        )
    with fcols[1]:
        cl_status = st.selectbox(
            "Status",
            options=["Tất cả", "new", "reviewed", "actioned", "ignored"],
            key="cl_filter_status",
            label_visibility="collapsed",
        )
    with fcols[2]:
        cl_limit = st.selectbox(
            "Số lượng",
            options=[20, 50, 100],
            index=1,
            key="cl_filter_limit",
            label_visibility="collapsed",
        )
    with fcols[3]:
        if st.button("Làm mới", use_container_width=True, key="cl_refresh"):
            st.rerun()

    topic_val = cl_topic if cl_topic != "Tất cả" else None
    status_val = cl_status if cl_status != "Tất cả" else None

    cluster_data = get_coverage_gap_clusters(
        detected_topic=topic_val,
        status=status_val,
        limit=cl_limit,
    )
    if not cluster_data or not cluster_data.get("clusters"):
        st.info("Không có cluster nào phù hợp bộ lọc.")
        return

    clusters = cluster_data["clusters"]
    st.caption(f"Hiển thị {len(clusters)} clusters")

    for cl in clusters:
        ck = cl["cluster_key"]
        count = cl["count"]
        topic_text = cl.get("detected_topic") or "-"
        rep_q = cl.get("representative_question") or ck
        latest_ts = cl.get("latest_created_at")
        latest_str = datetime.fromtimestamp(latest_ts).strftime("%d/%m %H:%M") if latest_ts else "-"

        statuses = cl.get("statuses", {})
        status_parts = [f"{s}: {c}" for s, c in statuses.items()]
        status_text = ", ".join(status_parts) if status_parts else "-"

        resolutions = cl.get("resolutions", {})
        res_parts = [f"{r}: {c}" for r, c in resolutions.items()]
        res_text = ", ".join(res_parts) if res_parts else "-"

        label = f"[x{count}] {rep_q[:80]}"
        with st.expander(label):
            info_html = (
                f'<div style="display:flex; flex-wrap:wrap; gap:0.8rem; margin-bottom:0.5rem; font-size:0.82rem;">'
                f'<span><b>Topic:</b> {topic_text}</span>'
                f'<span><b>Occurrences:</b> {count}</span>'
                f'<span><b>Latest:</b> {latest_str}</span>'
                f'</div>'
                f'<div style="font-size:0.82rem; margin-bottom:0.3rem;">'
                f'<b>Statuses:</b> {status_text}</div>'
                f'<div style="font-size:0.82rem; margin-bottom:0.5rem;">'
                f'<b>Resolutions:</b> {res_text}</div>'
            )
            st.markdown(info_html, unsafe_allow_html=True)

            st.markdown(f"**Representative question:** {rep_q}")

            # ── Recommendation section ──
            rec = cl.get("recommendation")
            if rec:
                r_action = rec.get("recommended_action", "review_only")
                r_reason = rec.get("recommendation_reason", "")
                r_topic = rec.get("candidate_topic", "")
                r_query = rec.get("suggested_search_query", "")
                r_priority = rec.get("priority", "low")
                r_signals = rec.get("signals", [])

                action_colors = {
                    "add_source": ("var(--warn)", "#fef3c7"),
                    "recrawl": ("var(--accent)", "var(--accent-soft)"),
                    "review_only": ("var(--text-muted)", "#f3f4f6"),
                }
                a_color, a_bg = action_colors.get(r_action, ("var(--text-muted)", "#f3f4f6"))

                priority_labels = {
                    "high": ("HIGH", "var(--danger)", "#fee2e2"),
                    "medium": ("MED", "var(--warn)", "#fef3c7"),
                    "low": ("LOW", "var(--text-subtle)", "#f3f4f6"),
                }
                p_label, p_color, p_bg = priority_labels.get(
                    r_priority, ("LOW", "var(--text-subtle)", "#f3f4f6")
                )

                rec_html = (
                    f'<div style="border:1px solid var(--border); border-radius:8px; '
                    f'padding:0.8rem 1rem; margin:0.5rem 0 0.8rem; background:var(--surface);">'
                    f'<div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.4rem;">'
                    f'<span style="font-weight:600; font-size:0.82rem; color:{a_color}; '
                    f'background:{a_bg}; padding:0.15rem 0.5rem; border-radius:4px;">'
                    f'{r_action.upper().replace("_", " ")}</span>'
                    f'<span style="font-weight:600; font-size:0.68rem; color:{p_color}; '
                    f'background:{p_bg}; padding:0.1rem 0.4rem; border-radius:3px;">'
                    f'{p_label}</span>'
                    f'<span style="color:var(--text-subtle); font-size:0.72rem;">Recommendation</span>'
                    f'</div>'
                    f'<div style="font-size:0.82rem; color:var(--text); margin-bottom:0.3rem;">{r_reason}</div>'
                )
                if r_topic:
                    rec_html += (
                        f'<div style="font-size:0.78rem; color:var(--text-muted);">'
                        f'<b>Topic:</b> {r_topic}</div>'
                    )
                if r_query:
                    rec_html += (
                        f'<div style="font-size:0.78rem; color:var(--text-muted);">'
                        f'<b>Search query:</b> <code>{r_query}</code></div>'
                    )
                if r_signals:
                    sig_str = ", ".join(r_signals)
                    rec_html += (
                        f'<div style="font-size:0.72rem; color:var(--text-subtle); margin-top:0.2rem;">'
                        f'Signals: {sig_str}</div>'
                    )
                rec_html += '</div>'
                st.markdown(rec_html, unsafe_allow_html=True)

            # Drill-down: show gaps in this cluster
            if st.button("Xem gaps trong cluster", key=f"cl-drill-{ck}"):
                st.session_state[f"cl_expand_{ck}"] = True

            if st.session_state.get(f"cl_expand_{ck}"):
                detail = get_coverage_gap_cluster_detail(ck, limit=20)
                if detail and detail.get("gaps"):
                    for gap in detail["gaps"]:
                        gap_id = gap["id"]
                        gap_status = gap["status"]
                        created = datetime.fromtimestamp(gap["created_at"]).strftime("%d/%m %H:%M")
                        status_color = {
                            "new": "var(--warn)",
                            "reviewed": "var(--accent)",
                            "actioned": "var(--ok)",
                            "ignored": "var(--text-subtle)",
                        }.get(gap_status, "var(--text-muted)")

                        gap_html = (
                            f'<div style="padding:0.4rem 0; border-bottom:1px solid var(--border); font-size:0.82rem;">'
                            f'<span style="font-weight:600; padding:0.1rem 0.4rem; border-radius:3px; '
                            f'background:{status_color}15; color:{status_color}; font-size:0.72rem;">'
                            f'{gap_status.upper()}</span> '
                            f'<span style="color:var(--text-subtle)">#{gap_id} {created}</span> '
                            f'{gap["question"][:100]}'
                            f'</div>'
                        )
                        st.markdown(gap_html, unsafe_allow_html=True)
                else:
                    st.caption("Không tìm thấy gaps.")


# ─── Page: Coverage Gaps ─────────────────────────────────────────────────────
def page_coverage_gaps():
    render_page_header(
        "Coverage Gaps",
        "Phát hiện lỗ hổng knowledge base từ traffic chat",
    )

    data = get_coverage_gaps(limit=200)
    if not data:
        st.info("Chưa có coverage gap nào.")
        return

    summary = data.get("summary", {})
    items = data.get("items", [])

    # Summary metrics
    cols = st.columns(5)
    cols[0].metric("Tổng gaps", summary.get("total", 0))
    cols[1].metric("New", summary.get("total_new", 0))
    cols[2].metric("Reviewed", summary.get("total_reviewed", 0))
    cols[3].metric("Actioned", summary.get("total_actioned", 0))
    cols[4].metric("Ignored", summary.get("total_ignored", 0))

    # Topic breakdown
    by_topic = summary.get("by_topic", {})
    by_resolution = summary.get("by_resolution", {})
    if by_topic or by_resolution:
        st.markdown("&nbsp;")
        bcols = st.columns(2, gap="medium")
        with bcols[0]:
            if by_topic:
                st.markdown('<div class="card-title">Theo topic</div>', unsafe_allow_html=True)
                for topic, cnt in by_topic.items():
                    st.text(f"  {topic}: {cnt}")
        with bcols[1]:
            if by_resolution:
                st.markdown('<div class="card-title">Theo resolution</div>', unsafe_allow_html=True)
                for res, cnt in by_resolution.items():
                    st.text(f"  {res}: {cnt}")

    st.markdown("&nbsp;")

    # View toggle: Clusters vs Raw Gaps
    view_mode = st.radio(
        "Chế độ xem",
        options=["Clusters", "Raw Gaps"],
        horizontal=True,
        key="cg_view_mode",
        label_visibility="collapsed",
    )

    if view_mode == "Clusters":
        _render_cluster_view(items)
        return

    # Filters
    fcols = st.columns([1, 1, 1, 1, 1])
    with fcols[0]:
        filter_status = st.selectbox(
            "Status",
            options=["Tất cả", "new", "reviewed", "actioned", "ignored"],
            key="cg_filter_status",
            label_visibility="collapsed",
        )
    with fcols[1]:
        # Collect available topics from items
        all_topics = sorted({it.get("detected_topic") or "" for it in items} - {""})
        topic_options = ["Tất cả"] + all_topics
        filter_topic = st.selectbox(
            "Topic",
            options=topic_options,
            key="cg_filter_topic",
            label_visibility="collapsed",
        )
    with fcols[2]:
        resolution_options = [
            "Tất cả", "add_source", "recrawl", "out_of_scope",
            "duplicate", "retrieval_tuning", "prompt_tuning",
        ]
        filter_resolution = st.selectbox(
            "Resolution",
            options=resolution_options,
            key="cg_filter_resolution",
            label_visibility="collapsed",
        )
    with fcols[3]:
        filter_limit = st.selectbox(
            "Số lượng",
            options=[20, 50, 100],
            index=1,
            key="cg_filter_limit",
            label_visibility="collapsed",
        )
    with fcols[4]:
        if st.button("Làm mới", use_container_width=True, key="cg_refresh"):
            st.rerun()

    # Re-fetch with filters
    ft_status = filter_status if filter_status != "Tất cả" else None
    ft_topic = filter_topic if filter_topic != "Tất cả" else None
    ft_res = filter_resolution if filter_resolution != "Tất cả" else None
    if ft_status or ft_topic or ft_res or filter_limit != 50:
        data = get_coverage_gaps(
            status=ft_status,
            detected_topic=ft_topic,
            resolution=ft_res,
            limit=filter_limit,
        )
        if not data:
            return
        items = data.get("items", [])

    if not items:
        st.info("Không có coverage gap nào phù hợp bộ lọc.")
        return

    st.caption(f"Hiển thị {len(items)} gaps")

    # Render gap list
    for item in items:
        gap_id = item["id"]
        gap_status = item["status"]
        created = datetime.fromtimestamp(item["created_at"]).strftime("%d/%m %H:%M")
        signals = item.get("gap_signals", [])
        signals_text = ", ".join(signals) if signals else "-"
        topic_text = item.get("detected_topic") or "-"

        status_color = {
            "new": "var(--warn)",
            "reviewed": "var(--accent)",
            "actioned": "var(--ok)",
            "ignored": "var(--text-subtle)",
        }.get(gap_status, "var(--text-muted)")

        header_html = (
            f'<div style="display:flex; align-items:center; gap:0.6rem; margin-bottom:0.3rem;">'
            f'<span style="font-weight:600; font-size:0.75rem; padding:0.1rem 0.5rem; '
            f'border-radius:4px; background:{status_color}15; color:{status_color}">'
            f'{gap_status.upper()}</span>'
            f'<span style="font-size:0.75rem; color:var(--text-subtle)">[{topic_text}]</span>'
            f'<span style="font-size:0.75rem; color:var(--text-subtle)">ret={item["retrieval_count"]}</span>'
            f'<span style="font-size:0.75rem; color:var(--text-subtle)">{created}</span>'
            f'<span style="font-size:0.75rem; color:var(--text-subtle)">#{gap_id}</span>'
            f'</div>'
        )

        expander_label = f"[{gap_status.upper()}] {item['question'][:80]}"
        with st.expander(expander_label):
            st.markdown(header_html, unsafe_allow_html=True)

            st.markdown("**Câu hỏi:**")
            st.text(item["question"])

            if item.get("rewritten_query"):
                st.markdown(f"**Query rewritten:** {item['rewritten_query']}")

            st.markdown(f"**Signals:** {signals_text}")
            st.markdown(f"**Retrieval count:** {item['retrieval_count']}")

            if item.get("answer_excerpt"):
                st.markdown("**Answer excerpt:**")
                st.text(item["answer_excerpt"][:300] + ("..." if len(item["answer_excerpt"]) > 300 else ""))

            citations = item.get("citations_snapshot", [])
            if citations:
                st.markdown("**Citations:**")
                for c in citations[:5]:
                    score_text = f" (score: {c['score']:.2f})" if c.get("score") is not None else ""
                    st.text(f"  - {c.get('title', '-')}{score_text}")

            if item.get("session_id"):
                st.caption(f"Session: {item['session_id'][:8]}")

            if item.get("resolution"):
                st.success(
                    f"Resolution: {item['resolution']}"
                    + (f" — {item['review_note']}" if item.get("review_note") else "")
                )

            # Action history for actioned gaps
            if gap_status == "actioned" and item.get("action_payload"):
                ap = item["action_payload"]
                actioned_time = ""
                if item.get("actioned_at"):
                    actioned_time = datetime.fromtimestamp(item["actioned_at"]).strftime("%d/%m %H:%M")
                action_res = ap.get("result", {})
                st.markdown(
                    f"**Action:** {item.get('resolution', '-')} · {actioned_time}"
                )
                if item["resolution"] == "add_source":
                    st.text(f"  URL: {ap.get('url', '-')}")
                    st.text(f"  Topic: {ap.get('topic', '-')}")
                    if ap.get("title"):
                        st.text(f"  Title: {ap['title']}")
                elif item["resolution"] == "recrawl":
                    if ap.get("topic"):
                        st.text(f"  Topic: {ap['topic']}")
                    if ap.get("urls"):
                        st.text(f"  URLs: {len(ap['urls'])} target(s)")
                    if action_res.get("documents_crawled") is not None:
                        st.text(
                            f"  Result: {action_res.get('documents_crawled', 0)} docs, "
                            f"{action_res.get('chunks_indexed', 0)} chunks"
                        )
            elif gap_status != "new" and item.get("review_note"):
                st.info(f"Note: {item['review_note']}")

            # Review + Action forms for new/reviewed gaps
            if gap_status in ("new", "reviewed"):
                st.markdown("---")
                review_tab, action_tab = st.tabs(["Review", "Action"])

                with review_tab, st.form(key=f"cg-review-form-{gap_id}"):
                    note_input = st.text_input(
                        "Review note",
                        placeholder="Ghi chú ngắn (optional)",
                        key=f"cg-note-{gap_id}",
                    )
                    rcols = st.columns(2)
                    with rcols[0]:
                        status_input = st.selectbox(
                            "Status",
                            options=["reviewed", "actioned", "ignored"],
                            key=f"cg-status-{gap_id}",
                        )
                    with rcols[1]:
                        resolution_input = st.selectbox(
                            "Resolution",
                            options=[
                                "(none)", "add_source", "recrawl", "out_of_scope",
                                "duplicate", "retrieval_tuning", "prompt_tuning",
                            ],
                            key=f"cg-resolution-{gap_id}",
                        )
                    if st.form_submit_button("Đánh dấu", type="primary"):
                        res_value = resolution_input if resolution_input != "(none)" else None
                        result = review_coverage_gap(gap_id, status_input, res_value, note_input)
                        if result:
                            st.success("Đã cập nhật!")
                            st.rerun()

                with action_tab:
                    action_type = st.selectbox(
                        "Action",
                        options=["add_source", "recrawl"],
                        key=f"cg-action-type-{gap_id}",
                    )

                    if action_type == "add_source":
                        with st.form(key=f"cg-action-addsrc-{gap_id}"):
                            default_topic = item.get("detected_topic") or ""
                            a_topic = st.text_input(
                                "Topic",
                                value=default_topic,
                                placeholder="vd: kubernetes",
                                key=f"cg-a-topic-{gap_id}",
                            )
                            a_url = st.text_input(
                                "URL",
                                placeholder="https://docs.example.com/...",
                                key=f"cg-a-url-{gap_id}",
                            )
                            a_title = st.text_input(
                                "Title (optional)",
                                placeholder="Tiêu đề nguồn",
                                key=f"cg-a-title-{gap_id}",
                            )
                            a_note = st.text_input(
                                "Note (optional)",
                                placeholder="Ghi chú",
                                key=f"cg-a-note-{gap_id}",
                            )
                            if st.form_submit_button("Add source", type="primary"):
                                if not a_url.strip():
                                    st.error("Cần nhập URL.")
                                elif not a_topic.strip():
                                    st.error("Cần nhập topic.")
                                else:
                                    with st.spinner("Đang thêm source..."):
                                        result = action_coverage_gap(
                                            gap_id,
                                            "add_source",
                                            {"topic": a_topic.strip(), "url": a_url.strip(), "title": a_title.strip()},
                                            a_note.strip(),
                                        )
                                    if result:
                                        st.success("Đã thêm source và đánh dấu actioned!")
                                        st.rerun()

                    elif action_type == "recrawl":
                        with st.form(key=f"cg-action-recrawl-{gap_id}"):
                            default_topic = item.get("detected_topic") or ""
                            r_topic = st.text_input(
                                "Recrawl topic",
                                value=default_topic,
                                placeholder="Topic cần recrawl (recrawl toàn bộ topic)",
                                key=f"cg-r-topic-{gap_id}",
                            )
                            r_urls = st.text_area(
                                "Hoặc URLs cụ thể (mỗi dòng 1 URL)",
                                placeholder="https://docs.example.com/page1\nhttps://docs.example.com/page2",
                                height=80,
                                key=f"cg-r-urls-{gap_id}",
                            )
                            r_note = st.text_input(
                                "Note (optional)",
                                placeholder="Ghi chú",
                                key=f"cg-r-note-{gap_id}",
                            )
                            if st.form_submit_button("Recrawl", type="primary"):
                                url_list = [
                                    u.strip() for u in (r_urls or "").splitlines()
                                    if u.strip() and not u.strip().startswith("#")
                                ]
                                if not r_topic.strip() and not url_list:
                                    st.error("Cần nhập topic hoặc ít nhất 1 URL.")
                                else:
                                    payload: dict = {}
                                    if r_topic.strip():
                                        payload["topic"] = r_topic.strip()
                                    if url_list:
                                        payload["urls"] = url_list
                                    with st.spinner("Đang recrawl..."):
                                        result = action_coverage_gap(
                                            gap_id, "recrawl", payload, r_note.strip(),
                                        )
                                    if result:
                                        ar = result.get("action_result", {})
                                        st.success(
                                            f"Recrawl xong: {ar.get('documents_crawled', 0)} docs, "
                                            f"{ar.get('chunks_indexed', 0)} chunks. Gap đã actioned!"
                                        )
                                        st.rerun()


# ─── Page: Feedback ─────────────────────────────────────────────────────────
_ROOT_CAUSE_OPTIONS = [
    "retrieval_miss",
    "insufficient_context",
    "bad_citation_fit",
    "wrong_answer_from_context",
    "hallucination",
    "stale_source_mix",
    "true_coverage_gap",
    "other",
]

_ROOT_CAUSE_LABELS = {
    "retrieval_miss": "Retrieval miss",
    "insufficient_context": "Insufficient context",
    "bad_citation_fit": "Bad citation fit",
    "wrong_answer_from_context": "Wrong answer from context",
    "hallucination": "Hallucination",
    "stale_source_mix": "Stale source mix",
    "true_coverage_gap": "True coverage gap",
    "other": "Other",
}


def page_feedback():
    render_page_header(
        "Feedback Review",
        "Review, diagnose, and classify user feedback",
    )

    data = get_feedback_list(limit=200)
    if not data:
        st.info("No feedback yet.")
        return

    summary = data.get("summary", {})
    items = data.get("items", [])

    # ─── Summary metrics ────────────────────────────────────────────────
    cols = st.columns(4)
    cols[0].metric("Total feedback", summary.get("total", 0))
    cols[1].metric("Down (pending)", summary.get("down_pending", 0))
    cols[2].metric("Reviewed", summary.get("reviewed", 0))
    cols[3].metric("Up / Down", f"{summary.get('total_up', 0)} / {summary.get('total_down', 0)}")

    # ─── Debug summary section ──────────────────────────────────────────
    by_root_cause = summary.get("by_root_cause", {})
    top_down_topics = summary.get("top_down_topics", {})

    if by_root_cause or top_down_topics:
        st.markdown("&nbsp;")
        scols = st.columns(2, gap="medium")
        with scols[0]:
            st.markdown('<div class="card-title">Root cause breakdown</div>', unsafe_allow_html=True)
            if by_root_cause:
                for rc, cnt in by_root_cause.items():
                    label = _ROOT_CAUSE_LABELS.get(rc, rc)
                    st.text(f"  {label}: {cnt}")
            else:
                st.caption("No root causes assigned yet.")
        with scols[1]:
            st.markdown('<div class="card-title">Top topics with downvotes</div>', unsafe_allow_html=True)
            if top_down_topics:
                for topic, cnt in top_down_topics.items():
                    st.text(f"  {topic}: {cnt}")
            else:
                st.caption("No topic data yet.")

    st.markdown("&nbsp;")

    # ─── Filters ────────────────────────────────────────────────────────
    fcols = st.columns([1, 1, 1, 1, 1])
    with fcols[0]:
        filter_type = st.selectbox(
            "Type",
            options=["All", "down", "up"],
            key="fb_filter_type",
            label_visibility="collapsed",
        )
    with fcols[1]:
        filter_status = st.selectbox(
            "Status",
            options=["All", "pending", "reviewed", "actioned"],
            key="fb_filter_status",
            label_visibility="collapsed",
        )
    with fcols[2]:
        filter_root_cause = st.selectbox(
            "Root cause",
            options=["All"] + _ROOT_CAUSE_OPTIONS,
            format_func=lambda x: _ROOT_CAUSE_LABELS.get(x, x) if x != "All" else "All root causes",
            key="fb_filter_root_cause",
            label_visibility="collapsed",
        )
    with fcols[3]:
        filter_limit = st.selectbox(
            "Count",
            options=[20, 50, 100],
            index=1,
            key="fb_filter_limit",
            label_visibility="collapsed",
        )
    with fcols[4]:
        if st.button("Refresh", use_container_width=True):
            st.rerun()

    # Re-fetch with filters
    ft = filter_type if filter_type != "All" else None
    fs = filter_status if filter_status != "All" else None
    frc = filter_root_cause if filter_root_cause != "All" else None
    if ft or fs or frc or filter_limit != 50:
        data = get_feedback_list(
            feedback_type=ft,
            review_status=fs,
            root_cause=frc,
            limit=filter_limit,
        )
        if not data:
            return
        items = data.get("items", [])

    if not items:
        st.info("No feedback matches the current filters.")
        return

    st.caption(f"Showing {len(items)} feedback items")

    # ─── Render feedback list ───────────────────────────────────────────
    for item in items:
        fb_id = item["id"]
        fb_type = item["feedback_type"]
        status = item["review_status"]
        created = datetime.fromtimestamp(item["created_at"]).strftime("%d/%m %H:%M")
        root_cause_val = item.get("root_cause") or ""

        type_badge = "DOWN" if fb_type == "down" else "UP"
        type_color = "var(--danger)" if fb_type == "down" else "var(--ok)"

        badge_parts = [
            f'<span style="font-weight:600; font-size:0.75rem; padding:0.1rem 0.5rem; '
            f'border-radius:4px; background:{type_color}15; color:{type_color}">{type_badge}</span>',
            f'<span style="font-size:0.75rem; color:var(--text-subtle)">{status.upper()}</span>',
            f'<span style="font-size:0.75rem; color:var(--text-subtle)">{created}</span>',
            f'<span style="font-size:0.75rem; color:var(--text-subtle)">#{fb_id}</span>',
        ]
        if root_cause_val:
            rc_label = _ROOT_CAUSE_LABELS.get(root_cause_val, root_cause_val)
            badge_parts.append(
                f'<span style="font-size:0.72rem; padding:0.1rem 0.4rem; border-radius:4px; '
                f'background:var(--accent-soft); color:var(--accent)">{rc_label}</span>'
            )

        header_html = (
            '<div style="display:flex; align-items:center; gap:0.6rem; margin-bottom:0.3rem;">'
            + "".join(badge_parts)
            + '</div>'
        )

        # Expander label
        topic_hint = f" [{item.get('detected_topic')}]" if item.get("detected_topic") else ""
        expander_label = f"{'[DOWN]' if fb_type == 'down' else '[UP]'}{topic_hint} {item['question'][:80]}"

        with st.expander(expander_label):
            st.markdown(header_html, unsafe_allow_html=True)

            st.markdown("**Question:**")
            st.text(item["question"])

            st.markdown("**Answer:**")
            st.text(item["answer"][:500] + ("..." if len(item["answer"]) > 500 else ""))

            if item.get("note"):
                st.markdown(f"**User note:** {item['note']}")

            # ── Debug context ───────────────────────────────────────────
            detail_parts: list[str] = []
            if item.get("session_id"):
                detail_parts.append(f"Session: {item['session_id'][:12]}")
            if item.get("rewritten_query"):
                detail_parts.append(f"Rewritten query: {item['rewritten_query']}")
            if item.get("detected_topic"):
                detail_parts.append(f"Topic: {item['detected_topic']}")
            if item.get("retrieval_count") is not None:
                detail_parts.append(f"Retrieval count: {item['retrieval_count']}")

            if detail_parts:
                st.markdown("**Debug context:**")
                for dp in detail_parts:
                    st.text(f"  {dp}")

            # Citations snapshot
            cit_snap = item.get("citations_snapshot") or []
            if cit_snap:
                with st.expander("Citations snapshot", expanded=False):
                    for ci, cit in enumerate(cit_snap, 1):
                        title = cit.get("title", "Untitled")
                        url = cit.get("url", "")
                        score = cit.get("score")
                        score_str = f" (score: {score})" if score else ""
                        if url:
                            st.markdown(f"{ci}. [{title}]({url}){score_str}")
                        else:
                            st.markdown(f"{ci}. {title}{score_str}")

            # Trace snapshot
            trace_snap = item.get("trace_snapshot") or {}
            if trace_snap:
                with st.expander("Trace snapshot", expanded=False):
                    st.json(trace_snap)

            # ── Review state / form ─────────────────────────────────────
            if item["reviewed"]:
                review_line = f"Reviewed ({item['review_status']})"
                if root_cause_val:
                    review_line += f" — {_ROOT_CAUSE_LABELS.get(root_cause_val, root_cause_val)}"
                if item.get("review_note"):
                    review_line += f" — {item['review_note']}"
                st.success(review_line)

                # Allow creating action item from reviewed feedback
                if st.button(
                    "Create action item",
                    key=f"create-action-{fb_id}",
                    help="Create a follow-up action item for this feedback in the Action Queue.",
                ):
                    result = create_feedback_action_item(fb_id)
                    if result:
                        act_label = _ACTION_LABELS.get(result.get("suggested_action", ""), result.get("suggested_action", ""))
                        st.success(f"Action item #{result['id']} created: {act_label}")
                        st.rerun()
            else:
                with st.form(key=f"review-form-{fb_id}"):
                    rcols = st.columns([2, 1, 1])
                    with rcols[0]:
                        note_input = st.text_input(
                            "Review note",
                            placeholder="Short note (optional)",
                            key=f"review-note-{fb_id}",
                        )
                    with rcols[1]:
                        status_input = st.selectbox(
                            "Status",
                            options=["reviewed", "actioned"],
                            key=f"review-status-{fb_id}",
                        )
                    with rcols[2]:
                        rc_input = st.selectbox(
                            "Root cause",
                            options=["(none)"] + _ROOT_CAUSE_OPTIONS,
                            format_func=lambda x: _ROOT_CAUSE_LABELS.get(x, x) if x != "(none)" else "-- select --",
                            key=f"review-rc-{fb_id}",
                        )
                    if st.form_submit_button("Mark reviewed", type="primary"):
                        rc_val = rc_input if rc_input != "(none)" else None
                        result = review_feedback_item(fb_id, note_input, status_input, rc_val)
                        if result:
                            st.success("Updated!")
                            st.rerun()


# ─── Page: Action Queue ──────────────────────────────────────────────────────
_ACTION_LABELS = {
    "create_coverage_gap": "Create coverage gap",
    "recrawl_source": "Recrawl source",
    "improve_retrieval": "Improve retrieval",
    "adjust_prompt": "Adjust prompt",
    "ignore": "Ignore",
}

_ACTION_COLORS = {
    "create_coverage_gap": ("var(--warn)", "#fef3c7"),
    "recrawl_source": ("var(--accent)", "var(--accent-soft)"),
    "improve_retrieval": ("var(--ok)", "#ecfdf5"),
    "adjust_prompt": ("var(--text-muted)", "#f3f4f6"),
    "ignore": ("var(--text-subtle)", "#f9fafb"),
}

_STATUS_COLORS = {
    "pending": ("var(--warn)", "#fef3c7"),
    "accepted": ("var(--ok)", "#ecfdf5"),
    "done": ("var(--text-muted)", "#f3f4f6"),
    "ignored": ("var(--text-subtle)", "#f9fafb"),
}

_EXEC_STATUS_COLORS = {
    "idle": ("var(--text-subtle)", "#f9fafb"),
    "prepared": ("var(--accent)", "var(--accent-soft)"),
    "executed": ("var(--ok)", "#ecfdf5"),
    "blocked": ("#b91c1c", "#fef2f2"),
}

_EXECUTABLE_ACTIONS = frozenset({"create_coverage_gap", "recrawl_source"})


def page_feedback_actions():
    render_page_header(
        "Action Queue",
        "Follow-up action items derived from reviewed feedback",
    )

    data = get_feedback_actions(limit=200)
    if data is None:
        return

    summary = data.get("summary", {})
    items = data.get("items", [])

    # ─── Summary metrics ────────────────────────────────────────────────
    cols = st.columns(5)
    cols[0].metric("Total", summary.get("total", 0))
    cols[1].metric("Pending", summary.get("total_pending", 0))
    cols[2].metric("Accepted", summary.get("total_accepted", 0))
    cols[3].metric("Done", summary.get("total_done", 0))
    cols[4].metric("Ignored", summary.get("total_ignored", 0))

    by_action = summary.get("by_action", {})
    if by_action:
        st.markdown("&nbsp;")
        st.markdown('<div class="card-title">By suggested action</div>', unsafe_allow_html=True)
        for act, cnt in by_action.items():
            label = _ACTION_LABELS.get(act, act)
            st.text(f"  {label}: {cnt}")

    st.markdown("&nbsp;")

    # ─── Filters ────────────────────────────────────────────────────────
    fcols = st.columns([1, 1, 1, 1])
    with fcols[0]:
        filter_status = st.selectbox(
            "Status",
            options=["All", "pending", "accepted", "done", "ignored"],
            key="aq_filter_status",
            label_visibility="collapsed",
        )
    with fcols[1]:
        filter_action = st.selectbox(
            "Suggested action",
            options=["All"] + list(_ACTION_LABELS.keys()),
            format_func=lambda x: _ACTION_LABELS.get(x, x) if x != "All" else "All actions",
            key="aq_filter_action",
            label_visibility="collapsed",
        )
    with fcols[2]:
        filter_limit = st.selectbox(
            "Count",
            options=[20, 50, 100],
            index=1,
            key="aq_filter_limit",
            label_visibility="collapsed",
        )
    with fcols[3]:
        if st.button("Refresh", use_container_width=True, key="aq_refresh"):
            st.rerun()

    # Re-fetch with filters
    fs = filter_status if filter_status != "All" else None
    fa = filter_action if filter_action != "All" else None
    if fs or fa or filter_limit != 50:
        data = get_feedback_actions(status=fs, suggested_action=fa, limit=filter_limit)
        if data is None:
            return
        items = data.get("items", [])

    if not items:
        st.info("No action items yet. Create one from the Feedback page by reviewing a feedback record.")
        return

    st.caption(f"Showing {len(items)} action items")

    # ─── Render action item list ─────────────────────────────────────────
    for item in items:
        action_id = item["id"]
        fb_id = item["feedback_id"]
        act = item["suggested_action"]
        status = item["status"]
        exec_status = item.get("execution_status") or "idle"
        created = datetime.fromtimestamp(item["created_at"]).strftime("%d/%m %H:%M")
        updated = datetime.fromtimestamp(item["updated_at"]).strftime("%d/%m %H:%M")

        act_label = _ACTION_LABELS.get(act, act)
        act_color, act_bg = _ACTION_COLORS.get(act, ("var(--text-muted)", "#f3f4f6"))
        st_color, st_bg = _STATUS_COLORS.get(status, ("var(--text-muted)", "#f3f4f6"))
        ex_color, ex_bg = _EXEC_STATUS_COLORS.get(exec_status, ("var(--text-subtle)", "#f9fafb"))

        topic = item.get("detected_topic") or "-"
        root_cause = item.get("root_cause") or "-"

        # Build compact execution summary for expander label
        exec_summary = ""
        exec_result = item.get("execution_result") or {}
        if exec_status == "executed":
            exec_summary = f" · {exec_result.get('summary', 'executed')}"
        elif exec_status == "blocked":
            exec_summary = f" · blocked: {exec_result.get('reason', '')[:40]}"

        header_html = (
            '<div style="display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; margin-bottom:0.3rem;">'
            f'<span style="font-size:0.75rem; font-weight:600; padding:0.1rem 0.5rem; '
            f'border-radius:4px; background:{act_bg}; color:{act_color}">{act_label.upper()}</span>'
            f'<span style="font-size:0.75rem; font-weight:600; padding:0.1rem 0.5rem; '
            f'border-radius:4px; background:{st_bg}; color:{st_color}">{status.upper()}</span>'
            f'<span style="font-size:0.75rem; font-weight:600; padding:0.1rem 0.5rem; '
            f'border-radius:4px; background:{ex_bg}; color:{ex_color}">{exec_status.upper()}</span>'
            f'<span style="font-size:0.74rem; color:var(--text-subtle)">[{topic}]</span>'
            f'<span style="font-size:0.74rem; color:var(--text-subtle)">{created}</span>'
            f'<span style="font-size:0.74rem; color:var(--text-subtle)">fb#{fb_id} · ai#{action_id}</span>'
            '</div>'
        )

        expander_label = f"[{act_label}] [{status}] fb#{fb_id} — {root_cause}{exec_summary}"
        with st.expander(expander_label):
            st.markdown(header_html, unsafe_allow_html=True)

            info_parts = [
                ("Feedback ID", f"#{fb_id}"),
                ("Root cause", root_cause),
                ("Topic", topic),
                ("Suggested action", act_label),
                ("Updated", updated),
            ]
            if item.get("query_hint"):
                info_parts.append(("Query hint", item["query_hint"]))

            for label, val in info_parts:
                st.markdown(f"**{label}:** {val}")

            if item.get("reason"):
                st.markdown("**Reason:**")
                st.text(item["reason"])

            if item.get("owner_note"):
                st.info(f"Note: {item['owner_note']}")

            # ── Execution bridge ────────────────────────────────────────
            if act in _EXECUTABLE_ACTIONS:
                st.markdown("---")
                ecols = st.columns([3, 1])
                with ecols[0]:
                    if exec_status == "executed":
                        st.success(exec_result.get("summary", "Executed."))
                        if item.get("execution_type") == "coverage_gap_review":
                            gap_id = exec_result.get("coverage_gap_id")
                            if gap_id:
                                st.caption(f"Coverage gap #{gap_id} created.")
                        elif item.get("execution_type") == "recrawl":
                            st.caption(
                                f"Docs crawled: {exec_result.get('documents_crawled', 0)}  "
                                f"· Chunks: {exec_result.get('chunks_indexed', 0)}"
                            )
                    elif exec_status == "blocked":
                        st.warning(f"Blocked: {exec_result.get('reason', 'unknown reason')}")
                    else:
                        st.caption(f"Execution: {exec_status}")
                with ecols[1]:
                    if st.button(
                        "Execute",
                        key=f"aq-exec-{action_id}",
                        use_container_width=True,
                        help=f"Bridge this action into the {act_label} workflow.",
                    ):
                        result = execute_feedback_action(action_id)
                        if result:
                            new_exec = result.get("execution_status", "")
                            new_result = result.get("execution_result") or {}
                            if new_exec == "executed":
                                st.success(new_result.get("summary", "Executed."))
                            elif new_exec == "blocked":
                                st.warning(f"Blocked: {new_result.get('reason', '')}")
                            st.rerun()

            # ── Status update form ──────────────────────────────────────
            if status not in ("done", "ignored"):
                st.markdown("---")
                with st.form(key=f"aq-status-form-{action_id}"):
                    scols = st.columns([2, 1])
                    with scols[0]:
                        note_input = st.text_input(
                            "Owner note (optional)",
                            placeholder="Short note...",
                            key=f"aq-note-{action_id}",
                        )
                    with scols[1]:
                        new_status = st.selectbox(
                            "New status",
                            options=["accepted", "done", "ignored", "pending"],
                            key=f"aq-status-{action_id}",
                        )
                    if st.form_submit_button("Update status", type="primary"):
                        result = update_feedback_action_status(
                            action_id,
                            status=new_status,
                            owner_note=note_input.strip() or None,
                        )
                        if result:
                            st.success(f"Status updated to {new_status}.")
                            st.rerun()
            else:
                st.caption(f"Status: {status} — no further actions available.")


# ─── Eval Cases API helpers ─────────────────────────────────────────────────

def create_eval_case(feedback_id: int) -> dict | None:
    try:
        r = http().post(f"{api_url()}/admin/feedback/{feedback_id}/eval-case")
        if r.status_code == 409:
            st.warning(r.json().get("detail", "Active eval case already exists for this feedback."))
            return None
        if r.status_code == 400:
            st.warning(r.json().get("detail", "Cannot create eval case."))
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Create eval case failed: {exc}")
        return None


def get_eval_cases(
    status: str | None = None,
    root_cause: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if root_cause:
            params["root_cause"] = root_cause
        r = http().get(f"{api_url()}/admin/eval-cases", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch eval cases: {exc}")
        return None


def get_eval_cases_summary() -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/eval-cases/summary")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch eval cases summary: {exc}")
        return None


def run_eval_case(case_id: int) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/eval-cases/{case_id}/run",
            timeout=httpx.Timeout(120.0, connect=5.0, read=120.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Run eval case failed: {exc}")
        return None


def get_eval_case_runs(case_id: int, limit: int = 10) -> dict | None:
    try:
        r = http().get(
            f"{api_url()}/admin/eval-cases/{case_id}/runs",
            params={"limit": limit},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch runs: {exc}")
        return None


def archive_eval_case(case_id: int) -> dict | None:
    try:
        r = http().patch(
            f"{api_url()}/admin/eval-cases/{case_id}/status",
            json={"status": "archived"},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Archive failed: {exc}")
        return None


def run_eval_batch(
    label: str | None = None,
    root_cause: str | None = None,
    expected_topic: str | None = None,
    limit: int | None = None,
) -> dict | None:
    try:
        body: dict = {}
        if label:
            body["label"] = label
        if root_cause:
            body["root_cause"] = root_cause
        if expected_topic:
            body["expected_topic"] = expected_topic
        if limit:
            body["limit"] = limit
        r = http().post(
            f"{api_url()}/admin/eval-cases/run-batch",
            json=body,
            timeout=httpx.Timeout(600.0, connect=5.0, read=600.0),
        )
        if r.status_code == 400:
            st.warning(r.json().get("detail", "No matching eval cases found."))
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Batch run failed: {exc}")
        return None


def get_eval_batches(limit: int = 10, offset: int = 0) -> dict | None:
    try:
        r = http().get(
            f"{api_url()}/admin/eval-batches",
            params={"limit": limit, "offset": offset},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch eval batches: {exc}")
        return None


def get_eval_batch_detail(batch_id: int) -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/eval-batches/{batch_id}")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch batch detail: {exc}")
        return None


def get_eval_batch_items(batch_id: int, limit: int = 200) -> dict | None:
    try:
        r = http().get(
            f"{api_url()}/admin/eval-batches/{batch_id}/items",
            params={"limit": limit},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch batch items: {exc}")
        return None


def get_eval_batches_compare(
    candidate_batch_id: int,
    baseline_batch_id: int | None = None,
) -> dict | None:
    try:
        params: dict = {"candidate_batch_id": candidate_batch_id}
        if baseline_batch_id is not None:
            params["baseline_batch_id"] = baseline_batch_id
        r = http().get(f"{api_url()}/admin/eval-batches/compare", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot compare batches: {exc}")
        return None


def get_eval_batches_trend_data(limit: int = 10) -> dict | None:
    try:
        r = http().get(
            f"{api_url()}/admin/eval-batches/trend",
            params={"limit": limit},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch trend: {exc}")
        return None


# ─── Page: Eval Cases ────────────────────────────────────────────────────────

def page_eval_cases():
    render_page_header(
        "Eval Cases",
        "Regression quality cases derived from reviewed feedback",
    )

    summary = get_eval_cases_summary()
    if summary:
        c = st.columns(4)
        c[0].metric("Active cases", summary.get("total_active", 0))
        c[1].metric("Archived", summary.get("total_archived", 0))
        lr = summary.get("latest_runs", {})
        c[2].metric("Latest pass", lr.get("pass", 0))
        c[3].metric("Latest fail", lr.get("fail", 0))

    st.markdown("&nbsp;")

    # ── Create eval case from feedback ───────────────────────────────────────
    with st.expander("Create eval case from reviewed feedback", expanded=False):
        st.caption(
            "Enter a reviewed feedback ID to create an eval case. "
            "The feedback must have been reviewed (not pending)."
        )
        with st.form("create-eval-case-form"):
            fb_id_input = st.number_input(
                "Feedback ID",
                min_value=1,
                step=1,
                key="ec-create-fb-id",
            )
            submitted = st.form_submit_button("Create eval case", type="primary")
        if submitted:
            result = create_eval_case(int(fb_id_input))
            if result:
                st.success(
                    f"Eval case #{result['id']} created for feedback #{result['feedback_id']}."
                )
                st.rerun()

    st.markdown("---")

    # ── Batch Run ─────────────────────────────────────────────────────────────
    st.markdown("**Batch Run**")
    st.caption("Run many active eval cases at once and get a compact quality summary.")

    with st.form("eval-batch-run-form"):
        bcols = st.columns([3, 2, 2, 1])
        with bcols[0]:
            batch_label = st.text_input(
                "Label (optional)",
                placeholder="e.g. Post-retrieval-tuning check",
                key="eb-label",
            )
        with bcols[1]:
            batch_rc = st.text_input(
                "Root cause filter",
                placeholder="e.g. retrieval_miss",
                key="eb-rc",
            )
        with bcols[2]:
            batch_topic = st.text_input(
                "Expected topic filter",
                placeholder="e.g. kubernetes",
                key="eb-topic",
            )
        with bcols[3]:
            batch_limit = st.number_input(
                "Max cases",
                min_value=1,
                max_value=200,
                value=100,
                key="eb-limit",
            )
        batch_submitted = st.form_submit_button("Run active eval batch", type="primary")

    if batch_submitted:
        with st.spinner("Running eval batch…"):
            batch_result = run_eval_batch(
                label=batch_label.strip() or None,
                root_cause=batch_rc.strip() or None,
                expected_topic=batch_topic.strip() or None,
                limit=int(batch_limit),
            )
        if batch_result:
            summary = batch_result.get("summary", {})
            total = summary.get("total_cases", 0)
            passes = summary.get("pass_count", 0)
            fails = summary.get("fail_count", 0)
            errors = summary.get("error_count", 0)
            rate = summary.get("pass_rate", 0.0)

            st.success(f"Batch #{batch_result['id']} complete")
            rc_cols = st.columns(4)
            rc_cols[0].metric("Cases", total)
            rc_cols[1].metric("Pass", passes)
            rc_cols[2].metric("Fail", fails)
            rc_cols[3].metric("Pass rate", f"{rate * 100:.0f}%")

            by_rc = summary.get("by_root_cause", {})
            if by_rc:
                fail_lines = [
                    f"  {rc}: {v.get('fail', 0)} fail"
                    for rc, v in by_rc.items()
                    if v.get("fail", 0) > 0
                ]
                if fail_lines:
                    st.markdown("**Failures by root cause:**")
                    st.text("\n".join(fail_lines))
            if errors:
                st.warning(f"{errors} case(s) failed to execute (pipeline errors).")

    st.markdown("---")

    # ── Recent batches ────────────────────────────────────────────────────────
    with st.expander("Recent batch runs", expanded=False):
        batches_data = get_eval_batches(limit=10)
        if batches_data is None or not batches_data.get("batches"):
            st.caption("No batch runs yet.")
        else:
            for batch in batches_data["batches"]:
                bid = batch["id"]
                blabel = batch.get("label") or f"Batch #{bid}"
                total = batch.get("total_cases", 0)
                passes = batch.get("pass_count", 0)
                fails = batch.get("fail_count", 0)
                rate = f"{passes / total * 100:.0f}%" if total else "—"
                created = datetime.fromtimestamp(batch["created_at"]).strftime("%Y-%m-%d %H:%M")

                row_label = f"#{bid} · {blabel} · {total} cases · {passes} pass / {fails} fail · {rate} · {created}"
                with st.expander(row_label, expanded=False):
                    detail = get_eval_batch_detail(bid)
                    if detail:
                        dsummary = detail.get("summary", {})
                        dcols = st.columns(4)
                        dcols[0].metric("Total", dsummary.get("total_cases", 0))
                        dcols[1].metric("Pass", dsummary.get("pass_count", 0))
                        dcols[2].metric("Fail", dsummary.get("fail_count", 0))
                        dcols[3].metric(
                            "Pass rate",
                            f"{dsummary.get('pass_rate', 0) * 100:.0f}%",
                        )

                        by_rc = dsummary.get("by_root_cause", {})
                        by_et = dsummary.get("by_expected_topic", {})
                        if by_rc or by_et:
                            bk_cols = st.columns(2)
                            with bk_cols[0]:
                                if by_rc:
                                    st.markdown("**By root cause:**")
                                    for rc, v in by_rc.items():
                                        p, f = v.get("pass", 0), v.get("fail", 0)
                                        st.text(f"  {rc}: {p} pass / {f} fail")
                            with bk_cols[1]:
                                if by_et:
                                    st.markdown("**By topic:**")
                                    for et, v in by_et.items():
                                        p, f = v.get("pass", 0), v.get("fail", 0)
                                        st.text(f"  {et}: {p} pass / {f} fail")

                        items_data = get_eval_batch_items(bid, limit=200)
                        if items_data and items_data.get("items"):
                            st.markdown("**Per-case results:**")
                            for it in items_data["items"]:
                                pass_label = (
                                    "PASS" if it["pass"] is True
                                    else "FAIL" if it["pass"] is False
                                    else "ERROR"
                                )
                                rc_note = it.get("root_cause") or "—"
                                err_note = f"  · {it['error'][:80]}" if it.get("error") else ""
                                st.caption(
                                    f"case #{it['eval_case_id']} [{pass_label}]"
                                    f"  rc={rc_note}"
                                    f"  run_id={it.get('eval_run_id') or '—'}"
                                    f"{err_note}"
                                )

    st.markdown("---")

    # ── Trend history ──────────────────────────────────────────────────────────
    with st.expander("Batch trend history", expanded=False):
        st.caption("Recent batch runs in newest-first order. Quick scan of quality direction over time.")
        trend_data = get_eval_batches_trend_data(limit=15)
        if trend_data is None or not trend_data.get("batches"):
            st.caption("No batch runs yet.")
        else:
            for item in trend_data["batches"]:
                bid = item["id"]
                blabel = item.get("label") or f"#{bid}"
                total = item.get("total_cases", 0)
                passes = item.get("pass_count", 0)
                fails = item.get("fail_count", 0)
                errors = item.get("error_count", 0)
                rate = item.get("pass_rate", 0.0)
                rate_pct = f"{rate * 100:.0f}%"
                created = datetime.fromtimestamp(item["created_at"]).strftime("%Y-%m-%d %H:%M")
                err_note = f" · {errors} err" if errors else ""
                st.text(
                    f"#{bid} · {blabel} · {rate_pct} pass"
                    f" · {total} cases ({passes} pass / {fails} fail{err_note})"
                    f" · {created}"
                )

    st.markdown("---")

    # ── Batch comparison ──────────────────────────────────────────────────────
    with st.expander("Compare two batch runs", expanded=False):
        st.caption(
            "Compare a candidate batch against a baseline to see pass/fail deltas "
            "by root cause and topic."
        )

        # Build batch list for selection (newest first)
        batch_list_data = get_eval_batches(limit=30)
        batches_available = (batch_list_data or {}).get("batches", [])

        if len(batches_available) < 2:
            st.info("Need at least 2 batch runs to compare.")
        else:
            batch_options = {
                f"#{b['id']} · {b.get('label') or '—'} · "
                f"{b.get('pass_count', 0)}/{b.get('total_cases', 0)} pass"
                f" · {datetime.fromtimestamp(b['created_at']).strftime('%Y-%m-%d %H:%M')}": b["id"]
                for b in batches_available
            }
            option_labels = list(batch_options.keys())

            cmp_cols = st.columns(2)
            with cmp_cols[0]:
                baseline_label = st.selectbox(
                    "Baseline batch",
                    options=option_labels,
                    index=min(1, len(option_labels) - 1),
                    key="cmp-baseline",
                )
            with cmp_cols[1]:
                candidate_label = st.selectbox(
                    "Candidate batch",
                    options=option_labels,
                    index=0,
                    key="cmp-candidate",
                )

            if st.button("Compare", key="cmp-run-btn", type="primary"):
                baseline_id = batch_options[baseline_label]
                candidate_id = batch_options[candidate_label]
                if baseline_id == candidate_id:
                    st.warning("Select two different batches.")
                else:
                    with st.spinner("Comparing…"):
                        cmp = get_eval_batches_compare(
                            candidate_batch_id=candidate_id,
                            baseline_batch_id=baseline_id,
                        )
                    if cmp:
                        # Top-level summary
                        st.markdown("**Summary**")
                        top_cols = st.columns(4)
                        b_rate = cmp.get("baseline_pass_rate", 0.0)
                        c_rate = cmp.get("candidate_pass_rate", 0.0)
                        delta_rate = cmp.get("delta_pass_rate", 0.0)
                        top_cols[0].metric(
                            "Baseline pass rate", f"{b_rate * 100:.0f}%"
                        )
                        top_cols[1].metric(
                            "Candidate pass rate",
                            f"{c_rate * 100:.0f}%",
                            delta=f"{delta_rate * 100:+.0f}pp",
                        )
                        top_cols[2].metric(
                            "Delta pass count",
                            f"{cmp.get('delta_pass_count', 0):+d}",
                        )
                        top_cols[3].metric(
                            "Delta fail count",
                            f"{cmp.get('delta_fail_count', 0):+d}",
                        )

                        if cmp.get("sizes_differ"):
                            st.caption(
                                f"Note: batch sizes differ "
                                f"(baseline={cmp['baseline_total_cases']}, "
                                f"candidate={cmp['candidate_total_cases']})."
                            )

                        # Group breakdowns
                        bk_cols = st.columns(2)
                        with bk_cols[0]:
                            by_rc = cmp.get("by_root_cause", {})
                            if by_rc:
                                st.markdown("**By root cause:**")
                                for rc, v in by_rc.items():
                                    b_fail = v["baseline"]["fail"]
                                    c_fail = v["candidate"]["fail"]
                                    d_fail = v["delta"]["fail"]
                                    d_pass = v["delta"]["pass"]
                                    arrow = "↑" if d_fail < 0 else ("↓" if d_fail > 0 else "=")
                                    st.text(
                                        f"  {rc}: fail {b_fail}→{c_fail} {arrow}"
                                        f"  pass {d_pass:+d}"
                                    )
                        with bk_cols[1]:
                            by_et = cmp.get("by_expected_topic", {})
                            if by_et:
                                st.markdown("**By topic:**")
                                for et, v in by_et.items():
                                    b_fail = v["baseline"]["fail"]
                                    c_fail = v["candidate"]["fail"]
                                    d_fail = v["delta"]["fail"]
                                    d_pass = v["delta"]["pass"]
                                    arrow = "↑" if d_fail < 0 else ("↓" if d_fail > 0 else "=")
                                    st.text(
                                        f"  {et}: fail {b_fail}→{c_fail} {arrow}"
                                        f"  pass {d_pass:+d}"
                                    )

    st.markdown("---")

    # ── Filter bar ────────────────────────────────────────────────────────────
    fcols = st.columns([2, 2, 1])
    with fcols[0]:
        filter_status = st.selectbox(
            "Status",
            options=["active", "archived", "all"],
            index=0,
            key="ec-filter-status",
        )
    with fcols[1]:
        filter_rc = st.text_input(
            "Root cause (optional)",
            placeholder="e.g. retrieval_miss",
            key="ec-filter-rc",
        )

    status_param = None if filter_status == "all" else filter_status
    rc_param = filter_rc.strip() or None

    data = get_eval_cases(status=status_param, root_cause=rc_param, limit=50)
    if data is None:
        return

    items = data.get("items", [])
    if not items:
        st.info("No eval cases found.")
        return

    st.caption(f"{len(items)} eval case(s) shown.")

    # ── Case list ─────────────────────────────────────────────────────────────
    for case in items:
        case_id = case["id"]
        status = case.get("status", "active")
        root_cause = case.get("root_cause") or "—"
        expected_topic = case.get("expected_topic") or "—"
        latest_run = case.get("latest_run")

        if latest_run:
            run_pass = latest_run.get("pass")
            run_badge = "PASS" if run_pass else "FAIL"
            run_badge_color = "green" if run_pass else "red"
        else:
            run_badge = "—"
            run_badge_color = "gray"

        label = (
            f"[#{case_id}] {case['question'][:80]}"
            f"  |  {root_cause}  |  {run_badge}"
        )
        with st.expander(label, expanded=False):
            col_meta, col_actions = st.columns([3, 1])

            with col_meta:
                st.markdown(f"**Question:** {case['question']}")
                st.markdown(
                    f"**Root cause:** `{root_cause}` &nbsp; "
                    f"**Expected topic:** `{expected_topic}` &nbsp; "
                    f"**Status:** `{status}`",
                    unsafe_allow_html=True,
                )

                exp = case.get("eval_expectations", {})
                exp_parts = []
                if exp.get("should_not_fallback") is not None:
                    exp_parts.append(f"no_fallback={exp['should_not_fallback']}")
                if exp.get("should_have_citations") is not None:
                    exp_parts.append(f"has_citations={exp['should_have_citations']}")
                if exp.get("min_retrieval_count") is not None:
                    exp_parts.append(f"min_retrieval={exp['min_retrieval_count']}")
                if exp.get("expected_topic"):
                    exp_parts.append(f"topic={exp['expected_topic']}")
                st.markdown(
                    "**Expectations:** " + (", ".join(exp_parts) if exp_parts else "_(none set)_")
                )

                if latest_run:
                    run_time = datetime.fromtimestamp(latest_run["run_at"]).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                    st.markdown(
                        f"**Latest run:** "
                        f"<span style='color:{run_badge_color};font-weight:600'>{run_badge}</span>"
                        f" at {run_time}",
                        unsafe_allow_html=True,
                    )
                    snap = latest_run.get("result_snapshot", {})
                    if snap:
                        st.caption(
                            f"topic={snap.get('detected_topic') or '—'}  "
                            f"retrieval={snap.get('retrieval_count', 0)}  "
                            f"fallback={snap.get('is_fallback', False)}"
                        )
                    checks = latest_run.get("checks", {})
                    if checks:
                        check_lines = []
                        for name, chk in checks.items():
                            if chk.get("skipped"):
                                icon = "⬜"
                            elif chk.get("pass"):
                                icon = "✓"
                            else:
                                icon = "✗"
                            check_lines.append(f"{icon} **{name}**: {chk.get('reason', '')}")
                        st.markdown("  \n".join(check_lines))
                else:
                    st.caption("Not yet run.")

            with col_actions:
                if status == "active":
                    if st.button("Run now", key=f"ec-run-{case_id}", type="primary"):
                        with st.spinner("Running..."):
                            run_result = run_eval_case(case_id)
                        if run_result:
                            if run_result.get("pass"):
                                st.success("PASS")
                            else:
                                st.error("FAIL")
                            st.rerun()

                    if st.button("Archive", key=f"ec-archive-{case_id}"):
                        if archive_eval_case(case_id):
                            st.success("Archived.")
                            st.rerun()
                else:
                    st.caption("Archived.")

            # Run history (collapsed)
            if st.button("Show run history", key=f"ec-hist-{case_id}"):
                hist = get_eval_case_runs(case_id, limit=10)
                if hist and hist.get("runs"):
                    for run in hist["runs"]:
                        run_time = datetime.fromtimestamp(run["run_at"]).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        badge = "PASS" if run.get("pass") else "FAIL"
                        st.markdown(f"- **{badge}** at {run_time}")
                else:
                    st.caption("No run history.")


# ─── Render selected page ───────────────────────────────────────────────────
PAGE_RENDERERS = {
    "Dashboard": page_dashboard,
    "Sources": page_sources,
    "Health Check": page_health,
    "Freshness Center": page_freshness_center,
    "Coverage Gaps": page_coverage_gaps,
    "Feedback": page_feedback,
    "Action Queue": page_feedback_actions,
    "Eval Cases": page_eval_cases,
    "Sessions": page_sessions,
    "Maintenance": page_maintenance,
}

if not backend_ok:
    st.error(f"Không kết nối được backend tại {api_url()}. Khởi động backend rồi refresh.")
else:
    PAGE_RENDERERS[page]()
