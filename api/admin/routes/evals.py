from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from api.admin_shared import logger

router = APIRouter()


class RunBatchRequest(BaseModel):
    status: str = "active"
    root_cause: str | None = None
    expected_topic: str | None = None
    limit: int | None = None
    label: str | None = None


@router.post("/feedback/{feedback_id}/eval-case")
async def create_eval_case_from_feedback(feedback_id: int):
    from orchestrator import eval_case_store, feedback_store

    feedback = feedback_store.get_feedback(feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback không tồn tại.")
    if not feedback.get("reviewed") or feedback.get("review_status") == "pending":
        raise HTTPException(
            status_code=400,
            detail="Feedback phải được review trước khi tạo eval case.",
        )

    try:
        case = eval_case_store.create_eval_case(
            feedback_id=feedback_id,
            question=feedback["question"],
            root_cause=feedback.get("root_cause"),
            expected_topic=feedback.get("detected_topic"),
            rewritten_query=feedback.get("rewritten_query"),
            citations_snapshot=feedback.get("citations_snapshot") or None,
            trace_snapshot=feedback.get("trace_snapshot") or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return case


@router.get("/eval-cases")
async def list_eval_cases(
    status: str | None = None,
    root_cause: str | None = None,
    expected_topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    from orchestrator import eval_case_store

    if status and status not in ("active", "archived"):
        raise HTTPException(status_code=400, detail="status phải là 'active' hoặc 'archived'.")

    items = eval_case_store.list_eval_cases(
        status=status,
        root_cause=root_cause,
        expected_topic=expected_topic,
        limit=limit,
        offset=offset,
    )
    summary = eval_case_store.count_summary()
    return {
        "count": len(items),
        "summary": summary,
        "items": items,
    }


@router.get("/eval-cases/summary")
async def eval_cases_summary():
    from orchestrator import eval_case_store
    return eval_case_store.count_summary()


@router.post("/eval-cases/run-batch")
async def run_eval_batch(req: RunBatchRequest):
    from orchestrator import eval_case_store
    from orchestrator.eval_runner import run_eval_case as _run

    if req.status not in ("active", "archived"):
        raise HTTPException(status_code=400, detail="status phải là 'active' hoặc 'archived'.")

    case_limit = min(req.limit or 200, 200)
    cases = eval_case_store.list_eval_cases(
        status=req.status,
        root_cause=req.root_cause,
        expected_topic=req.expected_topic,
        limit=case_limit,
    )

    if not cases:
        raise HTTPException(
            status_code=400,
            detail="No matching eval cases found. Adjust filters or add eval cases first.",
        )

    filters: dict[str, Any] = {
        "status": req.status,
        "root_cause": req.root_cause,
        "expected_topic": req.expected_topic,
        "limit": req.limit,
    }

    item_results = []
    for case in cases:
        case_id = case["id"]
        try:
            run = _run(case)
            item_results.append({
                "eval_case_id": case_id,
                "eval_run_id": run["id"],
                "passed": run["pass"],
                "root_cause": case.get("root_cause"),
                "expected_topic": case.get("expected_topic"),
                "error": None,
            })
        except Exception as exc:
            logger.warning(
                "Eval batch: case run failed",
                extra={"case_id": case_id, "error": str(exc)},
            )
            item_results.append({
                "eval_case_id": case_id,
                "eval_run_id": None,
                "passed": None,
                "root_cause": case.get("root_cause"),
                "expected_topic": case.get("expected_topic"),
                "error": str(exc)[:500],
            })

    pass_count = sum(1 for it in item_results if it["passed"] is True)
    fail_count = sum(1 for it in item_results if it["passed"] is False)

    batch = eval_case_store.create_eval_batch(
        label=(req.label or "").strip() or None,
        filters=filters,
        total_cases=len(item_results),
        pass_count=pass_count,
        fail_count=fail_count,
    )
    batch_id = batch["id"]

    for it in item_results:
        eval_case_store.create_eval_batch_item(
            batch_id=batch_id,
            eval_case_id=it["eval_case_id"],
            eval_run_id=it["eval_run_id"],
            passed=it["passed"],
            root_cause=it["root_cause"],
            expected_topic=it["expected_topic"],
            error=it["error"],
        )

    logger.info(
        "Eval batch run completed",
        extra={
            "batch_id": batch_id,
            "total": len(item_results),
            "pass": pass_count,
            "fail": fail_count,
        },
    )

    return eval_case_store.get_eval_batch(batch_id)


@router.get("/eval-batches")
async def list_eval_batches(limit: int = 20, offset: int = 0):
    from orchestrator import eval_case_store

    batches = eval_case_store.list_eval_batches(limit=limit, offset=offset)
    return {
        "count": len(batches),
        "batches": batches,
    }


@router.get("/eval-batches/{batch_id}/items")
async def list_eval_batch_items(batch_id: int, limit: int = 200, offset: int = 0):
    from orchestrator import eval_case_store

    batch = eval_case_store.get_eval_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Eval batch không tồn tại.")

    items = eval_case_store.list_eval_batch_items(batch_id, limit=limit, offset=offset)
    return {
        "batch_id": batch_id,
        "count": len(items),
        "items": items,
    }


@router.get("/eval-batches/compare")
async def compare_eval_batches(
    candidate_batch_id: int,
    baseline_batch_id: int | None = None,
):
    from orchestrator import eval_case_store

    if baseline_batch_id is None:
        batches = eval_case_store.list_eval_batches(limit=50)
        resolved_baseline: int | None = None
        for i, b in enumerate(batches):
            if b["id"] == candidate_batch_id and i + 1 < len(batches):
                resolved_baseline = batches[i + 1]["id"]
                break
        if resolved_baseline is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No previous batch found for batch {candidate_batch_id}. "
                    "Provide baseline_batch_id explicitly."
                ),
            )
        baseline_id = resolved_baseline
    else:
        baseline_id = baseline_batch_id

    try:
        result = eval_case_store.compare_eval_batches(baseline_id, candidate_batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return result


@router.get("/eval-batches/trend")
async def eval_batches_trend(limit: int = 10):
    from orchestrator import eval_case_store

    items = eval_case_store.get_eval_batches_trend(limit=limit)
    return {
        "count": len(items),
        "batches": items,
    }


@router.get("/eval-batches/{batch_id}")
async def get_eval_batch(batch_id: int):
    from orchestrator import eval_case_store

    batch = eval_case_store.get_eval_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Eval batch không tồn tại.")
    return batch


@router.post("/eval-cases/{case_id}/run")
async def run_eval_case(case_id: int):
    from orchestrator import eval_case_store
    from orchestrator.eval_runner import run_eval_case as _run

    case = eval_case_store.get_eval_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Eval case không tồn tại.")
    if case.get("status") == "archived":
        raise HTTPException(status_code=400, detail="Cannot run an archived eval case.")

    try:
        run = _run(case)
    except Exception as exc:
        logger.error(
            "Eval case run failed",
            extra={"case_id": case_id, "error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Eval run failed: {exc}") from exc

    logger.info(
        "Eval case run completed",
        extra={
            "case_id": case_id,
            "pass": run.get("pass"),
        },
    )
    return run


@router.get("/eval-cases/{case_id}/runs")
async def list_eval_case_runs(
    case_id: int,
    limit: int = 20,
    offset: int = 0,
):
    from orchestrator import eval_case_store

    case = eval_case_store.get_eval_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Eval case không tồn tại.")

    runs = eval_case_store.list_eval_runs(case_id, limit=limit, offset=offset)
    return {
        "eval_case_id": case_id,
        "count": len(runs),
        "runs": runs,
    }


@router.patch("/eval-cases/{case_id}/status")
async def update_eval_case_status(case_id: int, body: dict = Body(...)):
    from orchestrator import eval_case_store

    status = (body.get("status") or "").strip()
    if status not in ("active", "archived"):
        raise HTTPException(status_code=400, detail="status phải là 'active' hoặc 'archived'.")

    case = eval_case_store.get_eval_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Eval case không tồn tại.")

    try:
        updated = eval_case_store.update_eval_case_status(case_id, status=status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return updated
