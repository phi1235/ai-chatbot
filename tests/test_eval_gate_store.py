"""Unit tests for orchestrator.eval_gate_store and eval_gate_runner thresholds."""
from __future__ import annotations

import importlib
import time

import pytest


@pytest.fixture(autouse=True)
def _fresh_store(tmp_path, monkeypatch):
    """Each test uses an isolated DB in tmp_path."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))

    import config.settings as settings_mod
    importlib.reload(settings_mod)

    import orchestrator.eval_gate_store as gs
    gs._initialised_paths.clear()
    importlib.reload(gs)


def _store():
    import orchestrator.eval_gate_store as gs
    return gs


# ─── Gate Config CRUD ─────────────────────────────────────────────────────────

def test_create_gate_config_defaults():
    gs = _store()
    cfg = gs.create_gate_config(name="default-nightly")
    assert cfg["id"] > 0
    assert cfg["name"] == "default-nightly"
    assert cfg["kind"] == "nightly"
    assert cfg["enabled"] is True
    assert cfg["status_filter"] == "active"
    assert cfg["baseline_mode"] == "previous_gate_run"
    assert cfg["block_on_error_increase"] is False
    assert cfg["max_pass_rate_drop"] is None
    assert cfg["max_fail_count_increase"] is None


def test_create_gate_config_ci_kind():
    gs = _store()
    cfg = gs.create_gate_config(
        name="ci-smoke",
        kind="ci",
        max_pass_rate_drop=0.05,
        max_fail_count_increase=2,
        block_on_error_increase=True,
    )
    assert cfg["kind"] == "ci"
    assert cfg["max_pass_rate_drop"] == pytest.approx(0.05)
    assert cfg["max_fail_count_increase"] == 2
    assert cfg["block_on_error_increase"] is True


def test_create_gate_config_invalid_kind():
    gs = _store()
    with pytest.raises(ValueError, match="kind"):
        gs.create_gate_config(name="bad", kind="weekly")


def test_create_gate_config_invalid_baseline_mode():
    gs = _store()
    with pytest.raises(ValueError, match="baseline_mode"):
        gs.create_gate_config(name="bad", baseline_mode="magic")


def test_create_gate_config_invalid_pass_rate_drop():
    gs = _store()
    with pytest.raises(ValueError, match="max_pass_rate_drop"):
        gs.create_gate_config(name="bad", max_pass_rate_drop=0.0)
    with pytest.raises(ValueError, match="max_pass_rate_drop"):
        gs.create_gate_config(name="bad2", max_pass_rate_drop=1.1)


def test_create_gate_config_duplicate_name_raises():
    gs = _store()
    gs.create_gate_config(name="my-gate")
    with pytest.raises(ValueError, match="already exists"):
        gs.create_gate_config(name="my-gate")


def test_get_gate_config_by_id():
    gs = _store()
    cfg = gs.create_gate_config(name="test-gate", kind="ci")
    fetched = gs.get_gate_config(cfg["id"])
    assert fetched is not None
    assert fetched["name"] == "test-gate"


def test_get_gate_config_not_found():
    gs = _store()
    assert gs.get_gate_config(9999) is None


def test_get_gate_config_by_name():
    gs = _store()
    gs.create_gate_config(name="lookup-me", kind="nightly")
    cfg = gs.get_gate_config_by_name("lookup-me")
    assert cfg is not None
    assert cfg["kind"] == "nightly"


def test_get_gate_config_by_name_not_found():
    gs = _store()
    assert gs.get_gate_config_by_name("nonexistent") is None


def test_list_gate_configs_empty():
    gs = _store()
    assert gs.list_gate_configs() == []


def test_list_gate_configs_all():
    gs = _store()
    gs.create_gate_config(name="a", kind="nightly")
    gs.create_gate_config(name="b", kind="ci")
    configs = gs.list_gate_configs()
    assert len(configs) == 2


def test_list_gate_configs_filter_by_kind():
    gs = _store()
    gs.create_gate_config(name="n1", kind="nightly")
    gs.create_gate_config(name="c1", kind="ci")
    gs.create_gate_config(name="n2", kind="nightly")

    nightly = gs.list_gate_configs(kind="nightly")
    assert len(nightly) == 2
    assert all(c["kind"] == "nightly" for c in nightly)

    ci = gs.list_gate_configs(kind="ci")
    assert len(ci) == 1
    assert ci[0]["name"] == "c1"


def test_list_gate_configs_filter_by_enabled():
    gs = _store()
    gs.create_gate_config(name="enabled-gate", enabled=True)
    gs.create_gate_config(name="disabled-gate", enabled=False)

    enabled = gs.list_gate_configs(enabled=True)
    assert len(enabled) == 1
    assert enabled[0]["name"] == "enabled-gate"

    disabled = gs.list_gate_configs(enabled=False)
    assert len(disabled) == 1
    assert disabled[0]["name"] == "disabled-gate"


def test_update_gate_config_toggle_enabled():
    gs = _store()
    cfg = gs.create_gate_config(name="toggle-test", enabled=True)
    updated = gs.update_gate_config(cfg["id"], updates={"enabled": False})
    assert updated is not None
    assert updated["enabled"] is False


def test_update_gate_config_thresholds():
    gs = _store()
    cfg = gs.create_gate_config(name="threshold-update")
    updated = gs.update_gate_config(
        cfg["id"],
        updates={"max_pass_rate_drop": 0.08, "max_fail_count_increase": 3},
    )
    assert updated["max_pass_rate_drop"] == pytest.approx(0.08)
    assert updated["max_fail_count_increase"] == 3


def test_update_gate_config_unknown_field_raises():
    gs = _store()
    cfg = gs.create_gate_config(name="bad-update")
    with pytest.raises(ValueError, match="Unknown update fields"):
        gs.update_gate_config(cfg["id"], updates={"nonexistent_field": 42})


def test_update_gate_config_not_found_returns_none():
    gs = _store()
    result = gs.update_gate_config(9999, updates={"enabled": False})
    assert result is None


# ─── Gate Run CRUD ────────────────────────────────────────────────────────────

def test_create_gate_run_minimal():
    gs = _store()
    cfg = gs.create_gate_config(name="run-test")
    run = gs.create_gate_run(
        config_id=cfg["id"],
        kind="nightly",
        trigger_source="manual",
        baseline_batch_id=None,
        candidate_batch_id=None,
        decision="no_baseline",
        decision_reason="No prior run.",
    )
    assert run["id"] > 0
    assert run["config_id"] == cfg["id"]
    assert run["decision"] == "no_baseline"
    assert run["trigger_source"] == "manual"
    assert run["baseline_batch_id"] is None
    assert run["candidate_batch_id"] is None


def test_create_gate_run_with_batches():
    gs = _store()
    cfg = gs.create_gate_config(name="run-with-batches", kind="ci")
    run = gs.create_gate_run(
        config_id=cfg["id"],
        kind="ci",
        trigger_source="ci",
        baseline_batch_id=1,
        candidate_batch_id=2,
        decision="pass",
        decision_reason="All thresholds met.",
        pass_rate_drop=-0.02,
        fail_count_delta=0,
        error_count_delta=0,
    )
    assert run["decision"] == "pass"
    assert run["baseline_batch_id"] == 1
    assert run["candidate_batch_id"] == 2
    assert run["pass_rate_drop"] == pytest.approx(-0.02)


def test_create_gate_run_invalid_decision():
    gs = _store()
    cfg = gs.create_gate_config(name="inv-decision")
    with pytest.raises(ValueError, match="decision"):
        gs.create_gate_run(
            config_id=cfg["id"],
            kind="nightly",
            trigger_source="manual",
            baseline_batch_id=None,
            candidate_batch_id=None,
            decision="unknown_decision",
            decision_reason="",
        )


def test_get_gate_run():
    gs = _store()
    cfg = gs.create_gate_config(name="get-run-test")
    run = gs.create_gate_run(
        config_id=cfg["id"],
        kind="nightly",
        trigger_source="nightly",
        baseline_batch_id=None,
        candidate_batch_id=5,
        decision="error",
        decision_reason="Batch failed.",
    )
    fetched = gs.get_gate_run(run["id"])
    assert fetched is not None
    assert fetched["decision"] == "error"
    assert fetched["candidate_batch_id"] == 5


def test_get_gate_run_not_found():
    gs = _store()
    assert gs.get_gate_run(9999) is None


def test_list_gate_runs_empty():
    gs = _store()
    assert gs.list_gate_runs() == []


def test_list_gate_runs_newest_first():
    gs = _store()
    cfg = gs.create_gate_config(name="list-order")
    gs.create_gate_run(
        config_id=cfg["id"], kind="nightly", trigger_source="manual",
        baseline_batch_id=None, candidate_batch_id=1,
        decision="pass", decision_reason="first",
    )
    time.sleep(0.01)
    gs.create_gate_run(
        config_id=cfg["id"], kind="nightly", trigger_source="manual",
        baseline_batch_id=1, candidate_batch_id=2,
        decision="fail", decision_reason="second",
    )

    runs = gs.list_gate_runs()
    assert len(runs) == 2
    assert runs[0]["decision"] == "fail"   # newer first
    assert runs[1]["decision"] == "pass"


def test_list_gate_runs_filter_by_config():
    gs = _store()
    cfg1 = gs.create_gate_config(name="cfg-a")
    cfg2 = gs.create_gate_config(name="cfg-b")
    gs.create_gate_run(
        config_id=cfg1["id"], kind="nightly", trigger_source="manual",
        baseline_batch_id=None, candidate_batch_id=1, decision="pass", decision_reason="",
    )
    gs.create_gate_run(
        config_id=cfg2["id"], kind="ci", trigger_source="ci",
        baseline_batch_id=None, candidate_batch_id=2, decision="no_baseline", decision_reason="",
    )

    runs_a = gs.list_gate_runs(config_id=cfg1["id"])
    assert len(runs_a) == 1
    assert runs_a[0]["config_id"] == cfg1["id"]

    runs_b = gs.list_gate_runs(config_id=cfg2["id"])
    assert len(runs_b) == 1
    assert runs_b[0]["config_id"] == cfg2["id"]


def test_list_gate_runs_filter_by_decision():
    gs = _store()
    cfg = gs.create_gate_config(name="decision-filter")
    for dec in ("pass", "fail", "no_baseline"):
        gs.create_gate_run(
            config_id=cfg["id"], kind="nightly", trigger_source="manual",
            baseline_batch_id=None, candidate_batch_id=None,
            decision=dec, decision_reason="",
        )

    fails = gs.list_gate_runs(decision="fail")
    assert len(fails) == 1
    assert fails[0]["decision"] == "fail"


def test_get_most_recent_gate_run_for_config():
    gs = _store()
    cfg = gs.create_gate_config(name="most-recent")
    gs.create_gate_run(
        config_id=cfg["id"], kind="nightly", trigger_source="manual",
        baseline_batch_id=None, candidate_batch_id=1, decision="pass", decision_reason="old",
    )
    time.sleep(0.01)
    gs.create_gate_run(
        config_id=cfg["id"], kind="nightly", trigger_source="nightly",
        baseline_batch_id=1, candidate_batch_id=2, decision="pass", decision_reason="newest",
    )

    latest = gs.get_most_recent_gate_run_for_config(cfg["id"])
    assert latest is not None
    assert latest["decision_reason"] == "newest"
    assert latest["candidate_batch_id"] == 2


def test_get_most_recent_gate_run_no_runs():
    gs = _store()
    cfg = gs.create_gate_config(name="no-runs-yet")
    assert gs.get_most_recent_gate_run_for_config(cfg["id"]) is None


# ─── Threshold rules ──────────────────────────────────────────────────────────

def _thresholds(**kwargs):
    from orchestrator.eval_gate_runner import _apply_thresholds
    return _apply_thresholds(**kwargs)


def test_threshold_pass_no_rules():
    """No thresholds configured → always pass."""
    comparison = {
        "delta_pass_rate": -0.10,
        "delta_fail_count": 5,
        "delta_error_count": 2,
        "baseline_pass_rate": 0.80,
        "candidate_pass_rate": 0.70,
    }
    decision, reason = _thresholds(
        comparison=comparison,
        max_pass_rate_drop=None,
        max_fail_count_increase=None,
        block_on_error_increase=False,
    )
    assert decision == "pass"


def test_threshold_fail_pass_rate_drop():
    """Pass rate drops more than threshold → fail."""
    comparison = {
        "delta_pass_rate": -0.08,  # 8% drop
        "delta_fail_count": 0,
        "delta_error_count": 0,
        "baseline_pass_rate": 0.78,
        "candidate_pass_rate": 0.70,
    }
    decision, reason = _thresholds(
        comparison=comparison,
        max_pass_rate_drop=0.05,
        max_fail_count_increase=None,
        block_on_error_increase=False,
    )
    assert decision == "fail"
    assert "pass rate" in reason.lower()
    assert "threshold" in reason.lower()


def test_threshold_pass_rate_drop_within_threshold():
    """Pass rate drops within threshold → pass."""
    comparison = {
        "delta_pass_rate": -0.03,  # 3% drop, threshold = 5%
        "delta_fail_count": 0,
        "delta_error_count": 0,
        "baseline_pass_rate": 0.80,
        "candidate_pass_rate": 0.77,
    }
    decision, reason = _thresholds(
        comparison=comparison,
        max_pass_rate_drop=0.05,
        max_fail_count_increase=None,
        block_on_error_increase=False,
    )
    assert decision == "pass"


def test_threshold_fail_fail_count_increase():
    """Fail count increases beyond threshold → fail."""
    comparison = {
        "delta_pass_rate": 0.0,
        "delta_fail_count": 5,
        "delta_error_count": 0,
        "baseline_pass_rate": 0.80,
        "candidate_pass_rate": 0.80,
    }
    decision, reason = _thresholds(
        comparison=comparison,
        max_pass_rate_drop=None,
        max_fail_count_increase=3,
        block_on_error_increase=False,
    )
    assert decision == "fail"
    assert "fail count" in reason.lower()


def test_threshold_fail_count_within_threshold():
    """Fail count increases within threshold → pass."""
    comparison = {
        "delta_pass_rate": 0.0,
        "delta_fail_count": 2,
        "delta_error_count": 0,
        "baseline_pass_rate": 0.80,
        "candidate_pass_rate": 0.80,
    }
    decision, reason = _thresholds(
        comparison=comparison,
        max_pass_rate_drop=None,
        max_fail_count_increase=3,
        block_on_error_increase=False,
    )
    assert decision == "pass"


def test_threshold_fail_on_error_increase():
    """Error count increases when block_on_error_increase=True → fail."""
    comparison = {
        "delta_pass_rate": 0.0,
        "delta_fail_count": 0,
        "delta_error_count": 1,
        "baseline_pass_rate": 0.80,
        "candidate_pass_rate": 0.80,
    }
    decision, reason = _thresholds(
        comparison=comparison,
        max_pass_rate_drop=None,
        max_fail_count_increase=None,
        block_on_error_increase=True,
    )
    assert decision == "fail"
    assert "error" in reason.lower()


def test_threshold_no_error_increase_passes():
    """Error count stable when block_on_error_increase=True → pass."""
    comparison = {
        "delta_pass_rate": 0.0,
        "delta_fail_count": 0,
        "delta_error_count": 0,
        "baseline_pass_rate": 0.80,
        "candidate_pass_rate": 0.80,
    }
    decision, reason = _thresholds(
        comparison=comparison,
        max_pass_rate_drop=None,
        max_fail_count_increase=None,
        block_on_error_increase=True,
    )
    assert decision == "pass"


def test_threshold_multiple_failures_combined_reason():
    """Multiple threshold violations → all appear in reason."""
    comparison = {
        "delta_pass_rate": -0.10,
        "delta_fail_count": 5,
        "delta_error_count": 1,
        "baseline_pass_rate": 0.80,
        "candidate_pass_rate": 0.70,
    }
    decision, reason = _thresholds(
        comparison=comparison,
        max_pass_rate_drop=0.05,
        max_fail_count_increase=3,
        block_on_error_increase=True,
    )
    assert decision == "fail"
    assert "pass rate" in reason.lower()
    assert "fail count" in reason.lower()
    assert "error" in reason.lower()


# ─── Baseline resolution ──────────────────────────────────────────────────────

def test_baseline_resolution_no_prior_run(tmp_path, monkeypatch):
    """previous_gate_run mode: no prior gate run → returns None (no_baseline)."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    import config.settings as settings_mod
    importlib.reload(settings_mod)
    import orchestrator.eval_gate_store as gs
    gs._initialised_paths.clear()
    importlib.reload(gs)
    import orchestrator.eval_case_store as ecs
    ecs._initialised_paths.clear()
    importlib.reload(ecs)

    from orchestrator.eval_gate_runner import _resolve_baseline

    cfg = gs.create_gate_config(name="no-prior-run")
    result = _resolve_baseline(
        config_id=cfg["id"],
        candidate_batch_id=99,
        baseline_mode="previous_gate_run",
    )
    assert result is None


