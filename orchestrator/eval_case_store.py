"""Eval Case persistence – SQLite backend.

Lightweight store for evaluation cases created from reviewed feedback and
their run history.  Designed as a regression / quality signal tool, not a
full benchmark framework.

Schema:
    eval_cases(
        id                  INTEGER PK AUTOINCREMENT,
        feedback_id         INTEGER NOT NULL,
        question            TEXT NOT NULL,
        expected_topic      TEXT,
        root_cause          TEXT,
        rewritten_query     TEXT,
        citations_snapshot  TEXT,   -- compact JSON list
        trace_snapshot      TEXT,   -- compact JSON dict
        eval_expectations   TEXT NOT NULL DEFAULT '{}',  -- compact JSON
        status              TEXT NOT NULL DEFAULT 'active',  -- active | archived
        created_at          REAL NOT NULL,
        updated_at          REAL NOT NULL
    )

    eval_runs(
        id              INTEGER PK AUTOINCREMENT,
        eval_case_id    INTEGER NOT NULL,
        pass            INTEGER NOT NULL,   -- bool (0/1)
        checks          TEXT NOT NULL,      -- compact JSON dict
        result_snapshot TEXT NOT NULL,      -- compact JSON dict
        run_at          REAL NOT NULL
    )

    eval_batches(
        id          INTEGER PK AUTOINCREMENT,
        label       TEXT,
        filters     TEXT NOT NULL DEFAULT '{}',  -- compact JSON
        status      TEXT NOT NULL DEFAULT 'completed',
        total_cases INTEGER NOT NULL DEFAULT 0,
        pass_count  INTEGER NOT NULL DEFAULT 0,
        fail_count  INTEGER NOT NULL DEFAULT 0,
        created_at  REAL NOT NULL
    )

    eval_batch_items(
        id              INTEGER PK AUTOINCREMENT,
        batch_id        INTEGER NOT NULL,
        eval_case_id    INTEGER NOT NULL,
        eval_run_id     INTEGER,        -- NULL if execution failed
        pass            INTEGER,        -- NULL if execution failed
        root_cause      TEXT,
        expected_topic  TEXT,
        error           TEXT,           -- populated if execution failed
        created_at      REAL NOT NULL
    )

Design notes:
- Lazy init + thread-safe via _lock, matching feedback_store pattern.
- One active eval case per feedback_id max (enforced at create time).
- Expectation defaults derived heuristically from root_cause.
- Run history kept compact; no heavy analytics.
- Batch records reference per-case eval_run_ids; no large snapshot duplication.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from threading import Lock

from config.settings import settings

_lock = Lock()
_initialised_paths: set[str] = set()

# ─── Expectation derivation ──────────────────────────────────────────────────

_EXPECTATION_DEFAULTS: dict[str, dict] = {
    "retrieval_miss": {
        "should_not_fallback": True,
        "should_have_citations": True,
        "min_retrieval_count": 1,
    },
    "true_coverage_gap": {
        "should_not_fallback": False,
        "should_have_citations": False,
        "min_retrieval_count": None,
    },
    "bad_citation_fit": {
        "should_not_fallback": None,
        "should_have_citations": True,
        "min_retrieval_count": None,
    },
    "insufficient_context": {
        "should_not_fallback": True,
        "should_have_citations": False,
        "min_retrieval_count": 1,
    },
    "hallucination": {
        "should_not_fallback": None,
        "should_have_citations": True,
        "min_retrieval_count": None,
    },
    "wrong_answer_from_context": {
        "should_not_fallback": None,
        "should_have_citations": True,
        "min_retrieval_count": None,
    },
    "stale_source_mix": {
        "should_not_fallback": True,
        "should_have_citations": True,
        "min_retrieval_count": 1,
    },
    "other": {
        "should_not_fallback": None,
        "should_have_citations": None,
        "min_retrieval_count": None,
    },
}

_DEFAULT_EXPECTATIONS: dict = {
    "should_not_fallback": None,
    "should_have_citations": None,
    "min_retrieval_count": None,
    "expected_topic": None,
}

_VALID_STATUSES = frozenset({"active", "archived"})


def derive_expectations(
    root_cause: str | None,
    expected_topic: str | None = None,
) -> dict:
    """Derive heuristic expectations from root_cause + optional expected_topic.

    Returns a dict with keys:
        should_not_fallback (bool | None)
        should_have_citations (bool | None)
        min_retrieval_count (int | None)
        expected_topic (str | None)

    None values mean "skip this check".
    """
    base = dict(_DEFAULT_EXPECTATIONS)
    rc_defaults = _EXPECTATION_DEFAULTS.get(root_cause or "", {})
    base.update(rc_defaults)
    base["expected_topic"] = (expected_topic or "").strip() or None
    return base


# ─── DB plumbing ─────────────────────────────────────────────────────────────

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
    key = str(path)
    if key in _initialised_paths:
        return
    with _lock, _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS eval_cases (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id         INTEGER NOT NULL,
                question            TEXT NOT NULL,
                expected_topic      TEXT,
                root_cause          TEXT,
                rewritten_query     TEXT,
                citations_snapshot  TEXT,
                trace_snapshot      TEXT,
                eval_expectations   TEXT NOT NULL DEFAULT '{}',
                status              TEXT NOT NULL DEFAULT 'active',
                created_at          REAL NOT NULL,
                updated_at          REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ec_feedback_id
                ON eval_cases(feedback_id);
            CREATE INDEX IF NOT EXISTS idx_ec_status
                ON eval_cases(status);
            CREATE INDEX IF NOT EXISTS idx_ec_root_cause
                ON eval_cases(root_cause);
            CREATE INDEX IF NOT EXISTS idx_ec_expected_topic
                ON eval_cases(expected_topic);
            CREATE INDEX IF NOT EXISTS idx_ec_created
                ON eval_cases(created_at DESC);

            CREATE TABLE IF NOT EXISTS eval_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                eval_case_id    INTEGER NOT NULL,
                pass            INTEGER NOT NULL,
                checks          TEXT NOT NULL DEFAULT '{}',
                result_snapshot TEXT NOT NULL DEFAULT '{}',
                run_at          REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_er_eval_case_id
                ON eval_runs(eval_case_id);
            CREATE INDEX IF NOT EXISTS idx_er_run_at
                ON eval_runs(run_at DESC);

            CREATE TABLE IF NOT EXISTS eval_batches (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                label       TEXT,
                filters     TEXT NOT NULL DEFAULT '{}',
                status      TEXT NOT NULL DEFAULT 'completed',
                total_cases INTEGER NOT NULL DEFAULT 0,
                pass_count  INTEGER NOT NULL DEFAULT 0,
                fail_count  INTEGER NOT NULL DEFAULT 0,
                created_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_eb_created
                ON eval_batches(created_at DESC);

            CREATE TABLE IF NOT EXISTS eval_batch_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id        INTEGER NOT NULL,
                eval_case_id    INTEGER NOT NULL,
                eval_run_id     INTEGER,
                pass            INTEGER,
                root_cause      TEXT,
                expected_topic  TEXT,
                error           TEXT,
                created_at      REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ebi_batch_id
                ON eval_batch_items(batch_id);
            """
        )
    _initialised_paths.add(key)


