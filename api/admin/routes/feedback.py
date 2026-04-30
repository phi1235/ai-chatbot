from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class FeedbackRequest(BaseModel):
    session_id: str | None = None
    message_id: str | None = None
    question: str
    answer: str
    feedback_type: str
    note: str | None = None
    rewritten_query: str | None = None
    detected_topic: str | None = None
    retrieval_count: int | None = None
    citations_snapshot: list[dict] | None = None
    trace_snapshot: dict | None = None


class ReviewRequest(BaseModel):
    review_note: str | None = None
    review_status: str = "reviewed"
    root_cause: str | None = None


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    from orchestrator import feedback_store

    if req.feedback_type not in ("up", "down"):
        raise HTTPException(status_code=400, detail="feedback_type phải là 'up' hoặc 'down'.")
    if not (req.question or "").strip() or not (req.answer or "").strip():
        raise HTTPException(status_code=400, detail="question và answer không được trống.")

    try:
        feedback_id = feedback_store.add_feedback(
            question=req.question,
            answer=req.answer,
            feedback_type=req.feedback_type,
            session_id=req.session_id,
            message_id=req.message_id,
            note=req.note,
            rewritten_query=req.rewritten_query,
            detected_topic=req.detected_topic,
            retrieval_count=req.retrieval_count,
            citations_snapshot=req.citations_snapshot,
            trace_snapshot=req.trace_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"id": feedback_id, "feedback_type": req.feedback_type}


@router.get("/feedback")
async def list_feedback(
    feedback_type: str | None = None,
    reviewed: bool | None = None,
    session_id: str | None = None,
    review_status: str | None = None,
    root_cause: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    from orchestrator import feedback_store

    if feedback_type and feedback_type not in ("up", "down"):
        raise HTTPException(status_code=400, detail="feedback_type phải là 'up' hoặc 'down'.")
    if review_status and review_status not in ("pending", "reviewed", "actioned"):
        raise HTTPException(status_code=400, detail="review_status không hợp lệ.")
    if root_cause and root_cause not in feedback_store.valid_root_causes():
        raise HTTPException(status_code=400, detail="root_cause không hợp lệ.")

    items = feedback_store.list_feedbacks(
        feedback_type=feedback_type,
        reviewed=reviewed,
        session_id=session_id,
        review_status=review_status,
        root_cause=root_cause,
        limit=limit,
        offset=offset,
    )
    summary = feedback_store.count_summary()
    return {
        "count": len(items),
        "summary": summary,
        "items": items,
    }


@router.post("/feedback/{feedback_id}/review")
async def review_feedback(feedback_id: int, req: ReviewRequest):
    from orchestrator import feedback_store

    existing = feedback_store.get_feedback(feedback_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Feedback không tồn tại.")

    if req.review_status not in ("pending", "reviewed", "actioned"):
        raise HTTPException(status_code=400, detail="review_status không hợp lệ.")
    if req.root_cause and req.root_cause not in feedback_store.valid_root_causes():
        raise HTTPException(status_code=400, detail="root_cause không hợp lệ.")

    try:
        updated = feedback_store.mark_reviewed(
            feedback_id,
            review_note=req.review_note,
            review_status=req.review_status,
            root_cause=req.root_cause,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return updated


@router.get("/feedback/summary")
async def feedback_summary():
    from orchestrator import feedback_store
    return feedback_store.count_summary()
