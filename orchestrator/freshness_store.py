"""Freshness snapshot persistence – SQLite backend.

Lưu kết quả health-check theo thời gian để admin theo dõi độ tươi của
knowledge-base sources.  Mỗi record ghi nhận trạng thái (OK / STALE / DEAD /
REDIRECT / ERROR) kèm metadata (http_status, notes, ...) tại thời điểm check.

Design notes:
- Lazy init: DB path được tính từ ``settings.chroma_path`` *tại thời điểm gọi*,
  cho phép test monkey-patch ``CHROMA_PATH`` rồi reload mà không bị stale path.
- Thread-safe qua ``_lock`` + ``check_same_thread=False``.
- ``list_latest`` chỉ trả bản ghi **mới nhất** cho mỗi (url, topic) pair,
  ưu tiên DEAD/ERROR/STALE lên đầu.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from threading import Lock

from config.settings import settings

_lock = Lock()
_initialised_paths: set[str] = set()

_STATUS_NORMALIZATION = {
    "UNKNOWN": "ERROR",
}


def _get_db_path() -> Path:
    """Compute DB path lazily from current settings."""
    return Path(settings.chroma_path).parent / "freshness.sqlite"


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
            CREATE TABLE IF NOT EXISTS freshness_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                topic TEXT,
                status TEXT NOT NULL,
                raw_status TEXT NOT NULL,
                checked_at REAL NOT NULL,
                http_status INTEGER,
                notes TEXT,
                error_message TEXT,
                final_url TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_freshness_checked_at
                ON freshness_snapshots(checked_at DESC);
            CREATE INDEX IF NOT EXISTS idx_freshness_status
                ON freshness_snapshots(status);
            CREATE INDEX IF NOT EXISTS idx_freshness_topic
                ON freshness_snapshots(topic);
            CREATE INDEX IF NOT EXISTS idx_freshness_url_topic_checked
                ON freshness_snapshots(url, topic, checked_at DESC);
            """
        )
    _initialised_paths.add(key)


def save_many(records: list[dict]) -> int:
    """Persist a batch of freshness check results.

    Returns the number of records actually inserted (skips entries without url).
    """
    if not records:
        return 0
    now = time.time()
    rows = [
        (
            (r.get("url") or "").strip(),
            (r.get("topic") or "").strip() or None,
            _STATUS_NORMALIZATION.get(
                (r.get("status") or "").upper(),
                (r.get("status") or "ERROR").upper(),
            ),
            (r.get("status") or "ERROR").upper(),
            float(r.get("checked_at") or now),
            r.get("http_status"),
            (r.get("notes") or "").strip() or None,
            (r.get("error_message") or "").strip() or None,
            (r.get("final_url") or "").strip() or None,
        )
        for r in records
        if (r.get("url") or "").strip()
    ]
    if not rows:
        return 0
    _ensure_schema()
    with _lock, _connect() as conn:
        conn.executemany(
            """
            INSERT INTO freshness_snapshots (
                url, topic, status, raw_status, checked_at, http_status,
                notes, error_message, final_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def list_latest(
    *,
    status: str | None = None,
    topic: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """Return the most recent freshness record per (url, topic).

    Results are ordered: DEAD > ERROR > STALE > REDIRECT > OK, then by
    ``checked_at`` descending within each status group.
    """
    status_filter = (
        _STATUS_NORMALIZATION.get(
            (status or "").upper(), (status or "").upper()
        )
        or None
    )
    where = ["1=1"]
    params: list[object] = []
    if status_filter:
        where.append("s.status = ?")
        params.append(status_filter)
    if topic:
        where.append("COALESCE(s.topic, '') = ?")
        params.append(topic)
    params.extend([max(1, min(limit, 2000)), max(0, offset)])
    where_sql = " AND ".join(where)

    query = f"""
        SELECT
            s.url,
            s.topic,
            s.status,
            s.raw_status,
            s.checked_at,
            s.http_status,
            s.notes,
            s.error_message,
            s.final_url
        FROM freshness_snapshots s
        INNER JOIN (
            SELECT url, COALESCE(topic, '') AS topic_key, MAX(checked_at) AS max_checked_at
            FROM freshness_snapshots
            GROUP BY url, topic_key
        ) latest
            ON latest.url = s.url
            AND latest.topic_key = COALESCE(s.topic, '')
            AND latest.max_checked_at = s.checked_at
        WHERE {where_sql}
        ORDER BY
            CASE s.status
                WHEN 'DEAD' THEN 0
                WHEN 'ERROR' THEN 1
                WHEN 'STALE' THEN 2
                WHEN 'REDIRECT' THEN 3
                WHEN 'OK' THEN 4
                ELSE 5
            END ASC,
            s.checked_at DESC
        LIMIT ? OFFSET ?
    """

    _ensure_schema()
    with _lock, _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        {
            "url": row["url"],
            "topic": row["topic"],
            "status": row["status"],
            "raw_status": row["raw_status"],
            "checked_at": row["checked_at"],
            "http_status": row["http_status"],
            "notes": row["notes"] or "",
            "error_message": row["error_message"] or "",
            "final_url": row["final_url"] or "",
        }
        for row in rows
    ]
