"""Answer Feedback persistence – SQLite backend.

Lưu feedback (up/down) cho mỗi câu trả lời chatbot + review workflow cho admin.

Schema:
    feedbacks(
        id                  INTEGER PK AUTOINCREMENT,
        session_id          TEXT,
        message_id          TEXT,
        question            TEXT NOT NULL,
        answer              TEXT NOT NULL,
        feedback_type       TEXT NOT NULL,  -- 'up' | 'down'
        note                TEXT,
        created_at          REAL NOT NULL,
        reviewed            INTEGER NOT NULL DEFAULT 0,
        review_note         TEXT,
        review_status       TEXT NOT NULL DEFAULT 'pending',  -- pending | reviewed | actioned
        reviewed_at         REAL,
        -- retrieval debug snapshot (MVP)
        rewritten_query     TEXT,
        detected_topic      TEXT,
        retrieval_count     INTEGER,
        citations_snapshot  TEXT,   -- compact JSON
        trace_snapshot      TEXT,   -- compact JSON
        root_cause          TEXT    -- admin classification
    )

Design notes:
- Lazy init tương tự freshness_store.
- Thread-safe qua _lock + check_same_thread=False.
- list_feedbacks hỗ trợ filter type/reviewed/session_id/root_cause + pagination.
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


_VALID_ROOT_CAUSES = frozenset({
    "retrieval_miss",
    "insufficient_context",
    "bad_citation_fit",
    "wrong_answer_from_context",
    "hallucination",
    "stale_source_mix",
    "true_coverage_gap",
    "other",
})


def valid_root_causes() -> frozenset[str]:
    """Return the set of valid root cause labels (public API)."""
    return _VALID_ROOT_CAUSES


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
                reviewed_at REAL,
                rewritten_query TEXT,
                detected_topic TEXT,
                retrieval_count INTEGER,
                citations_snapshot TEXT,
                trace_snapshot TEXT,
                root_cause TEXT
            );
            """
        )
        # Backward-compatible migration: add columns if missing before creating
        # indexes that depend on those columns. Older DBs may predate the debug /
        # review-classification fields introduced after the initial rollout.
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(feedbacks)").fetchall()
        }
        migrate_cols = [
            ("rewritten_query", "TEXT"),
            ("detected_topic", "TEXT"),
            ("retrieval_count", "INTEGER"),
            ("citations_snapshot", "TEXT"),
            ("trace_snapshot", "TEXT"),
            ("root_cause", "TEXT"),
        ]
        for col, col_type in migrate_cols:
            if col not in existing:
                conn.execute(f"ALTER TABLE feedbacks ADD COLUMN {col} {col_type}")

        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_feedback_created
                ON feedbacks(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feedback_type
                ON feedbacks(feedback_type);
            CREATE INDEX IF NOT EXISTS idx_feedback_review_status
                ON feedbacks(review_status);
            CREATE INDEX IF NOT EXISTS idx_feedback_session
                ON feedbacks(session_id);
            CREATE INDEX IF NOT EXISTS idx_feedback_root_cause
                ON feedbacks(root_cause);
            CREATE INDEX IF NOT EXISTS idx_feedback_detected_topic
                ON feedbacks(detected_topic);
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
    rewritten_query: str | None = None,
    detected_topic: str | None = None,
    retrieval_count: int | None = None,
    citations_snapshot: list[dict] | None = None,
    trace_snapshot: dict | None = None,
) -> int:
    """Persist a feedback entry. Returns the new feedback id."""
    if feedback_type not in ("up", "down"):
        raise ValueError("feedback_type must be 'up' or 'down'")
    if not question.strip() or not answer.strip():
        raise ValueError("question and answer must not be empty")

    _ensure_schema()
    now = time.time()
    cit_json = json.dumps(citations_snapshot, ensure_ascii=False) if citations_snapshot else None
    trace_json = json.dumps(trace_snapshot, ensure_ascii=False) if trace_snapshot else None
    with _lock, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO feedbacks (
                session_id, message_id, question, answer,
                feedback_type, note, created_at,
                rewritten_query, detected_topic, retrieval_count,
                citations_snapshot, trace_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (session_id or "").strip() or None,
                (message_id or "").strip() or None,
                question.strip(),
                answer.strip(),
                feedback_type,
                (note or "").strip() or None,
                now,
                (rewritten_query or "").strip() or None,
                (detected_topic or "").strip() or None,
                retrieval_count,
                cit_json,
                trace_json,
            ),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def list_feedbacks(
    *,
    feedback_type: str | None = None,
    reviewed: bool | None = None,
    session_id: str | None = None,
    review_status: str | None = None,
    root_cause: str | None = None,
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
    if root_cause:
        where.append("root_cause = ?")
        params.append(root_cause)

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
    root_cause: str | None = None,
) -> dict | None:
    """Mark a feedback as reviewed with optional note and root cause. Returns updated record."""
    if review_status not in ("pending", "reviewed", "actioned"):
        raise ValueError("review_status must be 'pending', 'reviewed', or 'actioned'")
    if root_cause and root_cause not in _VALID_ROOT_CAUSES:
        raise ValueError(f"root_cause must be one of: {', '.join(sorted(_VALID_ROOT_CAUSES))}")

    _ensure_schema()
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE feedbacks
            SET reviewed = 1,
                review_note = ?,
                review_status = ?,
                reviewed_at = ?,
                root_cause = COALESCE(?, root_cause)
            WHERE id = ?
            """,
            (
                (review_note or "").strip() or None,
                review_status,
                now,
                (root_cause or "").strip() or None,
                feedback_id,
            ),
        )
    return get_feedback(feedback_id)


def count_summary() -> dict:
    """Return summary counts for admin dashboard including root-cause breakdown and top topics."""
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

        # Root-cause breakdown (only for down feedbacks that have a root_cause)
        rc_rows = conn.execute(
            """
            SELECT root_cause, COUNT(*) AS cnt
            FROM feedbacks
            WHERE feedback_type = 'down'
              AND root_cause IS NOT NULL AND root_cause != ''
            GROUP BY root_cause
            ORDER BY cnt DESC
            """
        ).fetchall()
        by_root_cause = {r["root_cause"]: r["cnt"] for r in rc_rows}

        # Top detected topics with downvotes
        topic_rows = conn.execute(
            """
            SELECT detected_topic, COUNT(*) AS cnt
            FROM feedbacks
            WHERE feedback_type = 'down'
              AND detected_topic IS NOT NULL AND detected_topic != ''
            GROUP BY detected_topic
            ORDER BY cnt DESC
            LIMIT 10
            """
        ).fetchall()
        top_down_topics = {r["detected_topic"]: r["cnt"] for r in topic_rows}

    return {
        "total": row["total"] or 0,
        "total_down": row["total_down"] or 0,
        "total_up": row["total_up"] or 0,
        "down_pending": row["down_pending"] or 0,
        "reviewed": row["reviewed"] or 0,
        "by_root_cause": by_root_cause,
        "top_down_topics": top_down_topics,
    }


def _row_to_dict(row: sqlite3.Row) -> dict:
    cols = row.keys()
    cit_raw = row["citations_snapshot"] if "citations_snapshot" in cols else None
    trace_raw = row["trace_snapshot"] if "trace_snapshot" in cols else None
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
        "rewritten_query": row["rewritten_query"] if "rewritten_query" in cols else None,
        "detected_topic": row["detected_topic"] if "detected_topic" in cols else None,
        "retrieval_count": row["retrieval_count"] if "retrieval_count" in cols else None,
        "citations_snapshot": json.loads(cit_raw) if cit_raw else [],
        "trace_snapshot": json.loads(trace_raw) if trace_raw else {},
        "root_cause": row["root_cause"] if "root_cause" in cols else None,
    }
