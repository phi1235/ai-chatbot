from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.admin_shared import logger

router = APIRouter()


class GateConfigCreateRequest(BaseModel):
    name: str
    kind: str = "nightly"
    enabled: bool = True
    status_filter: str = "active"
    root_cause: str | None = None
    expected_topic: str | None = None
    limit_cases: int | None = None
    run_label_template: str | None = None
    baseline_mode: str = "previous_gate_run"
    max_pass_rate_drop: float | None = None
    max_fail_count_increase: int | None = None
    block_on_error_increase: bool = False


class GateConfigPatchRequest(BaseModel):
    name: str | None = None
    kind: str | None = None
    enabled: bool | None = None
    status_filter: str | None = None
    root_cause: str | None = None
    expected_topic: str | None = None
    limit_cases: int | None = None
    run_label_template: str | None = None
    baseline_mode: str | None = None
    max_pass_rate_drop: float | None = None
    max_fail_count_increase: int | None = None
    block_on_error_increase: bool | None = None


class GateRunRequest(BaseModel):
    trigger_source: str = "manual"


class RunCIRequest(BaseModel):
    config_name: str
    trigger_source: str = "ci"


_VALID_REGRESSION_CLASSES = frozenset({
    "new_fail", "still_fail", "improved", "new_error", "still_error", "still_pass",
})


@router.get("/eval-gates/configs")
async def list_gate_configs(
    kind: str | None = None,
    enabled: bool | None = None,
):
    from orchestrator import eval_gate_store

    configs = eval_gate_store.list_gate_configs(kind=kind, enabled=enabled)
    return {"count": len(configs), "configs": configs}


