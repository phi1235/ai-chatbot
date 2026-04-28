"""Feedback Action Queue – SQLite backend.

Lightweight store for action items created from reviewed feedback.
Each action item represents a concrete operational follow-up derived from
feedback review (root_cause, detected_topic, retrieval context).

Schema:
    feedback_actions(
        id               INTEGER PK AUTOINCREMENT,
        feedback_id      INTEGER NOT NULL,
        root_cause       TEXT,
        detected_topic   TEXT,
        suggested_action TEXT NOT NULL,  -- create_coverage_gap | recrawl_source |
                                         -- improve_retrieval | adjust_prompt | ignore
        reason           TEXT,
        query_hint       TEXT,
        status           TEXT NOT NULL DEFAULT 'pending',
                         -- pending | accepted | done | ignored
        owner_note       TEXT,
        created_at       REAL NOT NULL,
        updated_at       REAL NOT NULL
    )

Design notes:
- One active (pending | accepted) action item per feedback_id max.
- Lazy init + thread-safe via _lock.
- Heuristic mapping kept explicit and simple.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from threading import Lock

from config.settings import settings

_lock = Lock()
_initialised_paths: set[str] = set()

# ─── Heuristic mapping: root_cause → suggested_action ───────────────────────

_ROOT_CAUSE_TO_ACTION: dict[str, str] = {
    "retrieval_miss": "create_coverage_gap",
    "true_coverage_gap": "create_coverage_gap",
    "stale_source_mix": "recrawl_source",
    "insufficient_context": "improve_retrieval",
    "bad_citation_fit": "improve_retrieval",
    "wrong_answer_from_context": "adjust_prompt",
    "hallucination": "adjust_prompt",
    "other": "ignore",
}

_VALID_SUGGESTED_ACTIONS = frozenset(_ROOT_CAUSE_TO_ACTION.values())

_VALID_STATUSES = frozenset({"pending", "accepted", "done", "ignored"})

# Statuses that count as "active" (only one per feedback_id allowed)
_ACTIVE_STATUSES = frozenset({"pending", "accepted"})


def suggested_action_for(root_cause: str | None) -> str:
    """Return the heuristic suggested action for a given root_cause.

    Falls back to 'ignore' for unknown/None root causes.
    """
    return _ROOT_CAUSE_TO_ACTION.get(root_cause or "", "ignore")


def valid_suggested_actions() -> frozenset[str]:
    return _VALID_SUGGESTED_ACTIONS


def valid_statuses() -> frozenset[str]:
    return _VALID_STATUSES


# ─── DB plumbing ─────────────────────────────────────────────────────────────

def _get_db_path() -> Path:
    return Path(settings.chroma_path).parent / "feedback_actions.sqlite"


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
            CREATE TABLE IF NOT EXISTS feedback_actions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id      INTEGER NOT NULL,
                root_cause       TEXT,
                detected_topic   TEXT,
                suggested_action TEXT NOT NULL,
                reason           TEXT,
                query_hint       TEXT,
                status           TEXT NOT NULL DEFAULT 'pending',
                owner_note       TEXT,
                created_at       REAL NOT NULL,
                updated_at       REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fa_feedback_id
                ON feedback_actions(feedback_id);
            CREATE INDEX IF NOT EXISTS idx_fa_status
                ON feedback_actions(status);
            CREATE INDEX IF NOT EXISTS idx_fa_suggested_action
                ON feedback_actions(suggested_action);
            CREATE INDEX IF NOT EXISTS idx_fa_root_cause
                ON feedback_actions(root_cause);
            CREATE INDEX IF NOT EXISTS idx_fa_created
                ON feedback_actions(created_at DESC);
            """
        )
    _initialised_paths.add(key)


# ─── Public API ──────────────────────────────────────────────────────────────

def create_action_item(
    *,
    feedback_id: int,
    root_cause: str | None = None,
    detected_topic: str | None = None,
    query_hint: str | None = None,
    reason: str | None = None,
) -> dict:
    """Create an action item from a reviewed feedback record.

    Derives suggested_action from root_cause via heuristic mapping.
    Raises ValueError if there is already an active action item for this feedback_id.

    Returns the newly created action item dict.
    """
    _ensure_schema()
    action = suggested_action_for(root_cause)

    # Build a default reason if none provided
    if not reason:
        reason = _default_reason(root_cause, action)

    now = time.time()

    with _lock, _connect() as conn:
        # Enforce one-active-per-feedback constraint
        existing = conn.execute(
            "SELECT id FROM feedback_actions WHERE feedback_id = ? AND status IN ('pending', 'accepted')",
            (feedback_id,),
        ).fetchone()
        if existing:
            raise ValueError(
                f"Feedback #{feedback_id} already has an active action item (id={existing['id']}). "
                "Resolve or ignore it before creating a new one."
            )

        cursor = conn.execute(
            """
            INSERT INTO feedback_actions (
                feedback_id, root_cause, detected_topic,
                suggested_action, reason, query_hint,
                status, owner_note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?)
            """,
            (
                feedback_id,
                (root_cause or "").strip() or None,
                (detected_topic or "").strip() or None,
                action,
                (reason or "").strip() or None,
                (query_hint or "").strip() or None,
                now,
                now,
            ),
        )
        new_id = cursor.lastrowid

    return get_action_item(new_id)  # type: ignore[return-value]