# ─── Eval Case CRUD ───────────────────────────────────────────────────────────

def create_eval_case(
    *,
    feedback_id: int,
    question: str,
    root_cause: str | None = None,
    expected_topic: str | None = None,
    rewritten_query: str | None = None,
    citations_snapshot: list[dict] | None = None,
    trace_snapshot: dict | None = None,
    eval_expectations: dict | None = None,
) -> dict:
    """Create a new eval case from reviewed feedback context.

    Raises ValueError if there is already an active eval case for this feedback_id.
    If eval_expectations is not provided, derives defaults from root_cause.

    Returns the newly created eval case dict.
    """
    if not question.strip():
        raise ValueError("question must not be empty")

    _ensure_schema()
    now = time.time()

    expectations = eval_expectations if eval_expectations is not None else derive_expectations(
        root_cause=root_cause,
        expected_topic=expected_topic,
    )

    cit_json = json.dumps(citations_snapshot, ensure_ascii=False) if citations_snapshot else None
    trace_json = json.dumps(trace_snapshot, ensure_ascii=False) if trace_snapshot else None
    exp_json = json.dumps(expectations, ensure_ascii=False)

    with _lock, _connect() as conn:
        # Enforce one-active-per-feedback constraint
        existing = conn.execute(
            "SELECT id FROM eval_cases WHERE feedback_id = ? AND status = 'active'",
            (feedback_id,),
        ).fetchone()
        if existing:
            raise ValueError(
                f"Feedback #{feedback_id} already has an active eval case (id={existing['id']}). "
                "Archive it before creating a new one."
            )

        cursor = conn.execute(
            """
            INSERT INTO eval_cases (
                feedback_id, question, expected_topic, root_cause,
                rewritten_query, citations_snapshot, trace_snapshot,
                eval_expectations, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                feedback_id,
                question.strip(),
                (expected_topic or "").strip() or None,
                (root_cause or "").strip() or None,
                (rewritten_query or "").strip() or None,
                cit_json,
                trace_json,
                exp_json,
                now,
                now,
            ),
        )
        new_id = cursor.lastrowid

    return get_eval_case(new_id)  # type: ignore[return-value]


def get_eval_case(case_id: int) -> dict | None:
    """Return a single eval case by id, or None if not found."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM eval_cases WHERE id = ?", (case_id,)
        ).fetchone()
    if not row:
        return None
    case = _case_row_to_dict(row)
    # Attach latest run
    case["latest_run"] = get_latest_run(case_id)
    return case


