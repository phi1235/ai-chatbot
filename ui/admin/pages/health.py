from __future__ import annotations

from datetime import datetime

import streamlit as st

from ui.admin.api_client import get_sources, run_health, trigger_ingest
from ui.admin.page_shell import render_page_header, status_row_html


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
        if "health_result" in st.session_state and st.button("Xoá kết quả", use_container_width=True):
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

    visible_rows = [row for row in result["results"] if row["status"] in wanted]
    if not visible_rows:
        st.caption("(không có entry nào với filter hiện tại)")
        return

    health_sel_key = "health_selected_urls"
    if health_sel_key not in st.session_state:
        st.session_state[health_sel_key] = set()
    health_selected = st.session_state[health_sel_key]

    actionable = [row for row in visible_rows if row["status"] in ("STALE", "REDIRECT", "DEAD")]
    tcols = st.columns([2, 2, 2, 1])
    with tcols[0]:
        if st.button(
            f"Chọn tất cả STALE ({sum(1 for row in actionable if row['status'] == 'STALE')})",
            use_container_width=True,
            key="health_sel_stale",
            disabled=not any(row["status"] == "STALE" for row in actionable),
        ):
            st.session_state[health_sel_key] = {row["location"] for row in actionable if row["status"] == "STALE"}
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
                {
                    "location": row["location"],
                    "topic": row["topic"],
                    "title": row["title"],
                    "source": "website",
                }
                for row in result["results"]
                if row["location"] in health_selected
            ]
            with st.spinner(f"Re-crawl {len(urls_to_update)} URLs..."):
                res = trigger_ingest(urls=urls_to_update)
            if res:
                st.success(f"{res['documents_crawled']} docs, {res['chunks_indexed']} chunks")
                st.session_state[health_sel_key] = set()

    for row in visible_rows:
        loc = row["location"]
        is_actionable = row["status"] in ("STALE", "REDIRECT", "DEAD")
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
                st.markdown(status_row_html(row), unsafe_allow_html=True)
            with cols[2]:
                if st.button("↻", key=f"hrec-{loc}", help="Re-crawl URL này", use_container_width=True):
                    with st.spinner(f"Re-crawl {loc[:50]}..."):
                        res = trigger_ingest(
                            urls=[
                                {
                                    "location": loc,
                                    "topic": row["topic"],
                                    "title": row["title"],
                                    "source": "website",
                                }
                            ]
                        )
                    if res:
                        st.success(f"{res['chunks_indexed']} chunks")
        else:
            st.markdown(status_row_html(row), unsafe_allow_html=True)
