"""Eval Gate persistence – SQLite backend.

Stores gate configs (automated eval profiles) and gate run records.
Schema lives in the same DB file as eval_cases/batches for simplicity.

Schema:
    eval_gate_configs(
        id                      INTEGER PK AUTOINCREMENT,
        name                    TEXT NOT NULL UNIQUE,
        kind                    TEXT NOT NULL,           -- nightly | ci
        enabled                 INTEGER NOT NULL DEFAULT 1,
        status_filter           TEXT NOT NULL DEFAULT 'active',
        root_cause              TEXT,
        expected_topic          TEXT,
        limit_cases             INTEGER,
        run_label_template      TEXT,
        baseline_mode           TEXT NOT NULL DEFAULT 'previous_gate_run',
        max_pass_rate_drop      REAL,
        max_fail_count_increase INTEGER,
        block_on_error_increase INTEGER NOT NULL DEFAULT 0,
        created_at              REAL NOT NULL,
        updated_at              REAL NOT NULL
    )

    eval_gate_runs(
        id                  INTEGER PK AUTOINCREMENT,
        config_id           INTEGER NOT NULL,
        kind                TEXT NOT NULL,
        trigger_source      TEXT NOT NULL,   -- manual | nightly | ci
        baseline_batch_id   INTEGER,
        candidate_batch_id  INTEGER,
        decision            TEXT NOT NULL,   -- pass | fail | no_baseline | error
        decision_reason     TEXT NOT NULL,
        pass_rate_drop      REAL,
        fail_count_delta    INTEGER,
        error_count_delta   INTEGER,
        created_at          REAL NOT NULL
    )

Design notes:
- Reuses the same DB path and lock pattern as eval_case_store.
- Gate configs are keyed by unique name for easy CLI references.
- Baseline resolution: previous_gate_run mode uses the candidate_batch_id from
  the most recent prior gate run for the same config.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from threading import Lock

from config.settings import settings

_lock = Lock()
_initialised_paths: set[str] = set()

_VALID_KINDS = frozenset({"nightly", "ci"})
_VALID_TRIGGER_SOURCES = frozenset({"manual", "nightly", "ci"})
_VALID_DECISIONS = frozenset({"pass", "fail", "no_baseline", "error"})
_VALID_BASELINE_MODES = frozenset({"previous_gate_run", "previous_batch"})


# ─── DB plumbing ──────────────────────────────────────────────────────────────

def _get_db_path() -> Path:
    return Path(settings.chroma_path).parent / "eval_cases.sqlite"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema(db_path: Path | None = None) -> None:
    path = db_path or _get_db_path()
    key = str(path) + ":gates"
    if key in _initialised_paths:
        return
    with _lock, _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS eval_gate_configs (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                name                    TEXT NOT NULL UNIQUE,
                kind                    TEXT NOT NULL DEFAULT 'nightly',
                enabled                 INTEGER NOT NULL DEFAULT 1,
                status_filter           TEXT NOT NULL DEFAULT 'active',
                root_cause              TEXT,
                expected_topic          TEXT,
                limit_cases             INTEGER,
                run_label_template      TEXT,
                baseline_mode           TEXT NOT NULL DEFAULT 'previous_gate_run',
                max_pass_rate_drop      REAL,
                max_fail_count_increase INTEGER,
                block_on_error_increase INTEGER NOT NULL DEFAULT 0,
                created_at              REAL NOT NULL,
                updated_at              REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_egc_kind
                ON eval_gate_configs(kind);
            CREATE INDEX IF NOT EXISTS idx_egc_enabled
                ON eval_gate_configs(enabled);

            CREATE TABLE IF NOT EXISTS eval_gate_runs (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                config_id           INTEGER NOT NULL,
                kind                TEXT NOT NULL,
                trigger_source      TEXT NOT NULL,
                baseline_batch_id   INTEGER,
                candidate_batch_id  INTEGER,
                decision            TEXT NOT NULL,
                decision_reason     TEXT NOT NULL DEFAULT '',
                pass_rate_drop      REAL,
                fail_count_delta    INTEGER,
                error_count_delta   INTEGER,
                created_at          REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_egr_config_id
                ON eval_gate_runs(config_id);
            CREATE INDEX IF NOT EXISTS idx_egr_created
                ON eval_gate_runs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_egr_decision
                ON eval_gate_runs(decision);
            """
        )
    _initialised_paths.add(key)