def list_eval_cases(
    *,
    status: str | None = None,
    root_cause: str | None = None,
    expected_topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List eval cases with optional filters. Newest first."""
    _ensure_schema()

    where = ["1=1"]
    params: list[object] = []

    if status:
        where.append("status = ?")
        params.append(status)
    if root_cause:
        where.append("root_cause = ?")
        params.append(root_cause)
    if expected_topic:
        where.append("expected_topic = ?")
        params.append(expected_topic)

    params.extend([max(1, min(limit, 500)), max(0, offset)])
    where_sql = " AND ".join(where)

    query = f"""
        SELECT * FROM eval_cases
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """

    with _lock, _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    cases = [_case_row_to_dict(row) for row in rows]
    # Attach latest run for each case
    for case in cases:
        case["latest_run"] = get_latest_run(case["id"])
    return cases


def update_eval_case_status(case_id: int, *, status: str) -> dict | None:
    """Update status (active | archived) of an eval case."""
    if status not in _VALID_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(_VALID_STATUSES))}")
    _ensure_schema()
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE eval_cases SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, case_id),
        )
    return get_eval_case(case_id)


def count_summary() -> dict:
    """Return summary counts for admin dashboard."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'active'   THEN 1 ELSE 0 END) AS total_active,
                SUM(CASE WHEN status = 'archived' THEN 1 ELSE 0 END) AS total_archived
            FROM eval_cases
            """
        ).fetchone()

        rc_rows = conn.execute(
            """
            SELECT root_cause, COUNT(*) AS cnt
            FROM eval_cases
            WHERE root_cause IS NOT NULL AND root_cause != ''
            GROUP BY root_cause
            ORDER BY cnt DESC
            """
        ).fetchall()
        by_root_cause = {r["root_cause"]: r["cnt"] for r in rc_rows}

        run_row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_runs,
                SUM(pass) AS total_pass,
                SUM(CASE WHEN pass = 0 THEN 1 ELSE 0 END) AS total_fail
            FROM eval_runs
            WHERE eval_case_id IN (
                SELECT id FROM eval_cases WHERE status = 'active'
            )
            AND id IN (
                SELECT MAX(id)
                FROM eval_runs
                GROUP BY eval_case_id
            )
            """
        ).fetchone()

    return {
        "total": row["total"] or 0,
        "total_active": row["total_active"] or 0,
        "total_archived": row["total_archived"] or 0,
        "by_root_cause": by_root_cause,
        "latest_runs": {
            "total": run_row["total_runs"] or 0,
            "pass": run_row["total_pass"] or 0,
            "fail": run_row["total_fail"] or 0,
        },
    }


# ─── Eval Run CRUD ────────────────────────────────────────────────────────────

