"""Eval Gate Runner – gate execution logic and CLI entry point.

Core flow for running an eval gate:
  1. Load gate config
  2. Build a batch label (from template or default)
  3. Run a batch using the existing eval_case_store + eval_runner infrastructure
  4. Resolve a baseline batch using the configured baseline_mode
  5. Compare candidate vs baseline using compare_eval_batches
  6. Apply threshold rules to decide pass/fail/no_baseline/error
  7. Persist a compact gate run record
  8. Return the gate run dict

Decisions:
  - pass        – candidate met or exceeded baseline within thresholds
  - fail        – at least one threshold rule was violated
  - no_baseline – no prior baseline could be resolved (first run or no prior batches)
  - error       – the batch run or comparison itself raised an exception

CLI usage (shell-friendly, non-zero exit on failure):
  python -m orchestrator.eval_gate_runner --config <name> [--trigger ci]

Exit codes:
  0 – gate decision: pass
  1 – gate decision: fail, no_baseline, or error
"""
from __future__ import annotations

import sys
from typing import Any

from observability import get_logger

logger = get_logger(__name__)


# ─── Batch execution (mirrors api/admin.py run_eval_batch logic) ──────────────

def _run_batch_for_gate(
    *,
    status_filter: str,
    root_cause: str | None,
    expected_topic: str | None,
    limit_cases: int | None,
    label: str | None,
) -> dict:
    """Run eval cases matching config filters; persist and return the batch record.

    Mirrors admin.py run_eval_batch without going through HTTP.
    Raises RuntimeError if no cases match or if the batch could not be created.
    """
    from orchestrator import eval_case_store
    from orchestrator.eval_runner import run_eval_case as _run

    case_limit = min(limit_cases or 200, 200)
    cases = eval_case_store.list_eval_cases(
        status=status_filter,
        root_cause=root_cause,
        expected_topic=expected_topic,
        limit=case_limit,
    )
    if not cases:
        raise RuntimeError(
            "No matching eval cases found for gate config filters. "
            f"(status={status_filter!r}, root_cause={root_cause!r}, "
            f"expected_topic={expected_topic!r})"
        )

    filters: dict[str, Any] = {
        "status": status_filter,
        "root_cause": root_cause,
        "expected_topic": expected_topic,
        "limit": limit_cases,
        "gate_label": label,
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
                "Gate batch: case run failed",
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
        label=(label or "").strip() or None,
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

    return eval_case_store.get_eval_batch(batch_id)  # type: ignore[return-value]


# ─── Baseline resolution ──────────────────────────────────────────────────────

def _resolve_baseline(
    *,
    config_id: int,
    candidate_batch_id: int,
    baseline_mode: str,
) -> int | None:
    """Return the baseline batch_id to compare against, or None if unavailable.

    previous_gate_run mode:
        Use the candidate_batch_id from the most recent prior gate run for this
        config. If no prior gate run exists, return None (first run → no_baseline).

    previous_batch mode:
        Use the batch created immediately before the candidate batch (by id order).
        If no older batch exists, return None.
    """
    from orchestrator import eval_case_store, eval_gate_store

    if baseline_mode == "previous_gate_run":
        last_run = eval_gate_store.get_most_recent_gate_run_for_config(config_id)
        if last_run is None or last_run.get("candidate_batch_id") is None:
            return None
        return last_run["candidate_batch_id"]

    # previous_batch mode: find the batch immediately before candidate
    batches = eval_case_store.list_eval_batches(limit=200)  # newest first
    for i, b in enumerate(batches):
        if b["id"] == candidate_batch_id and i + 1 < len(batches):
            return batches[i + 1]["id"]
    return None


# ─── Threshold rules ──────────────────────────────────────────────────────────

def _apply_thresholds(
    comparison: dict,
    *,
    max_pass_rate_drop: float | None,
    max_fail_count_increase: int | None,
    block_on_error_increase: bool,
) -> tuple[str, str]:
    """Apply threshold rules to a comparison result.

    Returns (decision, reason): decision is 'pass' or 'fail'.
    """
    reasons: list[str] = []

    delta_pass_rate = comparison.get("delta_pass_rate", 0.0) or 0.0
    delta_fail_count = comparison.get("delta_fail_count", 0) or 0
    delta_error_count = comparison.get("delta_error_count", 0) or 0
    baseline_rate = comparison.get("baseline_pass_rate", 0.0) or 0.0
    candidate_rate = comparison.get("candidate_pass_rate", 0.0) or 0.0

    if max_pass_rate_drop is not None and delta_pass_rate < -max_pass_rate_drop:
        pct_drop = abs(delta_pass_rate) * 100
        reasons.append(
            f"pass rate dropped {pct_drop:.1f}% "
            f"({baseline_rate:.2%} → {candidate_rate:.2%}); "
            f"threshold={max_pass_rate_drop:.2%}"
        )

    if max_fail_count_increase is not None and delta_fail_count > max_fail_count_increase:
        reasons.append(
            f"fail count increased by {delta_fail_count} "
            f"(threshold={max_fail_count_increase})"
        )

    if block_on_error_increase and delta_error_count > 0:
        reasons.append(f"error count increased by {delta_error_count}")

    if reasons:
        return "fail", "; ".join(reasons)
    return "pass", "candidate meets all thresholds vs baseline"


# ─── Main gate execution ──────────────────────────────────────────────────────

def run_gate(
    config_id_or_name: int | str,
    *,
    trigger_source: str = "manual",
) -> dict:
    """Execute a full gate run for the named/id config.

    Returns the gate run record dict (with decision field).
    Never raises — errors are captured as decision='error'.
    """
    from orchestrator import eval_gate_store

    # Load config
    if isinstance(config_id_or_name, int):
        config = eval_gate_store.get_gate_config(config_id_or_name)
    else:
        config = eval_gate_store.get_gate_config_by_name(config_id_or_name)

    if config is None:
        raise ValueError(f"Gate config not found: {config_id_or_name!r}")

    config_id = config["id"]
    kind = config["kind"]

    # Build run label
    label_template = config.get("run_label_template") or ""
    if label_template:
        from datetime import UTC, datetime
        now_str = datetime.now(UTC).strftime("%Y-%m-%d")
        label = label_template.replace("{date}", now_str).replace("{kind}", kind)
    else:
        from datetime import UTC, datetime
        label = f"{kind}-gate-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

    candidate_batch_id: int | None = None
    baseline_batch_id: int | None = None
    decision: str = "error"
    decision_reason: str = ""
    pass_rate_drop: float | None = None
    fail_count_delta: int | None = None
    error_count_delta: int | None = None

    try:
        # Step 1: run the batch
        batch = _run_batch_for_gate(
            status_filter=config.get("status_filter") or "active",
            root_cause=config.get("root_cause"),
            expected_topic=config.get("expected_topic"),
            limit_cases=config.get("limit_cases"),
            label=label,
        )
        candidate_batch_id = batch["id"]
        logger.info(
            "Gate batch run completed",
            extra={
                "config_id": config_id,
                "candidate_batch_id": candidate_batch_id,
                "label": label,
            },
        )

        # Step 2: resolve baseline
        baseline_batch_id = _resolve_baseline(
            config_id=config_id,
            candidate_batch_id=candidate_batch_id,
            baseline_mode=config.get("baseline_mode") or "previous_gate_run",
        )

        if baseline_batch_id is None:
            decision = "no_baseline"
            decision_reason = (
                "No baseline batch available for comparison. "
                "This is the first gate run for this config, or no prior batches exist."
            )
        else:
            # Step 3: compare
            from orchestrator.eval_case_store import compare_eval_batches
            comparison_exc: str | None = None
            comparison: dict = {}
            try:
                comparison = compare_eval_batches(baseline_batch_id, candidate_batch_id)
            except ValueError as exc:
                comparison_exc = str(exc)

            if comparison_exc:
                decision = "error"
                decision_reason = f"Comparison failed: {comparison_exc}"
            else:
                pass_rate_drop = comparison.get("delta_pass_rate")
                fail_count_delta = comparison.get("delta_fail_count")
                error_count_delta = comparison.get("delta_error_count")

                # Step 4: apply thresholds
                decision, decision_reason = _apply_thresholds(
                    comparison,
                    max_pass_rate_drop=config.get("max_pass_rate_drop"),
                    max_fail_count_increase=config.get("max_fail_count_increase"),
                    block_on_error_increase=bool(config.get("block_on_error_increase")),
                )

    except Exception as exc:
        decision = "error"
        decision_reason = f"Gate execution error: {str(exc)[:400]}"
        logger.error(
            "Gate run failed",
            extra={"config_id": config_id, "error": str(exc)},
            exc_info=True,
        )

    # Step 5: persist gate run
    gate_run = eval_gate_store.create_gate_run(
        config_id=config_id,
        kind=kind,
        trigger_source=trigger_source,
        baseline_batch_id=baseline_batch_id,
        candidate_batch_id=candidate_batch_id,
        decision=decision,
        decision_reason=decision_reason,
        pass_rate_drop=pass_rate_drop,
        fail_count_delta=fail_count_delta,
        error_count_delta=error_count_delta,
    )

    logger.info(
        "Gate run persisted",
        extra={
            "gate_run_id": gate_run["id"],
            "config_id": config_id,
            "decision": decision,
            "trigger_source": trigger_source,
        },
    )
    return gate_run


def run_nightly_gates() -> list[dict]:
    """Run all enabled nightly gate configs. Returns list of gate run records."""
    from orchestrator import eval_gate_store

    configs = eval_gate_store.list_gate_configs(kind="nightly", enabled=True)
    if not configs:
        logger.info("No enabled nightly gate configs found")
        return []

    results = []
    for config in configs:
        try:
            gate_run = run_gate(config["id"], trigger_source="nightly")
            results.append(gate_run)
        except Exception as exc:
            logger.error(
                "Nightly gate failed for config",
                extra={"config_id": config["id"], "error": str(exc)},
                exc_info=True,
            )
            # Persist error run if possible
            try:
                from orchestrator import eval_gate_store as gs
                gate_run = gs.create_gate_run(
                    config_id=config["id"],
                    kind=config["kind"],
                    trigger_source="nightly",
                    baseline_batch_id=None,
                    candidate_batch_id=None,
                    decision="error",
                    decision_reason=f"Nightly run error: {str(exc)[:400]}",
                )
                results.append(gate_run)
            except Exception:
                pass
    return results


# ─── CLI entry point ──────────────────────────────────────────────────────────

def _cli_main(argv: list[str] | None = None) -> int:
    """Shell-friendly CLI: run a named gate config and exit with 0 (pass) or 1 (fail/error).

    Usage:
        python -m orchestrator.eval_gate_runner --config <name> [--trigger ci]
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description="Run a named eval gate config and exit 0 on pass, 1 on failure.",
    )
    parser.add_argument("--config", required=True, help="Gate config name")
    parser.add_argument(
        "--trigger",
        default="ci",
        choices=["ci", "nightly", "manual"],
        help="Trigger source label (default: ci)",
    )
    parser.add_argument("--json", action="store_true", help="Print gate run as JSON")
    args = parser.parse_args(argv)

    try:
        gate_run = run_gate(args.config, trigger_source=args.trigger)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(_json.dumps(gate_run, indent=2))
    else:
        decision = gate_run.get("decision", "error")
        reason = gate_run.get("decision_reason", "")
        run_id = gate_run.get("id", "?")
        print(f"Gate run #{run_id}  decision={decision.upper()}  {reason}")

    decision = gate_run.get("decision", "error")
    return 0 if decision == "pass" else 1


if __name__ == "__main__":
    sys.exit(_cli_main())
