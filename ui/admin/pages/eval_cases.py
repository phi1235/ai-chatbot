from __future__ import annotations

from datetime import datetime

import httpx
import streamlit as st

from ui.admin.page_shell import render_page_header
from ui.admin.runtime import api_url, http


def create_eval_case(feedback_id: int) -> dict | None:
    try:
        r = http().post(f"{api_url()}/admin/feedback/{feedback_id}/eval-case")
        if r.status_code == 409:
            st.warning(r.json().get("detail", "Active eval case already exists for this feedback."))
            return None
        if r.status_code == 400:
            st.warning(r.json().get("detail", "Cannot create eval case."))
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Create eval case failed: {exc}")
        return None


def get_eval_cases(
    status: str | None = None,
    root_cause: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if root_cause:
            params["root_cause"] = root_cause
        r = http().get(f"{api_url()}/admin/eval-cases", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch eval cases: {exc}")
        return None


def get_eval_cases_summary() -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/eval-cases/summary")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch eval cases summary: {exc}")
        return None


def run_eval_case(case_id: int) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/eval-cases/{case_id}/run",
            timeout=httpx.Timeout(120.0, connect=5.0, read=120.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Run eval case failed: {exc}")
        return None


def get_eval_case_runs(case_id: int, limit: int = 10) -> dict | None:
    try:
        r = http().get(
            f"{api_url()}/admin/eval-cases/{case_id}/runs",
            params={"limit": limit},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch runs: {exc}")
        return None


def archive_eval_case(case_id: int) -> dict | None:
    try:
        r = http().patch(
            f"{api_url()}/admin/eval-cases/{case_id}/status",
            json={"status": "archived"},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Archive failed: {exc}")
        return None


def run_eval_batch(
    label: str | None = None,
    root_cause: str | None = None,
    expected_topic: str | None = None,
    limit: int | None = None,
) -> dict | None:
    try:
        body: dict = {}
        if label:
            body["label"] = label
        if root_cause:
            body["root_cause"] = root_cause
        if expected_topic:
            body["expected_topic"] = expected_topic
        if limit:
            body["limit"] = limit
        r = http().post(
            f"{api_url()}/admin/eval-cases/run-batch",
            json=body,
            timeout=httpx.Timeout(600.0, connect=5.0, read=600.0),
        )
        if r.status_code == 400:
            st.warning(r.json().get("detail", "No matching eval cases found."))
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Batch run failed: {exc}")
        return None


def get_eval_batches(limit: int = 10, offset: int = 0) -> dict | None:
    try:
        r = http().get(
            f"{api_url()}/admin/eval-batches",
            params={"limit": limit, "offset": offset},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch eval batches: {exc}")
        return None


def get_eval_batch_detail(batch_id: int) -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/eval-batches/{batch_id}")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch batch detail: {exc}")
        return None


def get_eval_batch_items(batch_id: int, limit: int = 200) -> dict | None:
    try:
        r = http().get(
            f"{api_url()}/admin/eval-batches/{batch_id}/items",
            params={"limit": limit},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch batch items: {exc}")
        return None


def get_eval_batches_compare(candidate_batch_id: int, baseline_batch_id: int | None = None) -> dict | None:
    try:
        params: dict = {"candidate_batch_id": candidate_batch_id}
        if baseline_batch_id is not None:
            params["baseline_batch_id"] = baseline_batch_id
        r = http().get(f"{api_url()}/admin/eval-batches/compare", params=params)
        if r.status_code == 400:
            st.warning(r.json().get("detail", "Cannot compare these batches."))
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Compare failed: {exc}")
        return None


def get_eval_batches_trend_data(limit: int = 10) -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/eval-batches/trend", params={"limit": limit})
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch trend data: {exc}")
        return None


def page_eval_cases():
    render_page_header(
        "Eval Cases",
        "Regression quality cases derived from reviewed feedback",
    )

    st.caption(
        "Flow: user gửi feedback → admin review/classify → tạo eval case từ feedback đã review → chạy single case hoặc batch."
    )

    summary = get_eval_cases_summary()
    if summary:
        c = st.columns(4)
        c[0].metric("Active cases", summary.get("total_active", 0))
        c[1].metric("Archived", summary.get("total_archived", 0))
        lr = summary.get("latest_runs", {})
        c[2].metric("Latest pass", lr.get("pass", 0))
        c[3].metric("Latest fail", lr.get("fail", 0))

    st.markdown("&nbsp;")

    with st.expander("Create eval case from reviewed feedback", expanded=False):
        st.caption(
            "Enter a reviewed feedback ID to create an eval case. "
            "The feedback must have been reviewed (not pending)."
        )
        with st.form("create-eval-case-form"):
            fb_id_input = st.number_input(
                "Feedback ID",
                min_value=1,
                step=1,
                key="ec-create-fb-id",
            )
            submitted = st.form_submit_button("Create eval case", type="primary")
        if submitted:
            result = create_eval_case(int(fb_id_input))
            if result:
                st.success(
                    f"Eval case #{result['id']} created for feedback #{result['feedback_id']}."
                )
                st.rerun()

    st.markdown("---")
    st.markdown("**Batch Run**")
    st.caption(
        "Run nhiều active eval cases cùng lúc để xem pass/fail rate sau một thay đổi retrieval/prompt/model."
    )

    with st.form("eval-batch-run-form"):
        bcols = st.columns([3, 2, 2, 1])
        with bcols[0]:
            batch_label = st.text_input(
                "Label (optional)",
                placeholder="e.g. Post-retrieval-tuning check",
                key="eb-label",
            )
        with bcols[1]:
            batch_rc = st.text_input(
                "Root cause filter",
                placeholder="e.g. retrieval_miss",
                key="eb-rc",
            )
        with bcols[2]:
            batch_topic = st.text_input(
                "Expected topic filter",
                placeholder="e.g. kubernetes",
                key="eb-topic",
            )
        with bcols[3]:
            batch_limit = st.number_input(
                "Limit",
                min_value=0,
                max_value=500,
                value=0,
                step=10,
                key="eb-limit",
            )
        batch_submit = st.form_submit_button("Run batch", type="primary")
    if batch_submit:
        result = run_eval_batch(
            label=batch_label or None,
            root_cause=batch_rc.strip() or None,
            expected_topic=batch_topic.strip() or None,
            limit=int(batch_limit) if batch_limit > 0 else None,
        )
        if result:
            summary = result.get("summary") or {}
            st.success(
                f"Batch #{result['id']} done · total={summary.get('total_cases', 0)} · "
                f"pass={summary.get('pass_count', 0)} · fail={summary.get('fail_count', 0)} · "
                f"error={summary.get('error_count', 0)} · pass_rate={summary.get('pass_rate', 0):.1%}"
            )
            st.rerun()

    st.markdown("---")
    st.markdown("**Eval Cases**")
    data = get_eval_cases(limit=200)
    items = (data or {}).get("items", [])
    if not items:
        st.info(
            "No eval cases yet. Review user feedback first, then create eval cases from reviewed feedback."
        )
    else:
        for item in items:
            header = f"Case #{item['id']} · {item.get('status', 'active')} · {item.get('root_cause') or '-'}"
            with st.expander(header, expanded=False):
                st.markdown(f"**Question**\n\n{item.get('question') or ''}")
                st.markdown(f"**Expected answer**\n\n{item.get('expected_answer') or ''}")
                st.caption(f"Expected topic: {item.get('expected_topic') or '—'}")

                latest_run = item.get("latest_run") or {}
                if latest_run:
                    run_time = datetime.fromtimestamp(latest_run["run_at"]).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                    st.caption(
                        f"Latest run: {latest_run.get('outcome', '?').upper()} at {run_time}"
                    )

                c1, c2 = st.columns(2)
                if c1.button("Run case", key=f"run-case-{item['id']}", type="primary"):
                    result = run_eval_case(item["id"])
                    if result:
                        st.success(f"Outcome: {result.get('outcome', '?').upper()}")
                        st.rerun()
                if c2.button("Archive", key=f"archive-case-{item['id']}"):
                    result = archive_eval_case(item["id"])
                    if result:
                        st.success("Archived.")
                        st.rerun()

                runs = get_eval_case_runs(item["id"], limit=10)
                run_items = (runs or {}).get("items", [])
                if run_items:
                    st.markdown("**Recent runs**")
                    for run in run_items:
                        run_time = datetime.fromtimestamp(run["run_at"]).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                        st.caption(
                            f"#{run['id']} · {run.get('outcome', '?').upper()} · {run_time}"
                        )

    st.markdown("---")
    st.markdown("**Recent batches**")
    batches_data = get_eval_batches(limit=20)
    batches = (batches_data or {}).get("items", [])
    if batches:
        batch_options = {
            f"Batch #{b['id']} · {b.get('label') or '—'} · {datetime.fromtimestamp(b['created_at']).strftime('%Y-%m-%d %H:%M')}": b["id"]
            for b in batches
        }
        selected_batch_label = st.selectbox("Inspect batch", list(batch_options.keys()), key="inspect-batch")
        selected_batch_id = batch_options[selected_batch_label]
        batch_detail = get_eval_batch_detail(selected_batch_id)
        if batch_detail:
            summary = batch_detail.get("summary") or {}
            cols = st.columns(4)
            cols[0].metric("Total", summary.get("total_cases", 0))
            cols[1].metric("Pass", summary.get("pass_count", 0))
            cols[2].metric("Fail", summary.get("fail_count", 0))
            cols[3].metric("Error", summary.get("error_count", 0))
            items_data = get_eval_batch_items(selected_batch_id, limit=200)
            batch_items = (items_data or {}).get("items", [])
            for item in batch_items[:50]:
                created = datetime.fromtimestamp(item["created_at"]).strftime("%Y-%m-%d %H:%M")
                st.caption(
                    f"Case #{item.get('eval_case_id')} · {item.get('outcome', '?').upper()} · {created}"
                )
    else:
        st.info("No eval batches yet.")

    st.markdown("---")
    st.markdown("**Compare batches**")
    if len(batches) >= 1:
        labels = list(batch_options.keys()) if batches else []
        ccols = st.columns(2)
        candidate_label = ccols[0].selectbox("Candidate batch", labels, key="cmp-candidate") if labels else None
        baseline_candidates = ["Auto previous batch"] + labels if labels else []
        baseline_label = ccols[1].selectbox("Baseline batch", baseline_candidates, key="cmp-baseline") if baseline_candidates else None
        if st.button("Compare batches") and candidate_label:
            candidate_id = batch_options[candidate_label]
            baseline_id = None if baseline_label == "Auto previous batch" else batch_options.get(baseline_label)
            compare = get_eval_batches_compare(candidate_id, baseline_id)
            if compare:
                st.write(compare)

    st.markdown("---")
    st.markdown("**Trend**")
    trend_data = get_eval_batches_trend_data(limit=10)
    trend_items = (trend_data or {}).get("items", [])
    if trend_items:
        st.line_chart(
            {
                "pass_rate": [it.get("pass_rate", 0) for it in trend_items],
                "fail_count": [it.get("fail_count", 0) for it in trend_items],
            }
        )
    else:
        st.info("No trend data yet.")
