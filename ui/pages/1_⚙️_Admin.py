"""Admin Portal — quản trị KB, sources, sessions, cache.

Truy cập: http://localhost:8501/Admin (Streamlit auto từ filename)
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
        r = http().post(f"{api_url()}/admin/ingest", json=body, timeout=httpx.Timeout(600.0, connect=5.0, read=600.0))
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
        r = http().post(f"{api_url()}/admin/bm25/rebuild", timeout=httpx.Timeout(120.0, connect=5.0, read=120.0))
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Rebuild thất bại: {exc}")
        return None


# ─── CSS giống main app ─────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    .stApp { font-family: 'Inter', sans-serif; background: #faf9f7; }
    .block-container { max-width: 1200px; padding-top: 1.5rem; }
    h1, h2, h3 { letter-spacing: -0.02em; color: #1f1f1f; }
    [data-testid="stMetricValue"] { font-size: 1.6rem; }
    .status-ok { color: #16a34a; }
    .status-stale { color: #d97706; }
    .status-dead { color: #dc2626; }
    .status-redirect { color: #d97706; }
    .status-unknown { color: #6b6b6b; }
    .stButton > button[kind="primary"] {
        background: #cc785c;
        color: white;
        border: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("⚙️ Admin Portal")
st.caption("Quản lý knowledge base, sources, sessions và cache")

tab_sources, tab_health, tab_stats, tab_sessions, tab_maint = st.tabs([
    "📚 Sources", "🩺 Health Check", "📊 Stats", "💾 Sessions", "🛠️ Maintenance",
])

# ─── Tab 1: Sources ─────────────────────────────────────────────────────────
with tab_sources:
    st.subheader("Quản lý sources")
    st.caption("Thêm URL vào topic, xoá hoặc trigger crawl. Mỗi topic 1 file `sources/<topic>.json`.")

    col_form, col_actions = st.columns([2, 1], gap="medium")

    with col_form:
        st.markdown("##### ➕ Thêm URL mới")
        with st.form("add_url_form", clear_on_submit=True):
            new_topic = st.text_input("Topic", placeholder="vd: kubernetes, react, fastapi")
            new_url = st.text_input("URL", placeholder="https://docs.example.com/page")
            new_title = st.text_input("Title (tùy chọn)", placeholder="Để trống sẽ dùng URL")
            submit = st.form_submit_button("➕ Thêm", type="primary")
            if submit:
                if not new_topic or not new_url:
                    st.error("Cần điền topic và URL.")
                else:
                    ok, msg = add_url(new_topic.strip(), new_url.strip(), new_title.strip())
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    with col_actions:
        st.markdown("##### 🚀 Crawl ad-hoc")
        st.caption("Crawl 1 URL ngay không cần thêm vào sources file.")
        with st.form("adhoc_crawl"):
            adhoc_topic = st.text_input("Topic", value="general", key="adhoc_topic")
            adhoc_url = st.text_input("URL", placeholder="https://...", key="adhoc_url")
            adhoc_submit = st.form_submit_button("Crawl ngay")
            if adhoc_submit and adhoc_url:
                with st.spinner("Đang crawl + index..."):
                    res = trigger_ingest(urls=[{
                        "location": adhoc_url.strip(),
                        "topic": adhoc_topic.strip() or "general",
                        "title": adhoc_url.strip(),
                        "source": "website",
                    }])
                if res:
                    st.success(
                        f"Crawl xong: {res['documents_crawled']} docs, {res['chunks_indexed']} chunks"
                    )

    st.divider()

    st.markdown("##### 📂 Topics hiện có")
    topics = get_sources()
    if not topics:
        st.info("Chưa có topic nào. Thêm URL ở form trên để tạo topic mới.")
    else:
        for t in topics:
            with st.expander(f"**{t['topic']}** — {t['count']} URLs", expanded=False):
                cols = st.columns([3, 1])
                with cols[0]:
                    st.caption(f"File: `{t['file']}`")
                with cols[1]:
                    if st.button(
                        "🔄 Re-crawl topic",
                        key=f"recrawl-{t['topic']}",
                        use_container_width=True,
                    ):
                        with st.spinner(f"Đang re-crawl {t['topic']}..."):
                            res = trigger_ingest(topic=t["topic"])
                        if res:
                            st.success(
                                f"{res['documents_crawled']} docs, {res['chunks_indexed']} chunks"
                            )

                if not t["items"]:
                    st.caption("(rỗng)")
                else:
                    for item in t["items"]:
                        url_cols = st.columns([5, 1])
                        with url_cols[0]:
                            st.markdown(f"- `{item.get('title', item['location'])}`  \n  {item['location']}")
                        with url_cols[1]:
                            if st.button(
                                "Xoá",
                                key=f"del-{t['topic']}-{item['location']}",
                                use_container_width=True,
                            ):
                                if delete_url(t["topic"], item["location"]):
                                    st.rerun()

# ─── Tab 2: Health Check ────────────────────────────────────────────────────
with tab_health:
    st.subheader("Health check sources")
    st.caption(
        "Kiểm tra URLs trong `sources/*.json`: status HTTP, detect content thay đổi (STALE), redirect."
    )

    topics = get_sources()
    topic_names = ["(tất cả)"] + [t["topic"] for t in topics]
    selected = st.selectbox("Topic", topic_names)
    selected_topic = None if selected == "(tất cả)" else selected

    cols = st.columns([1, 1, 4])
    with cols[0]:
        run_btn = st.button("🩺 Chạy check", type="primary", use_container_width=True)
    with cols[1]:
        if "health_result" in st.session_state and st.button("🗑️ Xoá kết quả", use_container_width=True):
            del st.session_state["health_result"]
            st.rerun()

    if run_btn:
        with st.spinner("Đang check (có thể mất 1-2 phút)..."):
            result = run_health(selected_topic)
        if result:
            st.session_state["health_result"] = result
            st.session_state["health_run_at"] = datetime.now().strftime("%H:%M:%S")

    if "health_result" in st.session_state:
        result = st.session_state["health_result"]
        run_at = st.session_state.get("health_run_at", "")

        st.caption(f"Last run: {run_at}")
        m_cols = st.columns(5)
        m_cols[0].metric("Total", result["total"])
        m_cols[1].metric("✓ OK", result["ok"])
        m_cols[2].metric("⚠ Stale", result["stale"])
        m_cols[3].metric("✗ Dead", result["dead"])
        m_cols[4].metric("↪ Redirect", result["redirect"])

        # Filter row
        st.divider()
        filter_cols = st.columns(5)
        show_ok = filter_cols[0].checkbox("OK", value=False)
        show_stale = filter_cols[1].checkbox("Stale", value=True)
        show_dead = filter_cols[2].checkbox("Dead", value=True)
        show_redirect = filter_cols[3].checkbox("Redirect", value=True)
        show_unknown = filter_cols[4].checkbox("Unknown", value=True)

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

        for r in result["results"]:
            if r["status"] not in wanted:
                continue
            cls = {
                "OK": "status-ok", "STALE": "status-stale", "DEAD": "status-dead",
                "REDIRECT": "status-redirect", "UNKNOWN": "status-unknown",
            }.get(r["status"], "")
            icon = {"OK": "✓", "STALE": "⚠", "DEAD": "✗", "REDIRECT": "↪", "UNKNOWN": "?"}[r["status"]]
            st.markdown(
                f"<div><span class='{cls}' style='font-weight:600'>{icon} {r['status']}</span>  "
                f"<span style='color:#6b6b6b'>[{r['topic']}]</span>  "
                f"{r['location'][:90]}  "
                f"<span style='color:#6b6b6b'>({r['detail']})</span></div>",
                unsafe_allow_html=True,
            )

        # Auto re-ingest button
        stale_urls = [r for r in result["results"] if r["status"] == "STALE"]
        if stale_urls:
            st.divider()
            st.warning(f"Có {len(stale_urls)} URL stale — content đã thay đổi.")
            if st.button("🔄 Re-ingest tất cả URL stale", type="primary"):
                urls_to_update = [
                    {"location": r["location"], "topic": r["topic"], "title": r["title"], "source": "website"}
                    for r in stale_urls
                ]
                with st.spinner("Đang re-crawl + re-embed..."):
                    res = trigger_ingest(urls=urls_to_update)
                if res:
                    st.success(f"Đã update: {res['documents_crawled']} docs, {res['chunks_indexed']} chunks")

# ─── Tab 3: Stats ───────────────────────────────────────────────────────────
with tab_stats:
    st.subheader("Knowledge Base Stats")

    if st.button("🔄 Refresh", key="refresh_stats"):
        st.rerun()

    stats = get_stats()
    if stats:
        st.markdown("##### Chunks")
        m_cols = st.columns(3)
        m_cols[0].metric("Total chunks", stats["chunks"]["total"])
        m_cols[1].metric("Topics", len(stats["chunks"]["by_topic"]))
        m_cols[2].metric("Session uploads", stats["chunks"]["session_uploads"])

        st.caption("Số chunks per topic:")
        if stats["chunks"]["by_topic"]:
            st.bar_chart(stats["chunks"]["by_topic"])

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### BM25 Index")
            bm25 = stats["bm25"]
            st.metric(
                "Status",
                "✓ Ready" if bm25["enabled_ready"] else "✗ Not ready",
                f"{bm25['indexed_chunks']} chunks indexed",
            )

        with c2:
            st.markdown("##### Answer Cache")
            cache = stats["cache"]
            st.metric(
                "Cache size",
                f"{cache['size']} / {cache['max_size']}",
                f"TTL {cache['ttl_seconds']}s",
            )

        st.divider()
        st.markdown("##### Metrics (counters từ khi backend khởi động)")
        metrics = stats.get("metrics", {})
        counters = metrics.get("counters", {})
        if counters:
            st.dataframe(
                {"Counter": list(counters.keys()), "Value": list(counters.values())},
                hide_index=True,
                use_container_width=True,
            )
        m_lat = st.columns(3)
        m_lat[0].metric("Latency avg", f"{metrics.get('latency_avg_ms', 0)} ms")
        m_lat[1].metric("Latency max", f"{metrics.get('latency_max_ms', 0)} ms")
        m_lat[2].metric("Sessions", stats["sessions"]["count_with_messages"])

# ─── Tab 4: Sessions ────────────────────────────────────────────────────────
with tab_sessions:
    st.subheader("Sessions / Cuộc trò chuyện")
    sessions = get_sessions()
    if not sessions:
        st.info("Chưa có session nào.")
    else:
        for s in sessions:
            cols = st.columns([4, 2, 1, 1])
            cols[0].markdown(f"**{s['title']}**")
            cols[1].caption(f"{s['message_count']} tin nhắn")
            cols[2].caption(s["id"][:8])
            with cols[3]:
                if st.button("🗑️", key=f"delsess-{s['id']}", help="Xoá session"):
                    if delete_session(s["id"]):
                        st.rerun()

# ─── Tab 5: Maintenance ─────────────────────────────────────────────────────
with tab_maint:
    st.subheader("Maintenance")
    st.caption("Các tác vụ bảo trì hệ thống.")

    cols = st.columns(2)
    with cols[0]:
        st.markdown("##### Answer Cache")
        st.caption("Xoá toàn bộ cache câu trả lời. Lần hỏi tiếp theo sẽ phải gọi LLM lại.")
        if st.button("🗑️ Clear answer cache", use_container_width=True):
            if clear_cache():
                st.success("Đã xoá cache")

    with cols[1]:
        st.markdown("##### BM25 Index")
        st.caption("Rebuild BM25 từ Chroma. Chạy khi nghi ngờ index lệch với data.")
        if st.button("🔄 Rebuild BM25", use_container_width=True):
            with st.spinner("Đang rebuild..."):
                res = rebuild_bm25()
            if res:
                st.success(f"Đã rebuild với {res['chunks_indexed']} chunks")

    st.divider()
    st.markdown("##### Reset toàn bộ KB")
    st.caption("⚠️ Xoá toàn bộ Chroma collection và re-ingest từ tất cả `sources/*.json`. Mất vài phút.")
    confirm = st.checkbox("Tôi hiểu thao tác này không thể hoàn tác")
    if st.button("☢️ Reset & Re-ingest All", disabled=not confirm, type="primary"):
        with st.spinner("Đang reset + crawl + re-embed (có thể mất 5-10 phút)..."):
            # Reset bằng cách trigger ingest cho từng topic với reset=True ở topic đầu
            topics = get_sources()
            if topics:
                first = topics[0]["topic"]
                trigger_ingest(topic=first, reset=True)
                for t in topics[1:]:
                    if t["count"] > 0:
                        trigger_ingest(topic=t["topic"])
        st.success("Reset hoàn tất")
