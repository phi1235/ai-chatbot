"""Tests for eval gate API endpoints.

Covers:
- Gate config CRUD
- Manual gate run flow (batch + comparison + gate result)
- No-baseline decision is explicit
- Pass-rate threshold failure
- Fail-count threshold failure
- Error-count rule
- Nightly execution path (enabled nightly configs only)
- CI gate run path
- Gate run list/detail
- Baseline resolution behavior
- CLI entry point exit codes
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Isolated DB + fresh module state for each test."""
    sources = tmp_path / "sources"
    sources.mkdir()
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.chdir(tmp_path)

    import config.settings as settings_mod
    importlib.reload(settings_mod)
    import orchestrator.store as store_mod
    importlib.reload(store_mod)
    import orchestrator.feedback_store as fb_mod
    fb_mod._initialised_paths.clear()
    importlib.reload(fb_mod)
    import orchestrator.freshness_store as fs_mod
    fs_mod._initialised_paths.clear()
    importlib.reload(fs_mod)
    import orchestrator.eval_case_store as ecs_mod
    ecs_mod._initialised_paths.clear()
    importlib.reload(ecs_mod)
    import orchestrator.eval_gate_store as gs_mod
    gs_mod._initialised_paths.clear()
    importlib.reload(gs_mod)
    import api.admin as admin_mod
    importlib.reload(admin_mod)

    from api.main import app
    return TestClient(app)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _create_reviewed_feedback(client, *, root_cause="retrieval_miss", topic="kubernetes"):
    r = client.post("/feedback", json={
        "question": "How to deploy pods?",
        "answer": "Use kubectl.",
        "feedback_type": "down",
        "detected_topic": topic,
        "rewritten_query": "deploy kubernetes pods",
        "retrieval_count": 2,
        "citations_snapshot": [{"title": "K8s docs", "url": "https://k8s.io"}],
        "trace_snapshot": {"request_id": "r1"},
    })
    fb_id = r.json()["id"]
    client.post(f"/admin/feedback/{fb_id}/review", json={
        "review_status": "reviewed",
        "root_cause": root_cause,
    })
    return fb_id


def _create_eval_case(client, feedback_id: int):
    return client.post(f"/admin/feedback/{feedback_id}/eval-case")


def _mock_rag_pass():
    from schemas.chat import Citation
    mock = MagicMock()
    mock.answer = "Kubernetes is a container orchestration platform."
    mock.detected_topic = "kubernetes"
    mock.retrieval_count = 3
    mock.citations = [Citation(title="K8s docs", url="https://k8s.io")]
    return mock


def _setup_eval_case(client) -> int:
    """Create one reviewed feedback + one active eval case. Returns case_id."""
    fb_id = _create_reviewed_feedback(client)
    return _create_eval_case(client, fb_id).json()["id"]


def _run_batch(client) -> dict:
    """Run a batch (with mock) and return the batch dict."""
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-cases/run-batch", json={})
    assert r.status_code == 200
    return r.json()


def _create_gate_config(client, **kwargs) -> dict:
    payload = {"name": "test-gate", "kind": "nightly", **kwargs}
    r = client.post("/admin/eval-gates/configs", json=payload)
    assert r.status_code == 200, r.json()
    return r.json()


# ─── Gate Config CRUD ────────────────────────────────────────────────────────

def test_list_gate_configs_empty(client):
    r = client.get("/admin/eval-gates/configs")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["configs"] == []


def test_create_gate_config_defaults(client):
    r = client.post("/admin/eval-gates/configs", json={"name": "nightly-default"})
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["id"] > 0
    assert cfg["name"] == "nightly-default"
    assert cfg["kind"] == "nightly"
    assert cfg["enabled"] is True
    assert cfg["baseline_mode"] == "previous_gate_run"
    assert cfg["max_pass_rate_drop"] is None
    assert cfg["max_fail_count_increase"] is None
    assert cfg["block_on_error_increase"] is False


def test_create_gate_config_ci_with_thresholds(client):
    r = client.post("/admin/eval-gates/configs", json={
        "name": "ci-smoke",
        "kind": "ci",
        "max_pass_rate_drop": 0.05,
        "max_fail_count_increase": 2,
        "block_on_error_increase": True,
    })
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["kind"] == "ci"
    assert cfg["max_pass_rate_drop"] == pytest.approx(0.05)
    assert cfg["max_fail_count_increase"] == 2
    assert cfg["block_on_error_increase"] is True


