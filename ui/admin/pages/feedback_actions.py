from __future__ import annotations

from datetime import datetime

import streamlit as st

from ui.admin.api_client import (
    execute_feedback_action,
    get_feedback_actions,
    update_feedback_action_status,
)
from ui.admin.page_shell import render_page_header


def page_feedback_actions():
    render_page_header(
        "Action Queue",
        "Track and execute follow-up actions derived from reviewed feedback",
    )

    data = get_feedback_actions(limit=200)
    if not data:
        st.info("No action items yet.")
        return

    items = data.get("items", [])
    summary = data.get("summary", {})

    cols = st.columns(4)
    cols[0].metric("Total", summary.get("total", len(items)))
    cols[1].metric("Open", summary.get("open", 0))
    cols[2].metric("In progress", summary.get("in_progress", 0))
    cols[3].metric("Done", summary.get("done", 0))

    if not items:
        st.info("No action items yet.")
        return

    for item in items:
        created = datetime.fromtimestamp(item["created_at"]).strftime("%d/%m %H:%M")
        updated = datetime.fromtimestamp(item["updated_at"]).strftime("%d/%m %H:%M")
        header = (
            f"Action #{item['id']} · feedback #{item.get('feedback_id')} · "
            f"{item.get('status', 'open')} · {created}"
        )
        with st.expander(header, expanded=item.get("status") in {"open", "in_progress"}):
            st.caption(f"Updated: {updated}")
            st.write(item)

            with st.form(f"action-status-{item['id']}"):
                status = st.selectbox(
                    "Status",
                    ["open", "in_progress", "done", "wont_do"],
                    index=["open", "in_progress", "done", "wont_do"].index(item.get("status", "open")) if item.get("status", "open") in ["open", "in_progress", "done", "wont_do"] else 0,
                )
                owner_note = st.text_area("Owner note", value=item.get("owner_note") or "", height=80)
                c1, c2 = st.columns(2)
                submitted = c1.form_submit_button("Update status", type="primary", use_container_width=True)
                execute_now = c2.form_submit_button("Execute", use_container_width=True)

            if submitted:
                result = update_feedback_action_status(item["id"], status=status, owner_note=owner_note or None)
                if result:
                    st.success("Status updated.")
                    st.rerun()
            if execute_now:
                result = execute_feedback_action(item["id"])
                if result is not None:
                    st.success("Execution request completed.")
                    st.rerun()
