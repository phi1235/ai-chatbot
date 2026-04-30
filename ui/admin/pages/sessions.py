from __future__ import annotations

import streamlit as st

from ui.admin.api_client import delete_session, get_sessions
from ui.admin.page_shell import render_page_header


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

    for session in sessions:
        cols = st.columns([4, 2, 2, 1])
        cols[0].markdown(f"**{session['title']}**")
        cols[1].caption(f"{session['message_count']} tin nhắn")
        cols[2].caption(session["id"][:8])
        with cols[3]:
            if st.button("Xoá", key=f"delsess-{session['id']}"):
                if delete_session(session["id"]):
                    st.rerun()
