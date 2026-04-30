from __future__ import annotations

import streamlit as st

from ui.admin.api_client import clear_cache, rebuild_bm25
from ui.admin.page_shell import render_page_header


def page_maintenance():
    render_page_header(
        "Maintenance",
        "Bảo trì cache, BM25 index, reset hệ thống",
    )

    cols = st.columns(2, gap="medium")

    with cols[0]:
        st.markdown('<div class="card-title">Answer Cache</div>', unsafe_allow_html=True)
        st.caption("Xoá cache câu trả lời. Lần hỏi tiếp theo sẽ gọi LLM lại.")
        if st.button("Clear cache", use_container_width=True) and clear_cache():
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
