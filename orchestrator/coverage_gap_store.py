"""Coverage Gap persistence – SQLite backend.

Lưu các coverage gap candidates được phát hiện từ traffic chat.
Admin dùng để review, triage, và quyết định hành động (add source, recrawl, ...).

Schema:
    coverage_gaps(
        id                INTEGER PK AUTOINCREMENT,
        session_id        TEXT,
        message_id        TEXT,
        question          TEXT NOT NULL,
        rewritten_query   TEXT,
        detected_topic    TEXT,
        answer_excerpt    TEXT,
        retrieval_count   INTEGER NOT NULL DEFAULT 0,
        citations_snapshot TEXT,   -- JSON rút gọn
        gap_signals       TEXT,    -- JSON list các lý do bị gắn cờ
        status            TEXT NOT NULL DEFAULT 'new',
                          -- new | reviewed | actioned | ignored
        resolution        TEXT,
                          -- add_source | recrawl | out_of_scope | duplicate
                          -- | retrieval_tuning | prompt_tuning | null
        review_note       TEXT,
        feedback_type     TEXT,    -- 'up' | 'down' nếu request bị vote
        created_at        REAL NOT NULL,
        reviewed_at       REAL,
        action_payload    TEXT,    -- JSON: chi tiết action đã thực hiện
        actioned_at       REAL     -- timestamp khi action hoàn thành
    )

Design notes:
- Lazy init tương tự feedback_store / freshness_store.
- Thread-safe qua _lock + check_same_thread=False.
- citations_snapshot và gap_signals lưu dạng JSON TEXT.
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

_VALID_STATUSES = {"new", "reviewed", "actioned", "ignored"}
_VALID_RESOLUTIONS = {
    "add_source",
    "recrawl",
    "out_of_scope",
    "duplicate",
    "retrieval_tuning",
    "prompt_tuning",
}


def _get_db_path() -> Path:
    """Compute DB path lazily from current settings."""
    return Path(settings.chroma_path).parent / "coverage_gap.sqlite"


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
            CREATE TABLE IF NOT EXISTS coverage_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                message_id TEXT,
                question TEXT NOT NULL,
                rewritten_query TEXT,
                detected_topic TEXT,
                answer_excerpt TEXT,
                retrieval_count INTEGER NOT NULL DEFAULT 0,
                citations_snapshot TEXT,
                gap_signals TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                resolution TEXT,
                review_note TEXT,
                feedback_type TEXT,
                created_at REAL NOT NULL,
                reviewed_at REAL,
                action_payload TEXT,
                actioned_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_coverage_gap_created
                ON coverage_gaps(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_coverage_gap_status
                ON coverage_gaps(status);
            CREATE INDEX IF NOT EXISTS idx_coverage_gap_topic
                ON coverage_gaps(detected_topic);
            CREATE INDEX IF NOT EXISTS idx_coverage_gap_resolution
                ON coverage_gaps(resolution);
            """
        )
        # Migrate existing tables: add new columns if missing
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(coverage_gaps)").fetchall()
        }
        if "action_payload" not in existing_cols:
            conn.execute("ALTER TABLE coverage_gaps ADD COLUMN action_payload TEXT")
        if "actioned_at" not in existing_cols:
            conn.execute("ALTER TABLE coverage_gaps ADD COLUMN actioned_at REAL")
    _initialised_paths.add(key)


def add_gap(
    *,
    question: str,
    answer_excerpt: str = "",
    retrieval_count: int = 0,
    gap_signals: list[str] | None = None,
    citations_snapshot: list[dict] | None = None,
    session_id: str | None = None,
    message_id: str | None = None,
    rewritten_query: str | None = None,
    detected_topic: str | None = None,
    feedback_type: str | None = None,
) -> int:
    """Persist a coverage gap candidate. Returns the new gap id."""
    if not (question or "").strip():
        raise ValueError("question must not be empty")

    _ensure_schema()
    now = time.time()
    with _lock, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO coverage_gaps (
                session_id, message_id, question, rewritten_query,
                detected_topic, answer_excerpt, retrieval_count,
                citations_snapshot, gap_signals, feedback_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (session_id or "").strip() or None,
                (message_id or "").strip() or None,
                question.strip(),
                (rewritten_query or "").strip() or None,
                (detected_topic or "").strip() or None,
                (answer_excerpt or "").strip()[:500] or None,
                max(0, retrieval_count),
                json.dumps(citations_snapshot or [], ensure_ascii=False),
                json.dumps(gap_signals or [], ensure_ascii=False),
                (feedback_type or "").strip() or None,
                now,
            ),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def get_gap(gap_id: int) -> dict | None:
    """Get a single coverage gap by id."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM coverage_gaps WHERE id = ?", (gap_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_gaps(
    *,
    status: str | None = None,
    detected_topic: str | None = None,
    resolution: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List coverage gaps with optional filters. Newest first, 'new' prioritised."""
    _ensure_schema()

    where = ["1=1"]
    params: list[object] = []

    if status:
        where.append("status = ?")
        params.append(status)
    if detected_topic:
        where.append("detected_topic = ?")
        params.append(detected_topic)
    if resolution:
        where.append("resolution = ?")
        params.append(resolution)

    params.extend([max(1, min(limit, 500)), max(0, offset)])
    where_sql = " AND ".join(where)

    query = f"""
        SELECT * FROM coverage_gaps
        WHERE {where_sql}
        ORDER BY
            CASE status WHEN 'new' THEN 0 ELSE 1 END ASC,
            created_at DESC
        LIMIT ? OFFSET ?
    """

    with _lock, _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    return [_row_to_dict(row) for row in rows]


