from __future__ import annotations

from datetime import datetime

import httpx
import streamlit as st

from ui.admin.page_shell import render_page_header
from ui.admin.runtime import api_url, http


def get_gate_configs(kind: str | None = None, enabled: bool | None = None) -> dict | None:
    try:
        params: dict = {}
        if kind:
            params["kind"] = kind
        if enabled is not None:
            params["enabled"] = str(enabled).lower()
        r = http().get(f"{api_url()}/admin/eval-gates/configs", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch gate configs: {exc}")
        return None


def create_gate_config_api(payload: dict) -> dict | None:
    try:
        r = http().post(f"{api_url()}/admin/eval-gates/configs", json=payload)
        if r.status_code == 400:
            st.error(r.json().get("detail", "Validation error"))
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Create gate config failed: {exc}")
        return None


def patch_gate_config_api(config_id: int, updates: dict) -> dict | None:
    try:
        r = http().patch(f"{api_url()}/admin/eval-gates/configs/{config_id}", json=updates)
        if r.status_code in (400, 404):
            st.error(r.json().get("detail", "Update failed"))
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Patch gate config failed: {exc}")
        return None


def run_gate_config_api(config_id: int, trigger_source: str = "manual") -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/eval-gates/configs/{config_id}/run",
            json={"trigger_source": trigger_source},
            timeout=httpx.Timeout(600.0, connect=5.0, read=600.0),
        )
        if r.status_code == 404:
            st.error("Gate config not found.")
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Gate run failed: {exc}")
        return None


