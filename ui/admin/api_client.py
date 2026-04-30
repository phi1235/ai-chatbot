from __future__ import annotations

import httpx
import streamlit as st

from .runtime import api_url, http


def get_sources() -> list[dict]:
    try:
        r = http().get(f"{api_url()}/admin/sources")
        r.raise_for_status()
        return r.json().get("topics", [])
    except Exception as exc:
        st.error(f"Không lấy được sources: {exc}")
        return []


def add_url(topic: str, location: str, title: str = "") -> tuple[bool, str]:
    try:
        r = http().post(
            f"{api_url()}/admin/sources/{topic}",
            json={"location": location, "topic": topic, "title": title or location, "source": "website"},
        )
        if r.status_code == 200:
            return True, f"Đã thêm vào {topic}"
        return False, r.json().get("detail", r.text)
    except Exception as exc:
        return False, str(exc)


def delete_url(topic: str, location: str) -> bool:
    try:
        r = http().request(
            "DELETE",
            f"{api_url()}/admin/sources/{topic}",
            json={"location": location},
        )
        return r.status_code == 200
    except Exception:
        return False


def trigger_ingest(topic: str | None = None, urls: list[dict] | None = None, reset: bool = False) -> dict | None:
    try:
        body: dict = {"reset": reset}
        if topic:
            body["topic"] = topic
        if urls:
            body["urls"] = urls
        r = http().post(
            f"{api_url()}/admin/ingest", json=body,
            timeout=httpx.Timeout(600.0, connect=5.0, read=600.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Ingest thất bại: {exc}")
        return None


def run_health(topic: str | None = None) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/health-check",
            json={"topic": topic} if topic else {},
            timeout=httpx.Timeout(300.0, connect=5.0, read=300.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Health check thất bại: {exc}")
        return None


def get_stats() -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/stats")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được stats: {exc}")
        return None


def get_sessions() -> list[dict]:
    try:
        r = http().get(f"{api_url()}/sessions")
        r.raise_for_status()
        return r.json().get("sessions", [])
    except Exception:
        return []


def delete_session(sid: str) -> bool:
    try:
        return http().delete(f"{api_url()}/sessions/{sid}").status_code == 200
    except Exception:
        return False


def clear_cache() -> bool:
    try:
        return http().post(f"{api_url()}/admin/cache/clear").status_code == 200
    except Exception:
        return False


def rebuild_bm25() -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/bm25/rebuild",
            timeout=httpx.Timeout(120.0, connect=5.0, read=120.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Rebuild thất bại: {exc}")
        return None


def get_freshness(
    status: str | None = None,
    topic: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if topic:
            params["topic"] = topic
        r = http().get(f"{api_url()}/admin/freshness", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được freshness data: {exc}")
        return None


def batch_recrawl(urls: list[str]) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/freshness/recrawl",
            json={"urls": urls},
            timeout=httpx.Timeout(600.0, connect=5.0, read=600.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Batch recrawl thất bại: {exc}")
        return None


def get_scheduler_status() -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/scheduler/status")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được trạng thái scheduler: {exc}")
        return None


def update_scheduler_config(enabled: bool, interval_seconds: int) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/scheduler/config",
            json={"enabled": enabled, "interval_seconds": interval_seconds},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cập nhật scheduler thất bại: {exc}")
        return None


def run_scheduler_now() -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/scheduler/run-now",
            timeout=httpx.Timeout(300.0, connect=5.0, read=300.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Chạy scheduler thất bại: {exc}")
        return None


def get_feedback_list(
    feedback_type: str | None = None,
    reviewed: bool | None = None,
    review_status: str | None = None,
    root_cause: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if feedback_type:
            params["feedback_type"] = feedback_type
        if reviewed is not None:
            params["reviewed"] = str(reviewed).lower()
        if review_status:
            params["review_status"] = review_status
        if root_cause:
            params["root_cause"] = root_cause
        r = http().get(f"{api_url()}/admin/feedback", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được feedback: {exc}")
        st.session_state["feedback_fetch_failed"] = True
        return None


def review_feedback_item(
    feedback_id: int, review_note: str, review_status: str, root_cause: str | None = None,
) -> dict | None:
    try:
        body: dict = {"review_note": review_note, "review_status": review_status}
        if root_cause:
            body["root_cause"] = root_cause
        r = http().post(
            f"{api_url()}/admin/feedback/{feedback_id}/review",
            json=body,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Review thất bại: {exc}")
        return None


def create_feedback_action_item(feedback_id: int) -> dict | None:
    try:
        r = http().post(f"{api_url()}/admin/feedback/{feedback_id}/action-item")
        if r.status_code == 409:
            st.warning(r.json().get("detail", "Active action item already exists for this feedback."))
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Create action item failed: {exc}")
        return None


def get_feedback_actions(
    status: str | None = None,
    suggested_action: str | None = None,
    root_cause: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if suggested_action:
            params["suggested_action"] = suggested_action
        if root_cause:
            params["root_cause"] = root_cause
        r = http().get(f"{api_url()}/admin/feedback-actions", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Cannot fetch action items: {exc}")
        return None


def update_feedback_action_status(
    action_id: int, status: str, owner_note: str | None = None
) -> dict | None:
    try:
        body: dict = {"status": status}
        if owner_note:
            body["owner_note"] = owner_note
        r = http().post(
            f"{api_url()}/admin/feedback-actions/{action_id}/status",
            json=body,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Update status failed: {exc}")
        return None


def execute_feedback_action(action_id: int) -> dict | None:
    try:
        r = http().post(
            f"{api_url()}/admin/feedback-actions/{action_id}/execute",
            timeout=httpx.Timeout(120.0, connect=5.0, read=120.0),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Execute failed: {exc}")
        return None


def get_coverage_gaps(
    status: str | None = None,
    detected_topic: str | None = None,
    resolution: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if detected_topic:
            params["detected_topic"] = detected_topic
        if resolution:
            params["resolution"] = resolution
        r = http().get(f"{api_url()}/admin/coverage-gaps", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được coverage gaps: {exc}")
        return None


def review_coverage_gap(
    gap_id: int,
    status: str = "reviewed",
    resolution: str | None = None,
    review_note: str | None = None,
) -> dict | None:
    try:
        body: dict = {"status": status}
        if resolution is not None:
            body["resolution"] = resolution
        if review_note:
            body["review_note"] = review_note
        r = http().post(f"{api_url()}/admin/coverage-gaps/{gap_id}/review", json=body)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Review coverage gap thất bại: {exc}")
        return None


def action_coverage_gap(
    gap_id: int,
    resolution: str,
    action_payload: dict | None = None,
    review_note: str | None = None,
) -> dict | None:
    try:
        body: dict = {"resolution": resolution}
        if action_payload is not None:
            body["action_payload"] = action_payload
        if review_note:
            body["review_note"] = review_note
        r = http().post(f"{api_url()}/admin/coverage-gaps/{gap_id}/action", json=body)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Action coverage gap thất bại: {exc}")
        return None


def get_coverage_gaps_summary() -> dict | None:
    try:
        r = http().get(f"{api_url()}/admin/coverage-gaps/summary")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được summary: {exc}")
        return None


def get_coverage_gap_clusters(
    detected_topic: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict | None:
    try:
        params: dict = {"limit": limit, "offset": offset}
        if detected_topic:
            params["detected_topic"] = detected_topic
        if status:
            params["status"] = status
        r = http().get(f"{api_url()}/admin/coverage-gap-clusters", params=params)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được clusters: {exc}")
        return None


def get_coverage_gap_cluster_detail(cluster_key: str, limit: int = 50) -> dict | None:
    try:
        r = http().get(
            f"{api_url()}/admin/coverage-gap-clusters/{cluster_key}",
            params={"limit": limit},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Không lấy được cluster detail: {exc}")
        return None


def check_backend() -> bool:
    try:
        r = http().get(f"{api_url()}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False