def test_create_gate_config_invalid_kind(client):
    r = client.post("/admin/eval-gates/configs", json={"name": "bad", "kind": "weekly"})
    assert r.status_code == 400
    assert "kind" in r.json()["detail"].lower()


def test_create_gate_config_invalid_pass_rate_drop(client):
    r = client.post("/admin/eval-gates/configs", json={
        "name": "bad-threshold", "max_pass_rate_drop": 0.0
    })
    assert r.status_code == 400


def test_create_gate_config_duplicate_name(client):
    client.post("/admin/eval-gates/configs", json={"name": "dup-name"})
    r2 = client.post("/admin/eval-gates/configs", json={"name": "dup-name"})
    assert r2.status_code == 400
    assert "already exists" in r2.json()["detail"].lower()


def test_list_gate_configs_returns_all(client):
    _create_gate_config(client, name="cfg-1")
    _create_gate_config(client, name="cfg-2", kind="ci")
    r = client.get("/admin/eval-gates/configs")
    assert r.json()["count"] == 2


def test_list_gate_configs_filter_kind(client):
    _create_gate_config(client, name="n1", kind="nightly")
    _create_gate_config(client, name="c1", kind="ci")
    r = client.get("/admin/eval-gates/configs", params={"kind": "ci"})
    assert r.json()["count"] == 1
    assert r.json()["configs"][0]["kind"] == "ci"


def test_patch_gate_config_toggle_enabled(client):
    cfg = _create_gate_config(client, enabled=True)
    r = client.patch(f"/admin/eval-gates/configs/{cfg['id']}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_patch_gate_config_update_thresholds(client):
    cfg = _create_gate_config(client)
    r = client.patch(f"/admin/eval-gates/configs/{cfg['id']}", json={
        "max_pass_rate_drop": 0.10,
        "max_fail_count_increase": 5,
    })
    assert r.status_code == 200
    updated = r.json()
    assert updated["max_pass_rate_drop"] == pytest.approx(0.10)
    assert updated["max_fail_count_increase"] == 5


def test_patch_gate_config_not_found(client):
    r = client.patch("/admin/eval-gates/configs/9999", json={"enabled": False})
    assert r.status_code == 404


# ─── Manual gate run: no_baseline (first run) ─────────────────────────────────

def test_gate_run_first_time_no_baseline(client):
    """First gate run for a config → no_baseline decision (no prior gate run)."""
    _setup_eval_case(client)
    cfg = _create_gate_config(client, baseline_mode="previous_gate_run")

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})

    assert r.status_code == 200
    gate_run = r.json()
    assert gate_run["decision"] == "no_baseline"
    assert gate_run["candidate_batch_id"] is not None  # batch was still created
    assert gate_run["baseline_batch_id"] is None


# ─── Manual gate run: pass ────────────────────────────────────────────────────

def test_gate_run_pass_with_prior_run(client):
    """Second gate run with stable results → pass."""
    _setup_eval_case(client)
    cfg = _create_gate_config(
        client,
        baseline_mode="previous_gate_run",
        max_pass_rate_drop=0.05,
    )

    # First run → no_baseline (establishes first batch)
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r1 = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})
    assert r1.json()["decision"] == "no_baseline"

    # Second run → has baseline (from first run's candidate batch), stable → pass
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r2 = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})

    assert r2.status_code == 200
    gate_run = r2.json()
    assert gate_run["decision"] == "pass"
    assert gate_run["baseline_batch_id"] is not None
    assert gate_run["candidate_batch_id"] is not None
    assert gate_run["candidate_batch_id"] != gate_run["baseline_batch_id"]


# ─── Manual gate run: fail on pass rate drop ──────────────────────────────────