# ─── Gate Config CRUD ─────────────────────────────────────────────────────────

def create_gate_config(
    *,
    name: str,
    kind: str = "nightly",
    enabled: bool = True,
    status_filter: str = "active",
    root_cause: str | None = None,
    expected_topic: str | None = None,
    limit_cases: int | None = None,
    run_label_template: str | None = None,
    baseline_mode: str = "previous_gate_run",
    max_pass_rate_drop: float | None = None,
    max_fail_count_increase: int | None = None,
    block_on_error_increase: bool = False,
) -> dict:
    """Create a new gate config. Raises ValueError on validation failure."""
    name = (name or "").strip()
    if not name:
        raise ValueError("name must not be empty")
    if kind not in _VALID_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(sorted(_VALID_KINDS))}")
    if baseline_mode not in _VALID_BASELINE_MODES:
        raise ValueError(
            f"baseline_mode must be one of: {', '.join(sorted(_VALID_BASELINE_MODES))}"
        )
    if max_pass_rate_drop is not None and not (0 < max_pass_rate_drop <= 1.0):
        raise ValueError("max_pass_rate_drop must be between 0 (exclusive) and 1.0")

    _ensure_schema()
    now = time.time()

    with _lock, _connect() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO eval_gate_configs (
                    name, kind, enabled, status_filter, root_cause, expected_topic,
                    limit_cases, run_label_template, baseline_mode,
                    max_pass_rate_drop, max_fail_count_increase, block_on_error_increase,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    kind,
                    1 if enabled else 0,
                    status_filter or "active",
                    (root_cause or "").strip() or None,
                    (expected_topic or "").strip() or None,
                    limit_cases,
                    (run_label_template or "").strip() or None,
                    baseline_mode,
                    max_pass_rate_drop,
                    max_fail_count_increase,
                    1 if block_on_error_increase else 0,
                    now,
                    now,
                ),
            )
            new_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Gate config name '{name}' already exists") from exc

    return get_gate_config(new_id)  # type: ignore[return-value]


def get_gate_config(config_id: int) -> dict | None:
    """Return a single gate config by id, or None."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM eval_gate_configs WHERE id = ?", (config_id,)
        ).fetchone()
    return _config_row_to_dict(row) if row else None


def get_gate_config_by_name(name: str) -> dict | None:
    """Return a gate config by unique name, or None."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM eval_gate_configs WHERE name = ?", (name,)
        ).fetchone()
    return _config_row_to_dict(row) if row else None


def list_gate_configs(*, kind: str | None = None, enabled: bool | None = None) -> list[dict]:
    """List gate configs. Newest first."""
    _ensure_schema()
    where = ["1=1"]
    params: list[object] = []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if enabled is not None:
        where.append("enabled = ?")
        params.append(1 if enabled else 0)

    with _lock, _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM eval_gate_configs WHERE {' AND '.join(where)} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [_config_row_to_dict(row) for row in rows]


def update_gate_config(config_id: int, *, updates: dict) -> dict | None:
    """Apply partial updates to a gate config. Returns updated config or None."""
    _ensure_schema()

    # Validate updatable fields
    allowed = {
        "name", "kind", "enabled", "status_filter", "root_cause", "expected_topic",
        "limit_cases", "run_label_template", "baseline_mode",
        "max_pass_rate_drop", "max_fail_count_increase", "block_on_error_increase",
    }
    bad = set(updates) - allowed
    if bad:
        raise ValueError(f"Unknown update fields: {', '.join(sorted(bad))}")

    if "kind" in updates and updates["kind"] not in _VALID_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(sorted(_VALID_KINDS))}")
    if "baseline_mode" in updates and updates["baseline_mode"] not in _VALID_BASELINE_MODES:
        raise ValueError(
            f"baseline_mode must be one of: {', '.join(sorted(_VALID_BASELINE_MODES))}"
        )
    if "max_pass_rate_drop" in updates and updates["max_pass_rate_drop"] is not None:
        v = updates["max_pass_rate_drop"]
        if not (0 < v <= 1.0):
            raise ValueError("max_pass_rate_drop must be between 0 (exclusive) and 1.0")

    if not updates:
        return get_gate_config(config_id)

    # Coerce boolean-like fields
    set_clauses: list[str] = []
    values: list[object] = []
    for field, value in updates.items():
        if field in ("enabled", "block_on_error_increase"):
            value = 1 if value else 0
        set_clauses.append(f"{field} = ?")
        values.append(value)

    set_clauses.append("updated_at = ?")
    values.append(time.time())
    values.append(config_id)

    with _lock, _connect() as conn:
        conn.execute(
            f"UPDATE eval_gate_configs SET {', '.join(set_clauses)} WHERE id = ?",
            values,
        )
    return get_gate_config(config_id)