@router.post("/eval-gates/configs")
async def create_gate_config(req: GateConfigCreateRequest):
    from orchestrator import eval_gate_store

    try:
        config = eval_gate_store.create_gate_config(
            name=req.name,
            kind=req.kind,
            enabled=req.enabled,
            status_filter=req.status_filter,
            root_cause=req.root_cause,
            expected_topic=req.expected_topic,
            limit_cases=req.limit_cases,
            run_label_template=req.run_label_template,
            baseline_mode=req.baseline_mode,
            max_pass_rate_drop=req.max_pass_rate_drop,
            max_fail_count_increase=req.max_fail_count_increase,
            block_on_error_increase=req.block_on_error_increase,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return config


@router.patch("/eval-gates/configs/{config_id}")
async def patch_gate_config(config_id: int, req: GateConfigPatchRequest):
    from orchestrator import eval_gate_store

    existing = eval_gate_store.get_gate_config(config_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Gate config not found.")

    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        return existing

    try:
        updated = eval_gate_store.update_gate_config(config_id, updates=updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return updated


@router.post("/eval-gates/configs/{config_id}/run")
async def run_gate_config(config_id: int, req: GateRunRequest):
    from orchestrator import eval_gate_store
    from orchestrator.eval_gate_runner import run_gate

    config = eval_gate_store.get_gate_config(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Gate config not found.")

    trigger = (req.trigger_source or "manual").strip()
    if trigger not in ("manual", "nightly", "ci"):
        raise HTTPException(
            status_code=400,
            detail="trigger_source must be one of: manual, nightly, ci",
        )

    try:
        gate_run = run_gate(config_id, trigger_source=trigger)
    except Exception as exc:
        logger.error(
            "Gate run endpoint failed",
            extra={"config_id": config_id, "error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Gate run failed: {exc}") from exc

    logger.info(
        "Gate run completed via API",
        extra={
            "config_id": config_id,
            "gate_run_id": gate_run.get("id"),
            "decision": gate_run.get("decision"),
            "trigger": trigger,
        },
    )
    return gate_run


@router.get("/eval-gates/runs")
async def list_gate_runs(
    config_id: int | None = None,
    kind: str | None = None,
    decision: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    from orchestrator import eval_gate_store

    if decision and decision not in ("pass", "fail", "no_baseline", "error"):
        raise HTTPException(
            status_code=400,
            detail="decision must be one of: pass, fail, no_baseline, error",
        )

    runs = eval_gate_store.list_gate_runs(
        config_id=config_id,
        kind=kind,
        decision=decision,
        limit=limit,
        offset=offset,
    )
    return {"count": len(runs), "runs": runs}


@router.get("/eval-gates/runs/{run_id}")
async def get_gate_run(run_id: int):
    from orchestrator import eval_gate_store

    run = eval_gate_store.get_gate_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Gate run not found.")
    return run


@router.get("/eval-gates/runs/{run_id}/triage")
async def get_gate_run_triage(run_id: int):
    from orchestrator.eval_gate_triage import get_gate_run_triage as _triage

    result = _triage(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Gate run not found.")
    return result


@router.get("/eval-gates/runs/{run_id}/items")
async def get_gate_run_triage_items(
    run_id: int,
    regression_class: str | None = None,
    root_cause: str | None = None,
    expected_topic: str | None = None,
    outcome: str | None = None,
):
    from orchestrator import eval_gate_store
    from orchestrator.eval_gate_triage import filter_triage_items
    from orchestrator.eval_gate_triage import get_gate_run_triage as _triage

    gate_run = eval_gate_store.get_gate_run(run_id)
    if gate_run is None:
        raise HTTPException(status_code=404, detail="Gate run not found.")

    if regression_class and regression_class not in _VALID_REGRESSION_CLASSES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"regression_class must be one of: "
                f"{', '.join(sorted(_VALID_REGRESSION_CLASSES))}"
            ),
        )
    if outcome and outcome not in ("pass", "fail", "error"):
        raise HTTPException(
            status_code=400,
            detail="outcome must be one of: pass, fail, error",
        )

    triage = _triage(run_id)
    if triage is None:
        raise HTTPException(status_code=404, detail="Gate run not found.")

    items = filter_triage_items(
        triage["items"],
        regression_class=regression_class,
        root_cause=root_cause,
        expected_topic=expected_topic,
        outcome=outcome,
    )

    return {
        "run_id": run_id,
        "decision": gate_run.get("decision"),
        "total_items": len(triage["items"]),
        "filtered_count": len(items),
        "filters": {
            "regression_class": regression_class,
            "root_cause": root_cause,
            "expected_topic": expected_topic,
            "outcome": outcome,
        },
        "triage_meta": triage.get("triage_meta") or {},
        "items": items,
    }


@router.post("/eval-gates/run-nightly")
async def run_nightly_gates():
    from orchestrator.eval_gate_runner import run_nightly_gates as _run_nightly

    gate_runs = _run_nightly()
    summary = [
        {
            "gate_run_id": gr.get("id"),
            "config_id": gr.get("config_id"),
            "decision": gr.get("decision"),
            "decision_reason": gr.get("decision_reason"),
        }
        for gr in gate_runs
    ]
    any_fail = any(gr.get("decision") in ("fail", "error") for gr in gate_runs)
    logger.info(
        "Nightly gate run completed",
        extra={"ran": len(gate_runs), "any_fail": any_fail},
    )
    return {
        "ran": len(gate_runs),
        "any_fail": any_fail,
        "summary": summary,
    }


@router.post("/eval-gates/run-ci")
async def run_ci_gate(req: RunCIRequest):
    from orchestrator import eval_gate_store
    from orchestrator.eval_gate_runner import run_gate

    config = eval_gate_store.get_gate_config_by_name(req.config_name)
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"Gate config '{req.config_name}' not found.",
        )

    try:
        gate_run = run_gate(config["id"], trigger_source="ci")
    except Exception as exc:
        logger.error(
            "CI gate run endpoint failed",
            extra={"config_name": req.config_name, "error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"CI gate run failed: {exc}") from exc

    logger.info(
        "CI gate run completed",
        extra={
            "config_name": req.config_name,
            "gate_run_id": gate_run.get("id"),
            "decision": gate_run.get("decision"),
        },
    )
    return gate_run