def test_gate_run_fail_on_pass_rate_drop(client):
    """Pass rate drops beyond threshold → decision=fail."""
    # Setup two eval cases
    fb1 = _create_reviewed_feedback(client, root_cause="retrieval_miss")
    fb2 = _create_reviewed_feedback(client, root_cause="hallucination", topic="docker")
    _create_eval_case(client, fb1)
    _create_eval_case(client, fb2)

    # Config: 5% threshold
    cfg = _create_gate_config(client, baseline_mode="previous_gate_run", max_pass_rate_drop=0.05)

    # First run: both cases pass → no_baseline, but creates batch with 100% pass rate
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r1 = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})
    assert r1.json()["decision"] == "no_baseline"

    # Second run: both cases fail → 0% pass rate vs 100% baseline → fail
    failing_mock = MagicMock()
    failing_mock.answer = "hiện tại tôi chưa tìm thấy thông tin"
    failing_mock.detected_topic = "kubernetes"
    failing_mock.retrieval_count = 0
    failing_mock.citations = []

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=failing_mock):
        r2 = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})

    assert r2.status_code == 200
    gate_run = r2.json()
    assert gate_run["decision"] == "fail"
    assert "pass rate" in gate_run["decision_reason"].lower()
    assert gate_run["pass_rate_drop"] is not None


# ─── Manual gate run: fail on fail count increase ─────────────────────────────

def test_gate_run_fail_on_fail_count_increase(client):
    """Fail count increases beyond threshold → decision=fail."""
    fb1 = _create_reviewed_feedback(client)
    fb2 = _create_reviewed_feedback(client, root_cause="hallucination", topic="docker")
    _create_eval_case(client, fb1)
    _create_eval_case(client, fb2)

    cfg = _create_gate_config(client, baseline_mode="previous_gate_run", max_fail_count_increase=0)

    # First run: all pass → no_baseline
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r1 = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})
    assert r1.json()["decision"] == "no_baseline"

    # Second run: all fail → fail count increased by 2 > threshold 0
    failing_mock = MagicMock()
    failing_mock.answer = "hiện tại tôi chưa tìm thấy thông tin"
    failing_mock.detected_topic = "kubernetes"
    failing_mock.retrieval_count = 0
    failing_mock.citations = []

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=failing_mock):
        r2 = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})

    gate_run = r2.json()
    assert gate_run["decision"] == "fail"
    assert "fail count" in gate_run["decision_reason"].lower()


# ─── Manual gate run: error handling ─────────────────────────────────────────

def test_gate_run_no_cases_returns_error(client):
    """If no eval cases match filters → gate decision is error."""
    cfg = _create_gate_config(client)  # no eval cases in DB
    r = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})
    assert r.status_code == 200
    assert r.json()["decision"] == "error"
    assert "no matching" in r.json()["decision_reason"].lower()


def test_gate_run_not_found(client):
    r = client.post("/admin/eval-gates/configs/9999/run", json={})
    assert r.status_code == 404


# ─── Gate run list + detail ───────────────────────────────────────────────────

def test_list_gate_runs_empty(client):
    r = client.get("/admin/eval-gates/runs")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["runs"] == []


def test_list_gate_runs_after_run(client):
    _setup_eval_case(client)
    cfg = _create_gate_config(client)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})

    r = client.get("/admin/eval-gates/runs")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    run = data["runs"][0]
    assert "decision" in run
    assert "config_id" in run
    assert "trigger_source" in run
    assert "created_at" in run


def test_list_gate_runs_filter_by_config(client):
    _setup_eval_case(client)
    cfg1 = _create_gate_config(client, name="cfg-filter-a")
    cfg2 = _create_gate_config(client, name="cfg-filter-b")

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        client.post(f"/admin/eval-gates/configs/{cfg1['id']}/run", json={})
        client.post(f"/admin/eval-gates/configs/{cfg2['id']}/run", json={})

    r = client.get("/admin/eval-gates/runs", params={"config_id": cfg1["id"]})
    assert r.json()["count"] == 1
    assert r.json()["runs"][0]["config_id"] == cfg1["id"]


def test_list_gate_runs_filter_by_decision(client):
    _setup_eval_case(client)
    cfg = _create_gate_config(client)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})

    # Filter for no_baseline (should match first run)
    r = client.get("/admin/eval-gates/runs", params={"decision": "no_baseline"})
    assert r.json()["count"] == 1

    # Filter for pass (should be empty)
    r2 = client.get("/admin/eval-gates/runs", params={"decision": "pass"})
    assert r2.json()["count"] == 0


