from __future__ import annotations

import streamlit as st

from ui.admin.api_client import get_stats
from ui.admin.page_shell import render_page_header


def page_dashboard():
    render_page_header(
        "Dashboard",
        "Tổng quan hệ thống Knowledge Base",
    )

    stats = get_stats()
    if not stats:
        st.warning("Chưa lấy được stats. Kiểm tra backend.")
        return

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
            hide_index=True,
            use_container_width=True,
        )
