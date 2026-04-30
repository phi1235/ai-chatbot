from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.admin.routes.sources import list_sources
from api.admin_shared import SOURCES_DIR, add_source_item, execute_recrawl, logger, resolve_recrawl_sources

router = APIRouter()


class CoverageGapReviewRequest(BaseModel):
    status: str = "reviewed"
    resolution: str | None = None
    review_note: str | None = None


class CoverageGapActionRequest(BaseModel):
    resolution: str
    review_note: str | None = None
    action_payload: dict | None = None


@router.get("/coverage-gaps")
async def list_coverage_gaps(
    status: str | None = None,
    detected_topic: str | None = None,
    resolution: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    from orchestrator import coverage_gap_store

    valid_statuses = {"new", "reviewed", "actioned", "ignored"}
    if status and status not in valid_statuses:
        raise HTTPException(status_code=400, detail="status không hợp lệ.")

    items = coverage_gap_store.list_gaps(
        status=status,
        detected_topic=detected_topic,
        resolution=resolution,
        limit=limit,
        offset=offset,
    )
    summary = coverage_gap_store.count_summary()
    return {
        "count": len(items),
        "summary": summary,
        "items": items,
    }


@router.post("/coverage-gaps/{gap_id}/review")
async def review_coverage_gap(gap_id: int, req: CoverageGapReviewRequest):
    from orchestrator import coverage_gap_store

    existing = coverage_gap_store.get_gap(gap_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Coverage gap không tồn tại.")

    try:
        updated = coverage_gap_store.review_gap(
            gap_id,
            status=req.status,
            resolution=req.resolution,
            review_note=req.review_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return updated


@router.post("/coverage-gaps/{gap_id}/action")
async def action_coverage_gap(gap_id: int, req: CoverageGapActionRequest):
    from orchestrator import coverage_gap_store

    existing = coverage_gap_store.get_gap(gap_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Coverage gap không tồn tại.")

    valid_actions = {"add_source", "recrawl"}
    if req.resolution not in valid_actions:
        raise HTTPException(
            status_code=400,
            detail=f"resolution phải là một trong: {', '.join(sorted(valid_actions))}",
        )

    payload = req.action_payload or {}

    if req.resolution == "add_source":
        action_result = add_source_item(
            topic=(payload.get("topic") or ""),
            location=(payload.get("url") or ""),
            title=(payload.get("title") or ""),
        )
    elif req.resolution == "recrawl":
        sources = await resolve_recrawl_sources(
            topic=payload.get("topic"),
            urls=payload.get("urls") or [],
            list_sources_fn=list_sources,
        )
        action_result = execute_recrawl(sources)
    else:
        raise HTTPException(status_code=400, detail="Action không được hỗ trợ.")

    try:
        updated = coverage_gap_store.action_gap(
            gap_id,
            resolution=req.resolution,
            action_payload={**payload, "result": action_result},
            review_note=req.review_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Coverage gap action executed",
        extra={
            "gap_id": gap_id,
            "resolution": req.resolution,
            "action_result": action_result,
        },
    )

    return {
        "gap": updated,
        "action_result": action_result,
    }


@router.get("/coverage-gaps/summary")
async def coverage_gaps_summary():
    from orchestrator import coverage_gap_store
    return coverage_gap_store.count_summary()


@router.get("/coverage-gap-clusters")
async def list_coverage_gap_clusters(
    detected_topic: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    from orchestrator import coverage_gap_store
    from orchestrator.coverage_gap_recommendation import (
        get_topic_source_context,
        recommend_for_cluster,
    )

    valid_statuses = {"new", "reviewed", "actioned", "ignored"}
    if status and status not in valid_statuses:
        raise HTTPException(status_code=400, detail="status không hợp lệ.")

    clusters = coverage_gap_store.list_clusters(
        detected_topic=detected_topic,
        status=status,
        limit=limit,
        offset=offset,
    )

    topic_sources = get_topic_source_context(SOURCES_DIR)
    for cl in clusters:
        cl["recommendation"] = recommend_for_cluster(cl, topic_sources)

    return {
        "count": len(clusters),
        "clusters": clusters,
    }


@router.get("/coverage-gap-clusters/{cluster_key:path}")
async def get_coverage_gap_cluster_detail(
    cluster_key: str,
    limit: int = 50,
    offset: int = 0,
):
    from orchestrator import coverage_gap_store
    from orchestrator.coverage_gap_recommendation import (
        get_topic_source_context,
        recommend_for_cluster,
    )

    gaps = coverage_gap_store.list_gaps_by_cluster(
        cluster_key,
        limit=limit,
        offset=offset,
    )

    recommendation = None
    if gaps:
        detected_topic = gaps[0].get("detected_topic") or ""
        statuses: dict[str, int] = {}
        for g in gaps:
            s = g.get("status", "new")
            statuses[s] = statuses.get(s, 0) + 1
        resolutions: dict[str, int] = {}
        for g in gaps:
            res = g.get("resolution")
            if res:
                resolutions[res] = resolutions.get(res, 0) + 1

        cluster_summary = {
            "cluster_key": cluster_key,
            "representative_question": gaps[0].get("question", ""),
            "detected_topic": detected_topic,
            "count": len(gaps),
            "statuses": statuses,
            "resolutions": resolutions,
        }
        topic_sources = get_topic_source_context(SOURCES_DIR)
        recommendation = recommend_for_cluster(cluster_summary, topic_sources)

    return {
        "cluster_key": cluster_key,
        "count": len(gaps),
        "gaps": gaps,
        "recommendation": recommendation,
    }
