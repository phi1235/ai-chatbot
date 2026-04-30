"""Admin Portal — quản trị KB, sources, sessions, cache.

Truy cập: http://localhost:8501/Admin
Backend endpoints dưới /admin/* (api/admin.py).
"""
from __future__ import annotations

import streamlit as st

from ui.admin.api_client import check_backend
from ui.admin.pages import (
    page_coverage_gaps,
    page_dashboard,
    page_eval_cases,
    page_eval_gates,
    page_feedback,
    page_feedback_actions,
    page_freshness_center,
    page_health,
    page_maintenance,
    page_sessions,
    page_sources,
)
from ui.admin.runtime import api_url
from ui.admin.styles import apply_styles

st.set_page_config(
    page_title="Admin · AI Knowledge Assistant",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_styles()

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
            "Eval Gates",
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
        f"{api_url()}</div>",
        unsafe_allow_html=True,
    )

PAGE_RENDERERS = {
    "Dashboard": page_dashboard,
    "Sources": page_sources,
    "Health Check": page_health,
    "Freshness Center": page_freshness_center,
    "Coverage Gaps": page_coverage_gaps,
    "Feedback": page_feedback,
    "Action Queue": page_feedback_actions,
    "Eval Cases": page_eval_cases,
    "Eval Gates": page_eval_gates,
    "Sessions": page_sessions,
    "Maintenance": page_maintenance,
}

if not backend_ok:
    st.error(f"Không kết nối được backend tại {api_url()}. Khởi động backend rồi refresh.")
else:
    PAGE_RENDERERS[page]()
