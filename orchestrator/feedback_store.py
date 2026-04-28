"""Answer Feedback persistence – SQLite backend.

Lưu feedback (up/down) cho mỗi câu trả lời chatbot + review workflow cho admin.

Schema:
    feedbacks(
        id              INTEGER PK AUTOINCREMENT,
        session_id      TEXT,
        message_id      TEXT,
        question        TEXT NOT NULL,
        answer          TEXT NOT NULL,
        feedback_type   TEXT NOT NULL,  -- 'up' | 'down'
        note            TEXT,
        created_at      REAL NOT NULL,
        reviewed        INTEGER NOT NULL DEFAULT 0,
        review_note     TEXT,
        review_status   TEXT NOT NULL DEFAULT 'pending',  -- pending | reviewed | actioned
        reviewed_at     REAL
    )

Design notes:
- Lazy init tương tự freshness_store.
- Thread-safe qua _lock + check_same_thread=False.
- list_feedbacks hỗ trợ filter type/reviewed/session_id + pagination.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from threading import Lock

from config.settings import settings

_lock = Lock()
_initialised_paths: set[str] = set()


def _get_db_path() -> Path:
    """Compute DB path lazily from current settings."""
    return Path(settings.chroma_path).parent / "feedback.sqlite"


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
            CREATE TABLE IF NOT EXISTS feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                message_id TEXT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                note TEXT,
                created_at REAL NOT NULL,
                reviewed INTEGER NOT NULL DEFAULT 0,
                review_note TEXT,
                review_status TEXT NOT NULL DEFAULT 'pending',
                reviewed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_created
                ON feedbacks(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feedback_type
                ON feedbacks(feedback_type);
            CREATE INDEX IF NOT EXISTS idx_feedback_review_status
                ON feedbacks(review_status);
            CREATE INDEX IF NOT EXISTS idx_feedback_session
                ON feedbacks(session_id);
            """
        )
    _initialised_paths.add(key)


def add_feedback(
    *,
    question: str,
    answer: str,
    feedback_type: str,
    session_id: str | None = None,
    message_id: str | None = None,
    note: str | None = None,
) -> int:
    """Persist a feedback entry. Returns the new feedback id."""
    if feedback_type not in ("up", "down"):
        raise ValueError("feedback_type must be 'up' or 'down'")
    if not question.strip() or not answer.strip():
        raise ValueError("question and answer must not be empty")

    _ensure_schema()
    now = time.time()
    with _lock, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO feedbacks (
                session_id, message_id, question, answer,
                feedback_type, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (session_id or "").strip() or None,
                (message_id or "").strip() or None,
                question.strip(),
                answer.strip(),
                feedback_type,
                (note or "").strip() or None,
                now,
            ),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def list_feedbacks(
    *,
    feedback_type: str | None = None,
    reviewed: bool | None = None,
    session_id: str | None = None,
    review_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List feedbacks with optional filters. Ordered by created_at DESC (newest first),
    with 'down' prioritised over 'up' within same timestamp."""
    _ensure_schema()

    where = ["1=1"]
    params: list[object] = []

    if feedback_type:
        where.append("feedback_type = ?")
        params.append(feedback_type)
    if reviewed is not None:
        where.append("reviewed = ?")
        params.append(1 if reviewed else 0)
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    if review_status:
        where.append("review_status = ?")
        params.append(review_status)

    params.extend([max(1, min(limit, 500)), max(0, offset)])
    where_sql = " AND ".join(where)

    query = f"""
        SELECT * FROM feedbacks
        WHERE {where_sql}
        ORDER BY
            CASE feedback_type WHEN 'down' THEN 0 ELSE 1 END ASC,
            created_at DESC
        LIMIT ? OFFSET ?
    """

    with _lock, _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    return [_row_to_dict(row) for row in rows]


def get_feedback(feedback_id: int) -> dict | None:
    """Get a single feedback by id."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM feedbacks WHERE id = ?", (feedback_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_feedback(feedback_id: int) -> bool:
    """Delete a feedback by id. Returns True when a row was deleted."""
    _ensure_schema()
    with _lock, _connect() as conn:
        cursor = conn.execute("DELETE FROM feedbacks WHERE id = ?", (feedback_id,))
        return cursor.rowcount > 0


def mark_reviewed(
    feedback_id: int,
    *,
    review_note: str | None = None,
    review_status: str = "reviewed",
) -> dict | None:
    """Mark a feedback as reviewed with optional note. Returns updated record."""
    if review_status not in ("pending", "reviewed", "actioned"):
        raise ValueError("review_status must be 'pending', 'reviewed', or 'actioned'")

    _ensure_schema()
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE feedbacks
            SET reviewed = 1,
                review_note = ?,
                review_status = ?,
                reviewed_at = ?
            WHERE id = ?
            """,
            (
                (review_note or "").strip() or None,
                review_status,
                now,
                feedback_id,
            ),
        )
    return get_feedback(feedback_id)


def count_summary() -> dict:
    """Return summary counts for admin dashboard."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN feedback_type = 'down' THEN 1 ELSE 0 END) AS total_down,
                SUM(CASE WHEN feedback_type = 'up' THEN 1 ELSE 0 END) AS total_up,
                SUM(CASE WHEN feedback_type = 'down' AND review_status = 'pending' THEN 1 ELSE 0 END) AS down_pending,
                SUM(CASE WHEN reviewed = 1 THEN 1 ELSE 0 END) AS reviewed
            FROM feedbacks
            """
        ).fetchone()
    return {
        "total": row["total"] or 0,
        "total_down": row["total_down"] or 0,
        "total_up": row["total_up"] or 0,
        "down_pending": row["down_pending"] or 0,
        "reviewed": row["reviewed"] or 0,
    }


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "message_id": row["message_id"],
        "question": row["question"],
        "answer": row["answer"],
        "feedback_type": row["feedback_type"],
        "note": row["note"] or "",
        "created_at": row["created_at"],
        "reviewed": bool(row["reviewed"]),
        "review_note": row["review_note"] or "",
        "review_status": row["review_status"],
        "reviewed_at": row["reviewed_at"],
    }