def review_gap(
    gap_id: int,
    *,
    status: str = "reviewed",
    resolution: str | None = None,
    review_note: str | None = None,
) -> dict | None:
    """Update a gap's review status/resolution. Returns updated record."""
    if status not in _VALID_STATUSES:
        raise ValueError(f"status must be one of {_VALID_STATUSES}")
    if resolution and resolution not in _VALID_RESOLUTIONS:
        raise ValueError(f"resolution must be one of {_VALID_RESOLUTIONS}")

    _ensure_schema()
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE coverage_gaps
            SET status = ?,
                resolution = ?,
                review_note = ?,
                reviewed_at = ?
            WHERE id = ?
            """,
            (
                status,
                (resolution or "").strip() or None,
                (review_note or "").strip() or None,
                now,
                gap_id,
            ),
        )
    return get_gap(gap_id)


_ACTION_RESOLUTIONS = {"add_source", "recrawl"}


def action_gap(
    gap_id: int,
    *,
    resolution: str,
    action_payload: dict | None = None,
    review_note: str | None = None,
) -> dict | None:
    """Mark a gap as actioned with a concrete action payload.

    Unlike review_gap, this is specifically for actions that have been
    *executed* (e.g. source added, recrawl triggered), not just labelled.
    """
    if resolution not in _ACTION_RESOLUTIONS:
        raise ValueError(f"resolution must be one of {_ACTION_RESOLUTIONS}")

    _ensure_schema()
    now = time.time()
    payload_json = json.dumps(action_payload or {}, ensure_ascii=False)
    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE coverage_gaps
            SET status = 'actioned',
                resolution = ?,
                review_note = ?,
                action_payload = ?,
                reviewed_at = ?,
                actioned_at = ?
            WHERE id = ?
            """,
            (
                resolution,
                (review_note or "").strip() or None,
                payload_json,
                now,
                now,
                gap_id,
            ),
        )
    return get_gap(gap_id)


def count_summary() -> dict:
    """Return summary counts for admin dashboard."""
    _ensure_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END) AS total_new,
                SUM(CASE WHEN status = 'reviewed' THEN 1 ELSE 0 END) AS total_reviewed,
                SUM(CASE WHEN status = 'actioned' THEN 1 ELSE 0 END) AS total_actioned,
                SUM(CASE WHEN status = 'ignored' THEN 1 ELSE 0 END) AS total_ignored
            FROM coverage_gaps
            """
        ).fetchone()

        # Breakdown by topic (top 10)
        topic_rows = conn.execute(
            """
            SELECT detected_topic, COUNT(*) AS cnt
            FROM coverage_gaps
            WHERE detected_topic IS NOT NULL AND detected_topic != ''
            GROUP BY detected_topic
            ORDER BY cnt DESC
            LIMIT 10
            """
        ).fetchall()

        # Breakdown by resolution
        resolution_rows = conn.execute(
            """
            SELECT resolution, COUNT(*) AS cnt
            FROM coverage_gaps
            WHERE resolution IS NOT NULL AND resolution != ''
            GROUP BY resolution
            ORDER BY cnt DESC
            """
        ).fetchall()

    return {
        "total": row["total"] or 0,
        "total_new": row["total_new"] or 0,
        "total_reviewed": row["total_reviewed"] or 0,
        "total_actioned": row["total_actioned"] or 0,
        "total_ignored": row["total_ignored"] or 0,
        "by_topic": {r["detected_topic"]: r["cnt"] for r in topic_rows},
        "by_resolution": {r["resolution"]: r["cnt"] for r in resolution_rows},
    }


def _row_to_dict(row: sqlite3.Row) -> dict:
    signals_raw = row["gap_signals"] or "[]"
    citations_raw = row["citations_snapshot"] or "[]"
    try:
        gap_signals = json.loads(signals_raw)
    except (json.JSONDecodeError, TypeError):
        gap_signals = []
    try:
        citations_snapshot = json.loads(citations_raw)
    except (json.JSONDecodeError, TypeError):
        citations_snapshot = []

    action_payload_raw = row["action_payload"] or "{}"
    try:
        action_payload = json.loads(action_payload_raw)
    except (json.JSONDecodeError, TypeError):
        action_payload = {}

    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "message_id": row["message_id"],
        "question": row["question"],
        "rewritten_query": row["rewritten_query"],
        "detected_topic": row["detected_topic"],
        "answer_excerpt": row["answer_excerpt"] or "",
        "retrieval_count": row["retrieval_count"],
        "citations_snapshot": citations_snapshot,
        "gap_signals": gap_signals,
        "status": row["status"],
        "resolution": row["resolution"],
        "review_note": row["review_note"] or "",
        "feedback_type": row["feedback_type"],
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
        "action_payload": action_payload,
        "actioned_at": row["actioned_at"],
    }
