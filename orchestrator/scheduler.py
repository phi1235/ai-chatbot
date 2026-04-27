"""Background scheduler for periodic health-check runs.

Simple in-process scheduler: mỗi N giây, chạy một health-check đầy đủ toàn hệ thống
và lưu kết quả + trạng thái alert.

Chạy trong startup event của FastAPI để tận dụng async context hiện có.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from observability import get_logger

logger = get_logger(__name__)

_scheduler_task: asyncio.Task | None = None
_should_stop = False


def _detect_alerts(summary: dict) -> tuple[str, str]:
    """Detect alert conditions based on health-check summary."""
    dead = summary.get("dead", 0)
    error = summary.get("unknown", 0)
    stale = summary.get("stale", 0)
    total = summary.get("total", 0)

    if dead > 0 or error > 0:
        msg = []
        if dead > 0:
            msg.append(f"{dead} DEAD")
        if error > 0:
            msg.append(f"{error} ERROR")
        reason = f"CRITICAL: {', '.join(msg)}"
        return "CRITICAL", reason

    if stale > 0:
        reason = f"WARNING: {stale} STALE (out of {total})"
        return "WARNING", reason

    return "OK", "All checks passed"


def _summary_to_records(summary_obj: Any, checked_at: float) -> list[dict[str, Any]]:
    records = []
    for r in getattr(summary_obj, "results", []):
        mapped_status = "ERROR" if r.status == "UNKNOWN" else r.status
        error_message = r.detail if mapped_status == "ERROR" else ""
        records.append(
            {
                "url": r.location,
                "topic": r.topic,
                "status": mapped_status,
                "checked_at": checked_at,
                "http_status": r.http_status,
                "notes": r.detail,
                "error_message": error_message,
                "final_url": r.final_url,
            }
        )
    return records


async def run_health_check_internal() -> dict[str, Any]:
    """Run health check once and return both summary metrics and records."""
    try:
        project_root = Path(__file__).resolve().parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        import tools.check_sources as cs

        checked_at = time.time()
        summary_obj = cs.check_sources(topic=None)
        records = _summary_to_records(summary_obj, checked_at)

        result = {
            "total": summary_obj.total,
            "ok": summary_obj.ok,
            "stale": summary_obj.stale,
            "dead": summary_obj.dead,
            "redirect": summary_obj.redirect,
            "unknown": summary_obj.unknown,
            "checked_at": checked_at,
            "records": records,
        }
        logger.info(
            "Scheduler health-check completed",
            extra={
                "total": summary_obj.total,
                "ok": summary_obj.ok,
                "stale": summary_obj.stale,
                "dead": summary_obj.dead,
                "redirect": summary_obj.redirect,
                "unknown": summary_obj.unknown,
            },
        )
        return result
    except Exception as exc:
        logger.error(
            "Scheduler health-check failed",
            extra={"error": str(exc)},
            exc_info=True,
        )
        return {"error": str(exc), "checked_at": time.time(), "records": []}


def save_to_freshness_store(summary: dict) -> int:
    """Persist health-check results to freshness store without re-running checks."""
    from orchestrator import freshness_store

    if "error" in summary:
        return 0

    records = summary.get("records", [])
    return freshness_store.save_many(records)


async def run_scheduler_cycle() -> dict[str, Any]:
    """Run one scheduler cycle and persist summary state."""
    from orchestrator import scheduler_state

    summary = await run_health_check_internal()
    saved_count = save_to_freshness_store(summary)
    summary["snapshot_saved"] = saved_count

    alert_state, reason = _detect_alerts(summary)
    if alert_state != "OK":
        logger.warning("Scheduler alert detected", extra={"reason": reason})
    else:
        logger.info("Scheduler check result", extra={"reason": reason})

    scheduler_state.save_run_summary(summary, alert_state=alert_state)
    summary["alert_state"] = alert_state
    summary["alert_reason"] = reason
    return summary


async def scheduler_loop():
    """Main scheduler loop – runs health checks at regular intervals."""
    from orchestrator import scheduler_state

    logger.info("Scheduler loop started")
    global _should_stop

    while not _should_stop:
        try:
            state = scheduler_state.read_state()
            if not state.enabled:
                await asyncio.sleep(60)
                continue

            await run_scheduler_cycle()
            await asyncio.sleep(state.interval_seconds)
        except Exception as exc:
            logger.error(
                "Scheduler loop error",
                extra={"error": str(exc)},
                exc_info=True,
            )
            await asyncio.sleep(60)


async def start_scheduler_task():
    """Start scheduler background task in FastAPI startup."""
    global _scheduler_task, _should_stop
    if is_running():
        return
    _should_stop = False
    _scheduler_task = asyncio.create_task(scheduler_loop())
    logger.info("Scheduler task created")


async def stop_scheduler_task():
    """Stop scheduler background task in FastAPI shutdown."""
    global _scheduler_task, _should_stop
    _should_stop = True
    if _scheduler_task:
        try:
            await asyncio.wait_for(_scheduler_task, timeout=5.0)
        except TimeoutError:
            _scheduler_task.cancel()
        finally:
            _scheduler_task = None
        logger.info("Scheduler task stopped")


def is_running() -> bool:
    """Check if scheduler task is running."""
    return _scheduler_task is not None and not _scheduler_task.done()
