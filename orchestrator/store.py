"""SQLite persistence cho conversations.

Schema:
    sessions(id PK, title, created_at, updated_at)
    messages(id PK, session_id FK, role, content, citations_json, show_citations,
             trace_json, is_error, created_at)

Mỗi cuộc trò chuyện = 1 session_id (UUID).
Memory module dùng store này để load/save persistent qua restart.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from threading import Lock
from typing import Any

from config.settings import settings

_DB_PATH = Path(settings.chroma_path).parent / "conversations.sqlite"
_lock = Lock()


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_schema() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'Cuộc trò chuyện mới',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                citations_json TEXT,
                show_citations INTEGER NOT NULL DEFAULT 0,
                trace_json TEXT,
                is_error INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
            CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
            """
        )


_init_schema()


def _now() -> float:
    return time.time()


def ensure_session(session_id: str, title: str | None = None) -> None:
    """Tạo session nếu chưa có. Idempotent."""
    now = _now()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, title, created_at, updated_at)
            VALUES (?, COALESCE(?, 'Cuộc trò chuyện mới'), ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (session_id, title, now, now),
        )


def update_title(session_id: str, title: str) -> None:
    title = (title or "").strip()[:120] or "Cuộc trò chuyện mới"
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), session_id),
        )


def touch_session(session_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )


def add_message(
    session_id: str,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
    show_citations: bool = False,
    trace: dict[str, Any] | None = None,
    is_error: bool = False,
) -> None:
    ensure_session(session_id)
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO messages (
                session_id, role, content, citations_json,
                show_citations, trace_json, is_error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                role,
                content,
                json.dumps(citations or [], ensure_ascii=False) if citations else None,
                1 if show_citations else 0,
                json.dumps(trace or {}, ensure_ascii=False) if trace else None,
                1 if is_error else 0,
                _now(),
            ),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )


def get_messages(session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Trả về list message theo thứ tự thời gian. limit=None để lấy tất cả."""
    with _lock, _connect() as conn:
        if limit:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT * FROM messages WHERE session_id = ?
                    ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "citations": json.loads(row["citations_json"]) if row["citations_json"] else [],
                "show_citations": bool(row["show_citations"]),
                "trace": json.loads(row["trace_json"]) if row["trace_json"] else {},
                "is_error": bool(row["is_error"]),
                "created_at": row["created_at"],
            }
        )
    return out


def get_recent_turns(session_id: str, max_turns: int = 8) -> list[dict[str, str]]:
    """View nhẹ cho LLM: chỉ role + content, N turn gần nhất."""
    msgs = get_messages(session_id, limit=max_turns)
    return [{"role": m["role"], "content": m["content"]} for m in msgs if m["role"] in ("user", "assistant")]


def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.created_at, s.updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count
            FROM sessions s
            WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "message_count": r["message_count"],
        }
        for r in rows
    ]


def delete_session(session_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def session_message_count(session_id: str) -> int:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


def auto_title_from_first_message(content: str) -> str:
    """Sinh title đơn giản từ content user đầu tiên."""
    text = " ".join(content.split())
    if len(text) > 60:
        text = text[:60].rsplit(" ", 1)[0] + "…"
    return text or "Cuộc trò chuyện mới"
