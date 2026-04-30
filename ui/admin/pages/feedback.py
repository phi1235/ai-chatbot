from __future__ import annotations

from datetime import datetime

import streamlit as st

from ui.admin.api_client import (
    create_feedback_action_item,
    get_feedback_list,
    review_feedback_item,
)
from ui.admin.page_shell import render_page_header

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

    st.session_state.pop("feedback_fetch_failed", None)
    data = get_feedback_list(limit=200)
    if not data:
        if st.session_state.get("feedback_fetch_failed"):
            st.warning(
                "Feedback API đang lỗi hoặc không đọc được DB. "
                "Đây không phải trạng thái 'không có dữ liệu'."
            )
        else:
            st.info("No feedback yet.")
        return

    summary = data.get("summary", {})
    items = data.get("items", [])

    cols = st.columns(4)
    cols[0].metric("Total feedback", summary.get("total", 0))
    cols[1].metric("Down (pending)", summary.get("down_pending", 0))
    cols[2].metric("Reviewed", summary.get("reviewed", 0))
    cols[3].metric("Up / Down", f"{summary.get('total_up', 0)} / {summary.get('total_down', 0)}")

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
                st.caption("No topic signals yet.")

    st.markdown("---")

    if not items:
        st.info("No feedback yet.")
        return

    for item in items:
        ftype = item["feedback_type"]
        emoji = "👎" if ftype == "down" else "👍"
        status = item.get("review_status", "pending")
        rc = item.get("root_cause") or "-"
        created = datetime.fromtimestamp(item["created_at"]).strftime("%d/%m %H:%M")

        header = f"{emoji} Feedback #{item['id']} · {created} · status={status} · root_cause={rc}"
        with st.expander(header, expanded=(ftype == "down" and status == "pending")):
            st.markdown(f"**Question**\n\n{item['question']}")
            st.markdown(f"**Answer**\n\n{item['answer']}")

            if item.get("note"):
                st.markdown(f"**User note**\n\n{item['note']}")

            dbg = st.columns(3)
            dbg[0].caption(f"Topic: {item.get('detected_topic') or '—'}")
            dbg[1].caption(f"Retrieval count: {item.get('retrieval_count') if item.get('retrieval_count') is not None else '—'}")
            dbg[2].caption(f"Reviewed: {'yes' if item.get('reviewed') else 'no'}")

            with st.expander("Debug snapshot", expanded=False):
                st.write({
                    "rewritten_query": item.get("rewritten_query"),
                    "citations_snapshot": item.get("citations_snapshot", []),
                    "trace_snapshot": item.get("trace_snapshot", {}),
                })

            st.markdown("---")
            st.markdown("**Review & classify**")
            with st.form(f"review-feedback-{item['id']}"):
                review_status = st.selectbox(
                    "Review status",
                    ["pending", "reviewed", "actioned"],
                    index=["pending", "reviewed", "actioned"].index(item.get("review_status", "pending")),
                    key=f"review-status-{item['id']}",
                )
                root_cause = st.selectbox(
                    "Root cause",
                    ["", *list(_ROOT_CAUSE_LABELS.keys())],
                    index=(["", *list(_ROOT_CAUSE_LABELS.keys())].index(item.get("root_cause") or "") if (item.get("root_cause") or "") in ["", *list(_ROOT_CAUSE_LABELS.keys())] else 0),
                    format_func=lambda v: "—" if v == "" else _ROOT_CAUSE_LABELS.get(v, v),
                    key=f"root-cause-{item['id']}",
                )
                review_note = st.text_area(
                    "Review note",
                    value=item.get("review_note") or "",
                    key=f"review-note-{item['id']}",
                    height=100,
                )
                c1, c2 = st.columns(2)
                submitted = c1.form_submit_button("Save review", type="primary", use_container_width=True)
                create_action = c2.form_submit_button("Create action item", use_container_width=True)

            if submitted:
                result = review_feedback_item(
                    item["id"],
                    review_note=review_note,
                    review_status=review_status,
                    root_cause=root_cause or None,
                )
                if result:
                    st.success("Review saved.")
                    st.rerun()

            if create_action:
                result = create_feedback_action_item(item["id"])
                if result:
                    st.success(f"Created action item #{result['id']}.")
                    st.rerun()