def test_baseline_resolution_previous_gate_run(tmp_path, monkeypatch):
    """previous_gate_run mode: prior gate run exists → returns its candidate_batch_id."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma2"))
    import config.settings as settings_mod
    importlib.reload(settings_mod)
    import orchestrator.eval_gate_store as gs
    gs._initialised_paths.clear()
    importlib.reload(gs)
    import orchestrator.eval_case_store as ecs
    ecs._initialised_paths.clear()
    importlib.reload(ecs)

    from orchestrator.eval_gate_runner import _resolve_baseline

    cfg = gs.create_gate_config(name="with-prior-run")
    # Create a prior gate run with candidate_batch_id=10
    gs.create_gate_run(
        config_id=cfg["id"],
        kind="nightly",
        trigger_source="nightly",
        baseline_batch_id=None,
        candidate_batch_id=10,
        decision="pass",
        decision_reason="",
    )

    baseline = _resolve_baseline(
        config_id=cfg["id"],
        candidate_batch_id=20,
        baseline_mode="previous_gate_run",
    )
    assert baseline == 10


def test_baseline_resolution_previous_batch_mode(tmp_path, monkeypatch):
    """previous_batch mode: finds the batch immediately before candidate."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma3"))
    import config.settings as settings_mod
    importlib.reload(settings_mod)
    import orchestrator.eval_gate_store as gs
    gs._initialised_paths.clear()
    importlib.reload(gs)
    import orchestrator.eval_case_store as ecs
    ecs._initialised_paths.clear()
    importlib.reload(ecs)

    # Create two batches
    b1 = ecs.create_eval_batch(label="batch1", filters={}, total_cases=2, pass_count=2, fail_count=0)
    b2 = ecs.create_eval_batch(label="batch2", filters={}, total_cases=2, pass_count=1, fail_count=1)

    from orchestrator.eval_gate_runner import _resolve_baseline
    cfg = gs.create_gate_config(name="prev-batch-test")

    baseline = _resolve_baseline(
        config_id=cfg["id"],
        candidate_batch_id=b2["id"],
        baseline_mode="previous_batch",
    )
    assert baseline == b1["id"]