def test_list_gate_runs_invalid_decision_rejected(client):
    r = client.get("/admin/eval-gates/runs", params={"decision": "unknown"})
    assert r.status_code == 400


def test_get_gate_run_detail(client):
    _setup_eval_case(client)
    cfg = _create_gate_config(client)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        run_r = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})
    run_id = run_r.json()["id"]

    r = client.get(f"/admin/eval-gates/runs/{run_id}")
    assert r.status_code == 200
    run = r.json()
    assert run["id"] == run_id
    assert "decision" in run
    assert "decision_reason" in run


def test_get_gate_run_not_found(client):
    r = client.get("/admin/eval-gates/runs/9999")
    assert r.status_code == 404


# ─── Nightly path: only enabled nightly configs run ───────────────────────────

def test_run_nightly_no_configs(client):
    """No enabled nightly configs → ran=0."""
    r = client.post("/admin/eval-gates/run-nightly")
    assert r.status_code == 200
    data = r.json()
    assert data["ran"] == 0
    assert data["any_fail"] is False
    assert data["summary"] == []


def test_run_nightly_only_nightly_kind_runs(client):
    """run-nightly should only run 'nightly' kind, not 'ci' kind."""
    _setup_eval_case(client)
    _create_gate_config(client, name="nightly-gate", kind="nightly", enabled=True)
    _create_gate_config(client, name="ci-gate", kind="ci", enabled=True)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-gates/run-nightly")

    assert r.status_code == 200
    data = r.json()
    assert data["ran"] == 1
    # Only the nightly config ran
    assert data["summary"][0]["config_id"] is not None


def test_run_nightly_disabled_configs_skipped(client):
    """Disabled nightly configs are not run."""
    _setup_eval_case(client)
    _create_gate_config(client, name="disabled-nightly", kind="nightly", enabled=False)
    _create_gate_config(client, name="enabled-nightly", kind="nightly", enabled=True)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-gates/run-nightly")

    assert r.status_code == 200
    data = r.json()
    assert data["ran"] == 1


def test_run_nightly_returns_summary_per_config(client):
    """Nightly response has one summary entry per config."""
    _setup_eval_case(client)
    _create_gate_config(client, name="n1", kind="nightly", enabled=True)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-gates/run-nightly")

    data = r.json()
    assert len(data["summary"]) == 1
    s = data["summary"][0]
    assert "gate_run_id" in s
    assert "decision" in s
    assert "decision_reason" in s


# ─── CI gate path ─────────────────────────────────────────────────────────────

def test_run_ci_not_found(client):
    r = client.post("/admin/eval-gates/run-ci", json={"config_name": "nonexistent-ci"})
    assert r.status_code == 404
    assert "nonexistent-ci" in r.json()["detail"]


def test_run_ci_returns_gate_run(client):
    """CI gate run returns gate run dict with decision field."""
    _setup_eval_case(client)
    _create_gate_config(client, name="ci-default", kind="ci")

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-gates/run-ci", json={"config_name": "ci-default"})

    assert r.status_code == 200
    gate_run = r.json()
    assert gate_run["decision"] in ("pass", "fail", "no_baseline", "error")
    assert gate_run["trigger_source"] == "ci"
    assert gate_run["kind"] == "ci"


def test_run_ci_trigger_source_is_ci(client):
    _setup_eval_case(client)
    _create_gate_config(client, name="ci-trigger-check", kind="ci")

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post("/admin/eval-gates/run-ci", json={"config_name": "ci-trigger-check"})

    assert r.json()["trigger_source"] == "ci"


# ─── Gate run records baseline resolution behavior ────────────────────────────

def test_second_run_uses_first_run_candidate_as_baseline(client):
    """Baseline resolution: second run uses first run's candidate_batch_id as baseline."""
    _setup_eval_case(client)
    cfg = _create_gate_config(client, baseline_mode="previous_gate_run")

    # First run
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r1 = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})
    first_candidate = r1.json()["candidate_batch_id"]
    assert r1.json()["decision"] == "no_baseline"

    # Second run
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r2 = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})
    second_run = r2.json()

    assert second_run["baseline_batch_id"] == first_candidate
    assert second_run["candidate_batch_id"] != first_candidate