# ─── Gate Run CRUD ────────────────────────────────────────────────────────────

def create_gate_run(
    *,
    config_id: int,
    kind: str,
    trigger_source: str,
    baseline_batch_id: int | None,
    candidate_batch_id: int | None,
    decision: str,
    decision_reason: str,
    pass_rate_drop: float | None = None,
    fail_count_delta: int | None = None,
    error_count_delta: int | None = None,
) -> dict:
    """Persist a gate run record. Returns the new gate run dict."""
    if kind not in _VALID_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(sorted(_VALID_KINDS))}")
    if trigger_source not in _VALID_TRIGGER_SOURCES:
        raise ValueError(
            f"trigger_source must be one of: {', '.join(sorted(_VALID_TRIGGER_SOURCES))}"
        )
    if decision not in _VALID_DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(sorted(_VALID_DECISIONS))}")

    _ensure_schema()
    now = time.time()

    with _lock, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO eval_gate_runs (
                config_id, kind, trigger_source,
                baseline_batch_id, candidate_batch_id,
                decision, decision_reason,
                pass_rate_drop, fail_count_delta, error_count_delta,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                config_id,
                kind,
                trigger_source,
                baseline_batch_id,
                candidate_batch_id,
                decision,
                (decision_reason or "").strip(),
                pass_rate_drop,
                fail_count_delta,
                error_count_delta,
                now,
            ),
        )
        new_id = cursor.lastrowid

    return get_gate_run(new_id)  # type: ignore[return-value]


def get_gate_run(run_id: int) -> dict | None:
    """Return a single gate run by id, or None."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM eval_gate_runs WHERE id = ?", (run_id,)
        ).fetchone()
    return _run_row_to_dict(row) if row else None


def list_gate_runs(
    *,
    config_id: int | None = None,
    kind: str | None = None,
    decision: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """List gate runs. Newest first."""
    _ensure_schema()
    where = ["1=1"]
    params: list[object] = []
    if config_id is not None:
        where.append("config_id = ?")
        params.append(config_id)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if decision:
        where.append("decision = ?")
        params.append(decision)

    params.extend([max(1, min(limit, 200)), max(0, offset)])
    with _lock, _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM eval_gate_runs
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
    return [_run_row_to_dict(row) for row in rows]


def get_most_recent_gate_run_for_config(config_id: int) -> dict | None:
    """Return the most recent gate run for a config, or None."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM eval_gate_runs
            WHERE config_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (config_id,),
        ).fetchone()
    return _run_row_to_dict(row) if row else None


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _config_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "enabled": bool(row["enabled"]),
        "status_filter": row["status_filter"],
        "root_cause": row["root_cause"],
        "expected_topic": row["expected_topic"],
        "limit_cases": row["limit_cases"],
        "run_label_template": row["run_label_template"],
        "baseline_mode": row["baseline_mode"],
        "max_pass_rate_drop": row["max_pass_rate_drop"],
        "max_fail_count_increase": row["max_fail_count_increase"],
        "block_on_error_increase": bool(row["block_on_error_increase"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _run_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "config_id": row["config_id"],
        "kind": row["kind"],
        "trigger_source": row["trigger_source"],
        "baseline_batch_id": row["baseline_batch_id"],
        "candidate_batch_id": row["candidate_batch_id"],
        "decision": row["decision"],
        "decision_reason": row["decision_reason"],
        "pass_rate_drop": row["pass_rate_drop"],
        "fail_count_delta": row["fail_count_delta"],
        "error_count_delta": row["error_count_delta"],
        "created_at": row["created_at"],
    }