def create_eval_run(
    *,
    eval_case_id: int,
    passed: bool,
    checks: dict,
    result_snapshot: dict,
) -> dict:
    """Persist an eval run result. Returns the new run dict."""
    _ensure_schema()
    now = time.time()
    checks_json = json.dumps(checks, ensure_ascii=False)
    snapshot_json = json.dumps(result_snapshot, ensure_ascii=False)

    with _lock, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO eval_runs (eval_case_id, pass, checks, result_snapshot, run_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (eval_case_id, 1 if passed else 0, checks_json, snapshot_json, now),
        )
        new_id = cursor.lastrowid

    return get_eval_run(new_id)  # type: ignore[return-value]


def get_eval_run(run_id: int) -> dict | None:
    """Return a single eval run by id, or None if not found."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM eval_runs WHERE id = ?", (run_id,)
        ).fetchone()
    return _run_row_to_dict(row) if row else None


def list_eval_runs(
    eval_case_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """List eval runs for a case. Newest first."""
    _ensure_schema()
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM eval_runs
            WHERE eval_case_id = ?
            ORDER BY run_at DESC
            LIMIT ? OFFSET ?
            """,
            (eval_case_id, max(1, min(limit, 200)), max(0, offset)),
        ).fetchall()
    return [_run_row_to_dict(row) for row in rows]


def get_latest_run(eval_case_id: int) -> dict | None:
    """Return the most recent eval run for a case, or None."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM eval_runs
            WHERE eval_case_id = ?
            ORDER BY run_at DESC
            LIMIT 1
            """,
            (eval_case_id,),
        ).fetchone()
    return _run_row_to_dict(row) if row else None


# ─── Eval Batch CRUD ─────────────────────────────────────────────────────────

def create_eval_batch(
    *,
    label: str | None,
    filters: dict,
    total_cases: int,
    pass_count: int,
    fail_count: int,
) -> dict:
    """Persist a batch run record. Returns the new batch dict (without summary)."""
    _ensure_schema()
    now = time.time()
    filters_json = json.dumps(filters, ensure_ascii=False)
    with _lock, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO eval_batches (label, filters, status, total_cases, pass_count, fail_count, created_at)
            VALUES (?, ?, 'completed', ?, ?, ?, ?)
            """,
            (label or None, filters_json, total_cases, pass_count, fail_count, now),
        )
        new_id = cursor.lastrowid
    return get_eval_batch(new_id)  # type: ignore[return-value]


def get_eval_batch(batch_id: int) -> dict | None:
    """Return a single eval batch with summary breakdown, or None if not found."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM eval_batches WHERE id = ?", (batch_id,)
        ).fetchone()
    if not row:
        return None
    batch = _batch_row_to_dict(row)
    batch["summary"] = _build_batch_summary(batch_id)
    return batch


def list_eval_batches(*, limit: int = 20, offset: int = 0) -> list[dict]:
    """List eval batches. Newest first. Does not include per-batch summary breakdowns."""
    _ensure_schema()
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM eval_batches
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (max(1, min(limit, 200)), max(0, offset)),
        ).fetchall()
    return [_batch_row_to_dict(row) for row in rows]


def create_eval_batch_item(
    *,
    batch_id: int,
    eval_case_id: int,
    eval_run_id: int | None,
    passed: bool | None,
    root_cause: str | None,
    expected_topic: str | None,
    error: str | None = None,
) -> dict:
    """Persist one batch item. Returns the new item dict."""
    _ensure_schema()
    now = time.time()
    pass_int = None if passed is None else (1 if passed else 0)
    with _lock, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO eval_batch_items
                (batch_id, eval_case_id, eval_run_id, pass, root_cause, expected_topic, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                eval_case_id,
                eval_run_id,
                pass_int,
                root_cause or None,
                expected_topic or None,
                error or None,
                now,
            ),
        )
        new_id = cursor.lastrowid
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM eval_batch_items WHERE id = ?", (new_id,)
        ).fetchone()
    return _batch_item_row_to_dict(row)  # type: ignore[arg-type]


