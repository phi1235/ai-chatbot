from __future__ import annotations

from datetime import datetime

import streamlit as st

from ui.admin.api_client import (
    batch_recrawl,
    get_freshness,
    get_scheduler_status,
    get_sources,
    run_health,
    run_scheduler_now,
    update_scheduler_config,
)
from ui.admin.page_shell import render_page_header, status_row_html


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
                format_func=lambda value: {
                    300: "5 phút",
                    900: "15 phút",
                    1800: "30 phút",
                    3600: "1 giờ",
                    7200: "2 giờ",
                    21600: "6 giờ",
                    43200: "12 giờ",
                    86400: "24 giờ",
                }[value],
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
            if scheduler_last_run
            else "-",
        )
        info_cols[3].metric(
            "Next run",
            datetime.fromtimestamp(float(scheduler_next_run)).strftime("%Y-%m-%d %H:%M:%S")
            if scheduler_next_run
            else "-",
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
    selected_urls = set(st.session_state[sel_key])

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
                row["url"]
                for row in records
                if row.get("status") in {"STALE", "DEAD", "ERROR", "REDIRECT"} and row.get("url")
            }
            st.rerun()
    with toolbar_cols[1]:
        if st.button("Chọn tất cả", use_container_width=True):
            st.session_state[sel_key] = {row["url"] for row in records if row.get("url")}
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
        },
    )

    updated_selection = {row.get("_url", "") for row in edited if row.get("Chọn") and row.get("_url")}
    if updated_selection != set(st.session_state[sel_key]):
        st.session_state[sel_key] = updated_selection

    with st.expander("Chi tiết records", expanded=False):
        for row in records:
            st.markdown(status_row_html(row), unsafe_allow_html=True)
