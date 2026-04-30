from __future__ import annotations

from datetime import datetime

import streamlit as st

from ui.admin.api_client import (
    action_coverage_gap,
    get_coverage_gap_cluster_detail,
    get_coverage_gap_clusters,
    get_coverage_gaps,
    review_coverage_gap,
)
from ui.admin.page_shell import render_page_header


def _render_cluster_view(raw_items: list[dict]):
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

    for cluster in clusters:
        cluster_key = cluster["cluster_key"]
        count = cluster["count"]
        topic_text = cluster.get("detected_topic") or "-"
        rep_question = cluster.get("representative_question") or cluster_key
        latest_ts = cluster.get("latest_created_at")
        latest_str = datetime.fromtimestamp(latest_ts).strftime("%d/%m %H:%M") if latest_ts else "-"

        statuses = cluster.get("statuses", {})
        status_text = ", ".join(f"{status}: {cnt}" for status, cnt in statuses.items()) if statuses else "-"

        resolutions = cluster.get("resolutions", {})
        resolution_text = ", ".join(f"{res}: {cnt}" for res, cnt in resolutions.items()) if resolutions else "-"

        label = f"[x{count}] {rep_question[:80]}"
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
                f'<b>Resolutions:</b> {resolution_text}</div>'
            )
            st.markdown(info_html, unsafe_allow_html=True)
            st.markdown(f"**Representative question:** {rep_question}")

            recommendation = cluster.get("recommendation")
            if recommendation:
                rec_action = recommendation.get("recommended_action", "review_only")
                rec_reason = recommendation.get("recommendation_reason", "")
                rec_topic = recommendation.get("candidate_topic", "")
                rec_query = recommendation.get("suggested_search_query", "")
                rec_priority = recommendation.get("priority", "low")
                rec_signals = recommendation.get("signals", [])

                action_colors = {
                    "add_source": ("var(--warn)", "#fef3c7"),
                    "recrawl": ("var(--accent)", "var(--accent-soft)"),
                    "review_only": ("var(--text-muted)", "#f3f4f6"),
                }
                a_color, a_bg = action_colors.get(rec_action, ("var(--text-muted)", "#f3f4f6"))
                priority_labels = {
                    "high": ("HIGH", "var(--danger)", "#fee2e2"),
                    "medium": ("MED", "var(--warn)", "#fef3c7"),
                    "low": ("LOW", "var(--text-subtle)", "#f3f4f6"),
                }
                p_label, p_color, p_bg = priority_labels.get(
                    rec_priority,
                    ("LOW", "var(--text-subtle)", "#f3f4f6"),
                )

                rec_html = (
                    f'<div style="border:1px solid var(--border); border-radius:8px; '
                    f'padding:0.8rem 1rem; margin:0.5rem 0 0.8rem; background:var(--surface);">'
                    f'<div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.4rem;">'
                    f'<span style="font-weight:600; font-size:0.82rem; color:{a_color}; '
                    f'background:{a_bg}; padding:0.15rem 0.5rem; border-radius:4px;">'
                    f'{rec_action.upper().replace("_", " ")}</span>'
                    f'<span style="font-weight:600; font-size:0.68rem; color:{p_color}; '
                    f'background:{p_bg}; padding:0.1rem 0.4rem; border-radius:3px;">'
                    f'{p_label}</span>'
                    f'<span style="color:var(--text-subtle); font-size:0.72rem;">Recommendation</span>'
                    f'</div>'
                    f'<div style="font-size:0.82rem; color:var(--text); margin-bottom:0.3rem;">{rec_reason}</div>'
                )
                if rec_topic:
                    rec_html += (
                        f'<div style="font-size:0.78rem; color:var(--text-muted);">'
                        f'<b>Topic:</b> {rec_topic}</div>'
                    )
                if rec_query:
                    rec_html += (
                        f'<div style="font-size:0.78rem; color:var(--text-muted);">'
                        f'<b>Search query:</b> <code>{rec_query}</code></div>'
                    )
                if rec_signals:
                    rec_html += (
                        f'<div style="font-size:0.72rem; color:var(--text-subtle); margin-top:0.2rem;">'
                        f'Signals: {", ".join(rec_signals)}</div>'
                    )
                rec_html += "</div>"
                st.markdown(rec_html, unsafe_allow_html=True)

            if st.button("Xem gaps trong cluster", key=f"cl-drill-{cluster_key}"):
                st.session_state[f"cl_expand_{cluster_key}"] = True

            if st.session_state.get(f"cl_expand_{cluster_key}"):
                detail = get_coverage_gap_cluster_detail(cluster_key, limit=20)
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

    cols = st.columns(5)
    cols[0].metric("Tổng gaps", summary.get("total", 0))
    cols[1].metric("New", summary.get("total_new", 0))
    cols[2].metric("Reviewed", summary.get("total_reviewed", 0))
    cols[3].metric("Actioned", summary.get("total_actioned", 0))
    cols[4].metric("Ignored", summary.get("total_ignored", 0))

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
                for resolution, cnt in by_resolution.items():
                    st.text(f"  {resolution}: {cnt}")

    st.markdown("&nbsp;")

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

    fcols = st.columns([1, 1, 1, 1, 1])
    with fcols[0]:
        filter_status = st.selectbox(
            "Status",
            options=["Tất cả", "new", "reviewed", "actioned", "ignored"],
            key="cg_filter_status",
            label_visibility="collapsed",
        )
    with fcols[1]:
        all_topics = sorted({it.get("detected_topic") or "" for it in items} - {""})
        filter_topic = st.selectbox(
            "Topic",
            options=["Tất cả"] + all_topics,
            key="cg_filter_topic",
            label_visibility="collapsed",
        )
    with fcols[2]:
        filter_resolution = st.selectbox(
            "Resolution",
            options=[
                "Tất cả",
                "add_source",
                "recrawl",
                "out_of_scope",
                "duplicate",
                "retrieval_tuning",
                "prompt_tuning",
            ],
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

    ft_status = filter_status if filter_status != "Tất cả" else None
    ft_topic = filter_topic if filter_topic != "Tất cả" else None
    ft_resolution = filter_resolution if filter_resolution != "Tất cả" else None
    if ft_status or ft_topic or ft_resolution or filter_limit != 50:
        data = get_coverage_gaps(
            status=ft_status,
            detected_topic=ft_topic,
            resolution=ft_resolution,
            limit=filter_limit,
        )
        if not data:
            return
        items = data.get("items", [])

    if not items:
        st.info("Không có coverage gap nào phù hợp bộ lọc.")
        return

    st.caption(f"Hiển thị {len(items)} gaps")

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
                excerpt = item["answer_excerpt"]
                st.text(excerpt[:300] + ("..." if len(excerpt) > 300 else ""))

            citations = item.get("citations_snapshot", [])
            if citations:
                st.markdown("**Citations:**")
                for citation in citations[:5]:
                    score_text = f" (score: {citation['score']:.2f})" if citation.get("score") is not None else ""
                    st.text(f"  - {citation.get('title', '-')}{score_text}")

            if item.get("session_id"):
                st.caption(f"Session: {item['session_id'][:8]}")

            if item.get("resolution"):
                note_text = f" — {item['review_note']}" if item.get("review_note") else ""
                st.success(f"Resolution: {item['resolution']}{note_text}")

            if gap_status == "actioned" and item.get("action_payload"):
                action_payload = item["action_payload"]
                actioned_time = ""
                if item.get("actioned_at"):
                    actioned_time = datetime.fromtimestamp(item["actioned_at"]).strftime("%d/%m %H:%M")
                action_result = action_payload.get("result", {})
                st.markdown(f"**Action:** {item.get('resolution', '-')} · {actioned_time}")
                if item["resolution"] == "add_source":
                    st.text(f"  URL: {action_payload.get('url', '-')}")
                    st.text(f"  Topic: {action_payload.get('topic', '-')}")
                    if action_payload.get("title"):
                        st.text(f"  Title: {action_payload['title']}")
                elif item["resolution"] == "recrawl":
                    if action_payload.get("topic"):
                        st.text(f"  Topic: {action_payload['topic']}")
                    if action_payload.get("urls"):
                        st.text(f"  URLs: {len(action_payload['urls'])} target(s)")
                    if action_result.get("documents_crawled") is not None:
                        st.text(
                            f"  Result: {action_result.get('documents_crawled', 0)} docs, "
                            f"{action_result.get('chunks_indexed', 0)} chunks"
                        )
            elif gap_status != "new" and item.get("review_note"):
                st.info(f"Note: {item['review_note']}")

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
                                "(none)",
                                "add_source",
                                "recrawl",
                                "out_of_scope",
                                "duplicate",
                                "retrieval_tuning",
                                "prompt_tuning",
                            ],
                            key=f"cg-resolution-{gap_id}",
                        )
                    if st.form_submit_button("Đánh dấu", type="primary"):
                        resolution_value = resolution_input if resolution_input != "(none)" else None
                        result = review_coverage_gap(
                            gap_id,
                            status=status_input,
                            resolution=resolution_value,
                            review_note=note_input,
                        )
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
                            action_topic = st.text_input(
                                "Topic",
                                value=default_topic,
                                placeholder="vd: kubernetes",
                                key=f"cg-a-topic-{gap_id}",
                            )
                            action_url = st.text_input(
                                "URL",
                                placeholder="https://docs.example.com/...",
                                key=f"cg-a-url-{gap_id}",
                            )
                            action_title = st.text_input(
                                "Title (optional)",
                                placeholder="Tiêu đề nguồn",
                                key=f"cg-a-title-{gap_id}",
                            )
                            action_note = st.text_input(
                                "Note (optional)",
                                placeholder="Ghi chú",
                                key=f"cg-a-note-{gap_id}",
                            )
                            if st.form_submit_button("Add source", type="primary"):
                                if not action_url.strip():
                                    st.error("Cần nhập URL.")
                                elif not action_topic.strip():
                                    st.error("Cần nhập topic.")
                                else:
                                    with st.spinner("Đang thêm source..."):
                                        result = action_coverage_gap(
                                            gap_id,
                                            resolution="add_source",
                                            action_payload={
                                                "topic": action_topic.strip(),
                                                "url": action_url.strip(),
                                                "title": action_title.strip(),
                                            },
                                            review_note=action_note.strip(),
                                        )
                                    if result:
                                        st.success("Đã thêm source và đánh dấu actioned!")
                                        st.rerun()

                    elif action_type == "recrawl":
                        with st.form(key=f"cg-action-recrawl-{gap_id}"):
                            default_topic = item.get("detected_topic") or ""
                            recrawl_topic = st.text_input(
                                "Recrawl topic",
                                value=default_topic,
                                placeholder="Topic cần recrawl (recrawl toàn bộ topic)",
                                key=f"cg-r-topic-{gap_id}",
                            )
                            recrawl_urls = st.text_area(
                                "Hoặc URLs cụ thể (mỗi dòng 1 URL)",
                                placeholder="https://docs.example.com/page1\nhttps://docs.example.com/page2",
                                height=80,
                                key=f"cg-r-urls-{gap_id}",
                            )
                            recrawl_note = st.text_input(
                                "Note (optional)",
                                placeholder="Ghi chú",
                                key=f"cg-r-note-{gap_id}",
                            )
                            if st.form_submit_button("Recrawl", type="primary"):
                                url_list = [
                                    url.strip()
                                    for url in (recrawl_urls or "").splitlines()
                                    if url.strip() and not url.strip().startswith("#")
                                ]
                                if not recrawl_topic.strip() and not url_list:
                                    st.error("Cần nhập topic hoặc ít nhất 1 URL.")
                                else:
                                    payload: dict = {}
                                    if recrawl_topic.strip():
                                        payload["topic"] = recrawl_topic.strip()
                                    if url_list:
                                        payload["urls"] = url_list
                                    with st.spinner("Đang recrawl..."):
                                        result = action_coverage_gap(
                                            gap_id,
                                            resolution="recrawl",
                                            action_payload=payload,
                                            review_note=recrawl_note.strip(),
                                        )
                                    if result:
                                        action_result = result.get("action_result", {})
                                        st.success(
                                            f"Recrawl xong: {action_result.get('documents_crawled', 0)} docs, "
                                            f"{action_result.get('chunks_indexed', 0)} chunks. Gap đã actioned!"
                                        )
                                        st.rerun()
