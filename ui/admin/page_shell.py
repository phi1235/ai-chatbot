from __future__ import annotations

import streamlit as st


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
    status = str(r.get("status") or "UNKNOWN")
    cls = status.lower()
    topic = r.get("topic") or "-"
    location = r.get("location") or r.get("url") or ""
    detail = r.get("detail") or r.get("notes") or r.get("error_message") or ""
    return (
        f'<div class="status-row {cls}">'
        f'  <span class="badge">{status}</span>'
        f'  <span class="topic">[{topic}]</span>'
        f'  <span class="url">{location[:90]}</span>'
        f'  <span class="detail">{detail}</span>'
        f'</div>'
    )