def get_gate_runs(
    config_id: int | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> dict | None:
    try:
        params: dict = {"limit": limit}
        if config_id is not None:
            params["config_id"] = config_id
        if kind:
            params["kind"] = kind
        r = http().get(f"{api_url()}/admin/eval-gates/runs", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch gate runs: {exc}")
        return None


def run_nightly_gates_api() -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/eval-gates/run-nightly",
            timeout=httpx.Timeout(600.0, connect=5.0, read=600.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Nightly gate run failed: {exc}")
        return None


def get_gate_run_triage_api(run_id: int) -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/eval-gates/runs/{run_id}/triage")
        if r.status_code == 404:
            st.error(f"Gate run #{run_id} not found.")
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch triage data: {exc}")
        return None


def get_gate_run_items_api(
    run_id: int,
    *,
    regression_class: str | None = None,
    root_cause: str | None = None,
    expected_topic: str | None = None,
    outcome: str | None = None,
) -> dict | None:
    try:
        params: dict = {}
        if regression_class:
            params["regression_class"] = regression_class
        if root_cause:
            params["root_cause"] = root_cause
        if expected_topic:
            params["expected_topic"] = expected_topic
        if outcome:
            params["outcome"] = outcome
        r = http().get(
            f"{api_url()}/admin/eval-gates/runs/{run_id}/items",
            params=params,
        )
        if r.status_code == 404:
            st.error(f"Gate run #{run_id} not found.")
            return None
        if r.status_code == 400:
            st.error(r.json().get("detail", "Invalid filter"))
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch triage items: {exc}")
        return None


def _render_regression_badge(regression_class: str) -> str:
    labels = {
        "new_fail": "NEW FAIL",
        "still_fail": "STILL FAIL",
        "new_error": "NEW ERROR",
        "still_error": "STILL ERROR",
        "improved": "IMPROVED",
        "still_pass": "STILL PASS",
    }
    return labels.get(regression_class, regression_class.upper())


def _render_outcome_badge(outcome: str) -> str:
    return {"pass": "PASS", "fail": "FAIL", "error": "ERROR"}.get(outcome, outcome.upper())


def _render_triage_item(item: dict, idx: int) -> None:
    rc = item.get("regression_class", "")
    candidate_outcome = item.get("candidate_outcome", "")
    question = item.get("question") or "(no question)"

    rc_colors = {
        "new_fail": "red",
        "still_fail": "orange",
        "new_error": "red",
        "still_error": "orange",
        "improved": "green",
        "still_pass": "green",
    }
    color = rc_colors.get(rc, "gray")
    rc_label = _render_regression_badge(rc)
    outcome_label = _render_outcome_badge(candidate_outcome)
    baseline_label = _render_outcome_badge(item.get("baseline_outcome", "none"))

    header = (
        f"{idx + 1}. :{color}[{rc_label}]  "
        f"candidate={outcome_label}  baseline={baseline_label}  ·  {question[:120]}"
    )

    with st.expander(header, expanded=rc in {"new_fail", "new_error"}):
        st.markdown(f"**Question**\n\n{question}")
        if item.get("expected_answer"):
            st.markdown(f"**Expected answer**\n\n{item['expected_answer']}")
        meta_cols = st.columns(3)
        meta_cols[0].caption(f"Root cause: {item.get('root_cause') or '—'}")
        meta_cols[1].caption(f"Expected topic: {item.get('expected_topic') or '—'}")
        meta_cols[2].caption(f"Eval case: #{item.get('eval_case_id')}")
        st.write(item)


def page_eval_gates():
    render_page_header(
        "Eval Gates",
        "Automated eval gate configs and run history",
    )

    st.caption(
        "Gate config = luật pass/fail tự động cho một nhóm eval cases. Dùng để so sánh candidate run với baseline run trước đó và phát hiện regression."
    )

    tab_configs, tab_runs, tab_triage, tab_new = st.tabs(
        ["Gate Configs", "Recent Runs", "Triage", "New Config"]
    )

    with tab_configs:
        st.subheader("Gate Configs")

        data = get_gate_configs()
        configs = (data or {}).get("configs", [])

        if not configs:
            st.info("No gate configs defined yet. Use the 'New Config' tab to add one.")
        else:
            for cfg in configs:
                cfg_id = cfg["id"]
                kind_badge = cfg["kind"].upper()
                enabled_badge = "enabled" if cfg["enabled"] else "disabled"
                col_hdr, col_toggle, col_run = st.columns([5, 2, 2])

                with col_hdr:
                    st.markdown(
                        f"**{cfg['name']}**  ·  `{kind_badge}`  ·  *{enabled_badge}*  "
                        f"·  baseline={cfg['baseline_mode']}"
                    )
                    thresholds = []
                    if cfg.get("max_pass_rate_drop") is not None:
                        thresholds.append(f"pass rate drop ≤ {cfg['max_pass_rate_drop']:.0%}")
                    if cfg.get("max_fail_count_increase") is not None:
                        thresholds.append(f"fail count increase ≤ {cfg['max_fail_count_increase']}")
                    if cfg.get("block_on_error_increase"):
                        thresholds.append("block on error increase")
                    filters = []
                    if cfg.get("root_cause"):
                        filters.append(f"root_cause={cfg['root_cause']}")
                    if cfg.get("expected_topic"):
                        filters.append(f"topic={cfg['expected_topic']}")
                    if filters:
                        st.caption("Filters: " + ", ".join(filters))
                    if thresholds:
                        st.caption("Thresholds: " + ", ".join(thresholds))

                with col_toggle:
                    new_state = not cfg["enabled"]
                    toggle_label = "Disable" if cfg["enabled"] else "Enable"
                    if st.button(toggle_label, key=f"gate-toggle-{cfg_id}"):
                        result = patch_gate_config_api(cfg_id, {"enabled": new_state})
                        if result:
                            st.rerun()

                with col_run:
                    if st.button("Run now", key=f"gate-run-{cfg_id}", type="primary"):
                        with st.spinner("Running gate..."):
                            gate_run = run_gate_config_api(cfg_id)
                        if gate_run:
                            decision = gate_run.get("decision", "error")
                            reason = gate_run.get("decision_reason", "")
                            if decision == "pass":
                                st.success(f"PASS — {reason}")
                            elif decision == "no_baseline":
                                st.warning(f"NO BASELINE — {reason}")
                            elif decision == "fail":
                                st.error(f"FAIL — {reason}")
                            else:
                                st.error(f"ERROR — {reason}")
                            st.rerun()

                st.markdown("---")

        st.subheader("Nightly Trigger")
        st.caption("Runs all enabled nightly gate configs (equivalent to nightly cron call).")
        if st.button("Run all nightly gates"):
            with st.spinner("Running nightly gates..."):
                result = run_nightly_gates_api()
            if result is not None:
                ran = result.get("ran", 0)
                any_fail = result.get("any_fail", False)
                if any_fail:
                    st.error(f"Nightly run completed: {ran} config(s) — some FAILED.")
                elif ran == 0:
                    st.info("No enabled nightly configs found.")
                else:
                    st.success(f"Nightly run completed: {ran} config(s) — all PASSED.")
                for s in result.get("summary", []):
                    decision = s.get("decision", "")
                    icon = "✓" if decision == "pass" else ("~" if decision == "no_baseline" else "✗")
                    st.caption(
                        f"{icon} config #{s.get('config_id')}  "
                        f"run #{s.get('gate_run_id')}  "
                        f"{decision.upper()}  —  {s.get('decision_reason', '')}"
                    )

    with tab_runs:
        st.subheader("Recent Gate Runs")

        col_filter_kind, col_filter_decision, col_filter_limit = st.columns(3)
        with col_filter_kind:
            filter_kind = st.selectbox("Kind", ["All", "nightly", "ci"], key="gr-kind")
        with col_filter_decision:
            filter_decision = st.selectbox(
                "Decision", ["All", "pass", "fail", "no_baseline", "error"], key="gr-decision"
            )
        with col_filter_limit:
            runs_limit = st.number_input("Limit", min_value=5, max_value=100, value=20, step=5, key="gr-limit")

        runs_data = get_gate_runs(
            kind=filter_kind if filter_kind != "All" else None,
            limit=int(runs_limit),
        )
        runs = (runs_data or {}).get("runs", [])

        if filter_decision != "All":
            runs = [r for r in runs if r.get("decision") == filter_decision]

        if not runs:
            st.info("No gate runs found.")
        else:
            for run in runs:
                decision = run.get("decision", "error")
                if decision == "pass":
                    icon = "✓ PASS"
                    color = "green"
                elif decision == "no_baseline":
                    icon = "~ NO BASELINE"
                    color = "orange"
                elif decision == "fail":
                    icon = "✗ FAIL"
                    color = "red"
                else:
                    icon = "! ERROR"
                    color = "red"

                run_at = run.get("created_at")
                run_at_str = (
                    datetime.fromtimestamp(run_at).strftime("%Y-%m-%d %H:%M")
                    if run_at else "?"
                )

                rate_drop = run.get("pass_rate_drop")
                delta_str = ""
                if rate_drop is not None:
                    pct = rate_drop * 100
                    delta_str = f"  pass rate {pct:+.1f}%"

                fail_delta = run.get("fail_count_delta")
                if fail_delta is not None and fail_delta != 0:
                    delta_str += f"  fail count {fail_delta:+d}"

                run_id = run.get("id")
                col_info, col_triage = st.columns([8, 2])
                with col_info:
                    st.markdown(
                        f"**#{run_id}** · {run.get('kind', '?')} · "
                        f"**:{color}[{icon}]** · {run_at_str}"
                        f"{delta_str}  \n"
                        f"*{run.get('decision_reason', '')}*  \n"
                        f"config={run.get('config_id')}  "
                        f"candidate={run.get('candidate_batch_id') or '—'}  "
                        f"baseline={run.get('baseline_batch_id') or '—'}  "
                        f"trigger={run.get('trigger_source', '?')}"
                    )
                with col_triage:
                    if st.button(
                        "Open triage",
                        key=f"open-triage-{run_id}",
                        help="Load triage view for this run in the Triage tab",
                    ):
                        st.session_state["eval_gate_triage_run_id"] = run_id
                        st.info(
                            f"Run #{run_id} selected. Switch to the **Triage** tab to inspect."
                        )
                st.markdown("---")

    with tab_triage:
        st.subheader("Gate Run Triage")
        st.caption(
            "Inspect failed/error cases for a gate run. "
            "Click 'Open triage' on any run in the Recent Runs tab, or enter a run ID below."
        )

        default_run_id = st.session_state.get("eval_gate_triage_run_id", "")
        triage_run_id_input = st.text_input(
            "Gate run ID",
            value=str(default_run_id) if default_run_id else "",
            placeholder="e.g. 3",
            key="triage-run-id-input",
        )

        if not triage_run_id_input.strip():
            st.info("Enter a gate run ID above, or use 'Open triage' from the Recent Runs tab.")
        else:
            try:
                triage_run_id = int(triage_run_id_input.strip())
            except ValueError:
                st.error("Run ID must be an integer.")
                triage_run_id = None

            if triage_run_id is not None:
                triage_data = get_gate_run_triage_api(triage_run_id)

                if triage_data:
                    gr = triage_data.get("gate_run") or {}
                    cfg = triage_data.get("config") or {}
                    ds = triage_data.get("decision_summary") or {}
                    c_batch = triage_data.get("candidate_batch") or {}
                    b_batch = triage_data.get("baseline_batch") or {}
                    triage_meta = triage_data.get("triage_meta") or {}
                    all_items = triage_data.get("items") or []

                    decision = gr.get("decision", "error")
                    run_at = gr.get("created_at")
                    run_at_str = (
                        datetime.fromtimestamp(run_at).strftime("%Y-%m-%d %H:%M")
                        if run_at else "?"
                    )

                    st.markdown(
                        f"**Run #{gr.get('id')}**  ·  "
                        f"config: *{cfg.get('name', '?')}* (#{cfg.get('id')})  ·  "
                        f"kind: `{gr.get('kind', '?')}`  ·  "
                        f"trigger: `{gr.get('trigger_source', '?')}`  ·  "
                        f"{run_at_str}"
                    )

                    if decision == "pass":
                        st.success(f"PASS — {ds.get('decision_reason', '')}")
                    elif decision == "no_baseline":
                        st.warning(f"NO BASELINE — {ds.get('decision_reason', '')}")
                    elif decision == "fail":
                        st.error(f"FAIL — {ds.get('decision_reason', '')}")
                    else:
                        st.error(f"ERROR — {ds.get('decision_reason', '')}")

                    with st.expander("Decision breakdown", expanded=True):
                        dcol1, dcol2, dcol3, dcol4 = st.columns(4)
                        with dcol1:
                            prd = ds.get("pass_rate_drop")
                            st.metric(
                                "Pass rate drop",
                                f"{prd * 100:+.1f}%" if prd is not None else "—",
                            )
                        with dcol2:
                            fcd = ds.get("fail_count_delta")
                            st.metric(
                                "Fail count delta",
                                f"{fcd:+d}" if fcd is not None else "—",
                            )
                        with dcol3:
                            ecd = ds.get("error_count_delta")
                            st.metric(
                                "Error count delta",
                                f"{ecd:+d}" if ecd is not None else "—",
                            )
                        with dcol4:
                            st.metric(
                                "Baseline",
                                "Yes" if ds.get("has_baseline") else "No",
                            )

                    if c_batch or b_batch:
                        with st.expander("Batch summaries", expanded=False):
                            bcol1, bcol2 = st.columns(2)
                            with bcol1:
                                st.markdown("**Candidate batch**")
                                if c_batch:
                                    cs = c_batch.get("summary") or {}
                                    st.caption(
                                        f"id={c_batch.get('id')}  "
                                        f"label={c_batch.get('label') or '—'}  "
                                        f"total={cs.get('total_cases', 0)}  "
                                        f"pass={cs.get('pass_count', 0)}  "
                                        f"fail={cs.get('fail_count', 0)}  "
                                        f"error={cs.get('error_count', 0)}  "
                                        f"pass_rate={cs.get('pass_rate', 0):.1%}"
                                    )
                                else:
                                    st.caption("—")
                            with bcol2:
                                st.markdown("**Baseline batch**")
                                if b_batch:
                                    bs = b_batch.get("summary") or {}
                                    st.caption(
                                        f"id={b_batch.get('id')}  "
                                        f"label={b_batch.get('label') or '—'}  "
                                        f"total={bs.get('total_cases', 0)}  "
                                        f"pass={bs.get('pass_count', 0)}  "
                                        f"fail={bs.get('fail_count', 0)}  "
                                        f"error={bs.get('error_count', 0)}  "
                                        f"pass_rate={bs.get('pass_rate', 0):.1%}"
                                    )
                                else:
                                    st.caption("No baseline batch.")

                    if all_items:
                        rc_counts: dict[str, int] = {}
                        for it in all_items:
                            rc = it.get("regression_class") or "unknown"
                            rc_counts[rc] = rc_counts.get(rc, 0) + 1

                        rc_order = [
                            "new_fail", "still_fail", "new_error",
                            "still_error", "improved", "still_pass",
                        ]
                        summary_parts = []
                        for rc in rc_order:
                            cnt = rc_counts.get(rc, 0)
                            if cnt:
                                summary_parts.append(f"{rc}={cnt}")
                        if summary_parts:
                            st.caption("Regression breakdown: " + "  ·  ".join(summary_parts))

                    st.markdown("**Filter cases**")
                    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
                    with fcol1:
                        regression_classes_available = sorted({
                            it.get("regression_class") for it in all_items
                            if it.get("regression_class")
                        })
                        f_rc = st.selectbox(
                            "Regression class",
                            ["All"] + regression_classes_available,
                            key=f"triage-rc-{triage_run_id}",
                        )
                    with fcol2:
                        root_causes_available = sorted({
                            it.get("root_cause") for it in all_items if it.get("root_cause")
                        })
                        f_root_cause = st.selectbox(
                            "Root cause",
                            ["All"] + root_causes_available,
                            key=f"triage-rca-{triage_run_id}",
                        )
                    with fcol3:
                        topics_available = sorted({
                            it.get("expected_topic") for it in all_items if it.get("expected_topic")
                        })
                        f_topic = st.selectbox(
                            "Expected topic",
                            ["All"] + topics_available,
                            key=f"triage-topic-{triage_run_id}",
                        )
                    with fcol4:
                        f_outcome = st.selectbox(
                            "Outcome",
                            ["All", "fail", "error", "pass"],
                            key=f"triage-outcome-{triage_run_id}",
                        )

                    filtered_data = get_gate_run_items_api(
                        triage_run_id,
                        regression_class=None if f_rc == "All" else f_rc,
                        root_cause=None if f_root_cause == "All" else f_root_cause,
                        expected_topic=None if f_topic == "All" else f_topic,
                        outcome=None if f_outcome == "All" else f_outcome,
                    )
                    filtered_items = (filtered_data or {}).get("items") or []
                    filtered_count = (filtered_data or {}).get("filtered_count", len(filtered_items))
                    total_items = (filtered_data or {}).get("total_items", len(all_items))

                    max_items = triage_meta.get("max_items")
                    if triage_meta.get("truncated") and max_items:
                        st.caption(
                            f"Triage currently shows up to {max_items} candidate cases for one gate run in this MVP."
                        )

                    st.caption(f"Showing {filtered_count} of {total_items} cases")

                    if not filtered_items:
                        st.info("No cases match the current filters.")
                    else:
                        for idx, item in enumerate(filtered_items):
                            _render_triage_item(item, idx)

    with tab_new:
        st.subheader("Create Gate Config")
        st.caption(
            "Tạo gate khi anh muốn tự động chặn regression: ví dụ nightly check cho toàn bộ active cases, "
            "hoặc CI smoke check cho một nhóm case retrieval_miss / theo topic cụ thể."
        )
        st.info(
            "Gợi ý nhanh: dùng kind=nightly cho kiểm tra định kỳ; dùng kind=ci cho bộ smoke/regression nhỏ trước merge/deploy."
        )

        with st.form("new_gate_config"):
            col_a, col_b = st.columns(2)
            with col_a:
                nc_name = st.text_input("Name *", placeholder="nightly-default")
                nc_kind = st.selectbox("Kind", ["nightly", "ci"])
                nc_enabled = st.checkbox("Enabled", value=True)
                nc_status_filter = st.selectbox("Case status filter", ["active", "archived"])
                nc_root_cause = st.text_input("Root cause filter (optional)")
                nc_expected_topic = st.text_input("Expected topic filter (optional)")
            with col_b:
                nc_limit = st.number_input(
                    "Limit cases (optional)", min_value=0, max_value=200, value=0, step=10
                )
                nc_label_template = st.text_input(
                    "Run label template (optional)", placeholder="{kind}-gate-{date}"
                )
                nc_baseline_mode = st.selectbox(
                    "Baseline mode",
                    ["previous_gate_run", "previous_batch"],
                    help=(
                        "previous_gate_run: compare against the candidate batch from the last run "
                        "of this config.  previous_batch: use the immediately prior batch."
                    ),
                )
                nc_pass_rate_drop = st.number_input(
                    "Max pass rate drop (0–1, blank = no limit)",
                    min_value=0.0, max_value=1.0, value=0.0, step=0.01, format="%.2f"
                )
                st.caption("Ví dụ 0.05 = fail nếu pass rate giảm hơn 5% so với baseline.")
                nc_fail_count_increase = st.number_input(
                    "Max fail count increase (blank = no limit)",
                    min_value=0, max_value=500, value=0, step=1
                )
                st.caption("Ví dụ 2 = fail nếu số case fail tăng hơn 2 so với baseline.")
                nc_block_error = st.checkbox("Block on error count increase", value=False)

            submitted = st.form_submit_button("Create config", type="primary")
            if submitted:
                if not nc_name.strip():
                    st.error("Name is required.")
                else:
                    payload: dict = {
                        "name": nc_name.strip(),
                        "kind": nc_kind,
                        "enabled": nc_enabled,
                        "status_filter": nc_status_filter,
                        "baseline_mode": nc_baseline_mode,
                        "block_on_error_increase": nc_block_error,
                    }
                    if nc_root_cause.strip():
                        payload["root_cause"] = nc_root_cause.strip()
                    if nc_expected_topic.strip():
                        payload["expected_topic"] = nc_expected_topic.strip()
                    if nc_limit > 0:
                        payload["limit_cases"] = int(nc_limit)
                    if nc_label_template.strip():
                        payload["run_label_template"] = nc_label_template.strip()
                    if nc_pass_rate_drop > 0:
                        payload["max_pass_rate_drop"] = nc_pass_rate_drop
                    if nc_fail_count_increase > 0:
                        payload["max_fail_count_increase"] = int(nc_fail_count_increase)

                    result = create_gate_config_api(payload)
                    if result:
                        st.success(f"Gate config '{result['name']}' created (id={result['id']}).")
                        st.rerun()