def test_baseline_mode_previous_batch_resolves_immediately_prior(client):
    """previous_batch mode: baseline is the batch immediately before candidate."""
    _setup_eval_case(client)
    cfg = _create_gate_config(client, baseline_mode="previous_batch")

    # First run → candidate batch created, no_baseline (no prior batch before it at run time)
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r1 = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})
    first_candidate_id = r1.json()["candidate_batch_id"]

    # Second run → candidate is a new batch; previous batch = first_candidate_id
    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r2 = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={})
    second_run = r2.json()

    assert second_run["baseline_batch_id"] == first_candidate_id


# ─── Manual trigger source ────────────────────────────────────────────────────

def test_manual_trigger_source_stored(client):
    _setup_eval_case(client)
    cfg = _create_gate_config(client)

    with patch("orchestrator.eval_runner._chat_with_trace", return_value=_mock_rag_pass()):
        r = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={"trigger_source": "manual"})

    assert r.json()["trigger_source"] == "manual"


def test_invalid_trigger_source_rejected(client):
    _setup_eval_case(client)
    cfg = _create_gate_config(client)

    r = client.post(f"/admin/eval-gates/configs/{cfg['id']}/run", json={"trigger_source": "webhook"})
    assert r.status_code == 400


# ─── CLI entry point ──────────────────────────────────────────────────────────

def test_cli_exits_nonzero_on_config_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    import config.settings as settings_mod
    importlib.reload(settings_mod)
    import orchestrator.eval_gate_store as gs_mod
    gs_mod._initialised_paths.clear()
    importlib.reload(gs_mod)

    from orchestrator.eval_gate_runner import _cli_main
    exit_code = _cli_main(["--config", "nonexistent-gate"])
    assert exit_code == 1


def test_cli_exits_zero_on_pass(tmp_path, monkeypatch):
    """CLI exits 0 when gate decision is pass."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    import config.settings as settings_mod
    importlib.reload(settings_mod)
    import orchestrator.eval_gate_store as gs_mod
    gs_mod._initialised_paths.clear()
    importlib.reload(gs_mod)
    import orchestrator.eval_case_store as ecs_mod
    ecs_mod._initialised_paths.clear()
    importlib.reload(ecs_mod)

    # Create a gate config that will produce "pass" (mocked)
    import orchestrator.eval_gate_store as gs
    gs.create_gate_config(name="cli-pass-gate", kind="ci")

    from orchestrator.eval_gate_runner import _cli_main

    # Mock run_gate to return pass decision
    with patch("orchestrator.eval_gate_runner.run_gate") as mock_run:
        mock_run.return_value = {
            "id": 1,
            "decision": "pass",
            "decision_reason": "all thresholds met",
        }
        exit_code = _cli_main(["--config", "cli-pass-gate"])
    assert exit_code == 0


def test_cli_exits_nonzero_on_fail(tmp_path, monkeypatch):
    """CLI exits 1 when gate decision is fail."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    import config.settings as settings_mod
    importlib.reload(settings_mod)
    import orchestrator.eval_gate_store as gs_mod
    gs_mod._initialised_paths.clear()
    importlib.reload(gs_mod)

    from orchestrator.eval_gate_runner import _cli_main

    with patch("orchestrator.eval_gate_runner.run_gate") as mock_run:
        mock_run.return_value = {
            "id": 2,
            "decision": "fail",
            "decision_reason": "pass rate dropped 8%",
        }
        exit_code = _cli_main(["--config", "some-gate"])
    assert exit_code == 1


def test_cli_exits_nonzero_on_no_baseline(tmp_path, monkeypatch):
    """CLI exits 1 when gate decision is no_baseline."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    import config.settings as settings_mod
    importlib.reload(settings_mod)
    import orchestrator.eval_gate_store as gs_mod
    gs_mod._initialised_paths.clear()
    importlib.reload(gs_mod)

    from orchestrator.eval_gate_runner import _cli_main

    with patch("orchestrator.eval_gate_runner.run_gate") as mock_run:
        mock_run.return_value = {
            "id": 3,
            "decision": "no_baseline",
            "decision_reason": "No prior run.",
        }
        exit_code = _cli_main(["--config", "some-gate"])
    assert exit_code == 1
