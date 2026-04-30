from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.admin_shared import SOURCES_DIR, logger

router = APIRouter()


class ActionItemStatusRequest(BaseModel):
    status: str
    owner_note: str | None = None


@router.post("/feedback/{feedback_id}/action-item")
async def create_feedback_action_item(feedback_id: int):
    from orchestrator import feedback_action_store, feedback_store

    feedback = feedback_store.get_feedback(feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback không tồn tại.")
    if not feedback.get("reviewed") or feedback.get("review_status") == "pending":
        raise HTTPException(
            status_code=400,
            detail="Feedback phải được review trước khi tạo action item.",
        )

    try:
        item = feedback_action_store.create_action_item(
            feedback_id=feedback_id,
            root_cause=feedback.get("root_cause"),
            detected_topic=feedback.get("detected_topic"),
            query_hint=feedback.get("rewritten_query"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return item


@router.get("/feedback-actions")
async def list_feedback_actions(
    status: str | None = None,
    suggested_action: str | None = None,
    root_cause: str | None = None,
    detected_topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    from orchestrator import feedback_action_store

    if status and status not in feedback_action_store.valid_statuses():
        raise HTTPException(
            status_code=400,
            detail=f"status phải là một trong: {', '.join(sorted(feedback_action_store.valid_statuses()))}",
        )
    if suggested_action and suggested_action not in feedback_action_store.valid_suggested_actions():
        raise HTTPException(
            status_code=400,
            detail=(
                f"suggested_action phải là một trong: "
                f"{', '.join(sorted(feedback_action_store.valid_suggested_actions()))}"
            ),
        )

    items = feedback_action_store.list_action_items(
        status=status,
        suggested_action=suggested_action,
        root_cause=root_cause,
        detected_topic=detected_topic,
        limit=limit,
        offset=offset,
    )
    summary = feedback_action_store.count_summary()
    return {
        "count": len(items),
        "summary": summary,
        "items": items,
    }


@router.post("/feedback-actions/{action_id}/status")
async def update_feedback_action_status(action_id: int, req: ActionItemStatusRequest):
    from orchestrator import feedback_action_store

    existing = feedback_action_store.get_action_item(action_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Action item không tồn tại.")

    try:
        updated = feedback_action_store.update_action_status(
            action_id,
            status=req.status,
            owner_note=req.owner_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return updated


@router.post("/feedback-actions/{action_id}/execute")
async def execute_feedback_action_item(action_id: int):
    from orchestrator import feedback_action_store
    from orchestrator.feedback_action_executor import execute_action_item

    existing = feedback_action_store.get_action_item(action_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Action item không tồn tại.")

    try:
        updated = execute_action_item(action_id, sources_dir=SOURCES_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Feedback action execution failed",
            extra={"action_id": action_id, "error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}") from exc

    logger.info(
        "Feedback action executed",
        extra={
            "action_id": action_id,
            "suggested_action": existing.get("suggested_action"),
            "execution_status": updated.get("execution_status"),
            "execution_type": updated.get("execution_type"),
        },
    )
    return updated


@router.get("/feedback-actions/summary")
async def feedback_actions_summary():
    from orchestrator import feedback_action_store
    return feedback_action_store.count_summary()