def get_action_item(action_id: int) -> dict | None:
    """Return a single action item by id, or None if not found."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM feedback_actions WHERE id = ?", (action_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_action_items(
    *,
    status: str | None = None,
    suggested_action: str | None = None,
    root_cause: str | None = None,
    detected_topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List action items with optional filters. Newest first, pending first."""
    _ensure_schema()

    where = ["1=1"]
    params: list[object] = []

    if status:
        where.append("status = ?")
        params.append(status)
    if suggested_action:
        where.append("suggested_action = ?")
        params.append(suggested_action)
    if root_cause:
        where.append("root_cause = ?")
        params.append(root_cause)
    if detected_topic:
        where.append("detected_topic = ?")
        params.append(detected_topic)

    params.extend([max(1, min(limit, 500)), max(0, offset)])
    where_sql = " AND ".join(where)

    query = f"""
        SELECT * FROM feedback_actions
        WHERE {where_sql}
        ORDER BY
            CASE status WHEN 'pending' THEN 0 WHEN 'accepted' THEN 1 ELSE 2 END ASC,
            created_at DESC
        LIMIT ? OFFSET ?
    """

    with _lock, _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    return [_row_to_dict(row) for row in rows]


def update_action_status(
    action_id: int,
    *,
    status: str,
    owner_note: str | None = None,
) -> dict | None:
    """Update the status (and optional owner note) of an action item.

    Returns the updated record, or None if not found.
    Raises ValueError for invalid status values.
    """
    if status not in _VALID_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(_VALID_STATUSES))}")

    _ensure_schema()
    now = time.time()

    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE feedback_actions
            SET status = ?,
                owner_note = COALESCE(?, owner_note),
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                (owner_note or "").strip() or None,
                now,
                action_id,
            ),
        )

    return get_action_item(action_id)


def count_summary() -> dict:
    """Return summary counts for the action queue dashboard."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'pending'  THEN 1 ELSE 0 END) AS total_pending,
                SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) AS total_accepted,
                SUM(CASE WHEN status = 'done'     THEN 1 ELSE 0 END) AS total_done,
                SUM(CASE WHEN status = 'ignored'  THEN 1 ELSE 0 END) AS total_ignored
            FROM feedback_actions
            """
        ).fetchone()

        action_rows = conn.execute(
            """
            SELECT suggested_action, COUNT(*) AS cnt
            FROM feedback_actions
            GROUP BY suggested_action
            ORDER BY cnt DESC
            """
        ).fetchall()
        by_action = {r["suggested_action"]: r["cnt"] for r in action_rows}

    return {
        "total": row["total"] or 0,
        "total_pending": row["total_pending"] or 0,
        "total_accepted": row["total_accepted"] or 0,
        "total_done": row["total_done"] or 0,
        "total_ignored": row["total_ignored"] or 0,
        "by_action": by_action,
    }


# ─── Internal ────────────────────────────────────────────────────────────────

def _default_reason(root_cause: str | None, suggested_action: str) -> str:
    templates: dict[str, str] = {
        "create_coverage_gap": (
            f"Root cause '{root_cause}' indicates missing knowledge. "
            "Consider adding or enriching a source for this topic."
        ),
        "recrawl_source": (
            f"Root cause '{root_cause}' suggests stale or outdated sources. "
            "Recrawling the relevant source may improve answer quality."
        ),
        "improve_retrieval": (
            f"Root cause '{root_cause}' points to a retrieval quality issue. "
            "Review retrieval config, reranking, or chunk strategy for this topic."
        ),
        "adjust_prompt": (
            f"Root cause '{root_cause}' indicates a generation/reasoning issue. "
            "Consider adjusting the system prompt or answer constraints."
        ),
        "ignore": (
            f"Root cause '{root_cause or 'unknown'}' does not map to a clear action. "
            "Marking as ignore unless further investigation reveals a pattern."
        ),
    }
    return templates.get(suggested_action, f"Root cause: {root_cause or 'unknown'}.")


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "feedback_id": row["feedback_id"],
        "root_cause": row["root_cause"],
        "detected_topic": row["detected_topic"],
        "suggested_action": row["suggested_action"],
        "reason": row["reason"] or "",
        "query_hint": row["query_hint"],
        "status": row["status"],
        "owner_note": row["owner_note"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