def list_eval_batch_items(
    batch_id: int,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """List items for a batch ordered by id (insertion order)."""
    _ensure_schema()
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM eval_batch_items
            WHERE batch_id = ?
            ORDER BY id
            LIMIT ? OFFSET ?
            """,
            (batch_id, max(1, min(limit, 500)), max(0, offset)),
        ).fetchall()
    return [_batch_item_row_to_dict(row) for row in rows]


def _build_batch_summary(batch_id: int) -> dict:
    """Build pass/fail summary + by_root_cause + by_expected_topic breakdowns."""
    items = list_eval_batch_items(batch_id, limit=500)
    total = len(items)
    pass_count = sum(1 for it in items if it["pass"] is True)
    fail_count = sum(1 for it in items if it["pass"] is False)
    error_count = sum(1 for it in items if it["pass"] is None)
    pass_rate = round(pass_count / total, 4) if total else 0.0

    by_root_cause: dict[str, dict] = {}
    by_expected_topic: dict[str, dict] = {}

    for it in items:
        if it["pass"] is None:
            continue  # execution errors are not included in breakdowns
        rc = it.get("root_cause") or "unknown"
        et = it.get("expected_topic") or "unknown"

        if rc not in by_root_cause:
            by_root_cause[rc] = {"pass": 0, "fail": 0}
        if it["pass"]:
            by_root_cause[rc]["pass"] += 1
        else:
            by_root_cause[rc]["fail"] += 1

        if et not in by_expected_topic:
            by_expected_topic[et] = {"pass": 0, "fail": 0}
        if it["pass"]:
            by_expected_topic[et]["pass"] += 1
        else:
            by_expected_topic[et]["fail"] += 1

    return {
        "total_cases": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "pass_rate": pass_rate,
        "by_root_cause": by_root_cause,
        "by_expected_topic": by_expected_topic,
    }


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _case_row_to_dict(row: sqlite3.Row) -> dict:
    cols = row.keys()
    cit_raw = row["citations_snapshot"] if "citations_snapshot" in cols else None
    trace_raw = row["trace_snapshot"] if "trace_snapshot" in cols else None
    exp_raw = row["eval_expectations"] if "eval_expectations" in cols else "{}"

    try:
        citations = json.loads(cit_raw) if cit_raw else []
    except (json.JSONDecodeError, TypeError):
        citations = []
    try:
        trace = json.loads(trace_raw) if trace_raw else {}
    except (json.JSONDecodeError, TypeError):
        trace = {}
    try:
        expectations = json.loads(exp_raw) if exp_raw else {}
    except (json.JSONDecodeError, TypeError):
        expectations = {}

    return {
        "id": row["id"],
        "feedback_id": row["feedback_id"],
        "question": row["question"],
        "expected_topic": row["expected_topic"],
        "root_cause": row["root_cause"],
        "rewritten_query": row["rewritten_query"],
        "citations_snapshot": citations,
        "trace_snapshot": trace,
        "eval_expectations": expectations,
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _run_row_to_dict(row: sqlite3.Row) -> dict:
    try:
        checks = json.loads(row["checks"] or "{}")
    except (json.JSONDecodeError, TypeError):
        checks = {}
    try:
        snapshot = json.loads(row["result_snapshot"] or "{}")
    except (json.JSONDecodeError, TypeError):
        snapshot = {}

    return {
        "id": row["id"],
        "eval_case_id": row["eval_case_id"],
        "pass": bool(row["pass"]),
        "checks": checks,
        "result_snapshot": snapshot,
        "run_at": row["run_at"],
    }


def _batch_row_to_dict(row: sqlite3.Row) -> dict:
    try:
        filters = json.loads(row["filters"] or "{}")
    except (json.JSONDecodeError, TypeError):
        filters = {}
    return {
        "id": row["id"],
        "label": row["label"],
        "filters": filters,
        "status": row["status"],
        "total_cases": row["total_cases"],
        "pass_count": row["pass_count"],
        "fail_count": row["fail_count"],
        "created_at": row["created_at"],
    }


def _batch_item_row_to_dict(row: sqlite3.Row) -> dict:
    pass_val = row["pass"]
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "eval_case_id": row["eval_case_id"],
        "eval_run_id": row["eval_run_id"],
        "pass": None if pass_val is None else bool(pass_val),
        "root_cause": row["root_cause"],
        "expected_topic": row["expected_topic"],
        "error": row["error"],
        "created_at": row["created_at"],
    }
