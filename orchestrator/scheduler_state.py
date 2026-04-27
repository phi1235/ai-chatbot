"""Scheduler state persistence – SQLite backend for scheduled freshness checks.

Lưu trạng thái scheduler (enabled, interval, last_run, next_run) và kết quả lần chạy gần nhất
để admin theo dõi và không mất dữ liệu khi restart.

Design:
- Lazy init: DB path được tính từ settings.chroma_path tại runtime
- Thread-safe qua _lock
- Simple table: một row duy nhất (id=1) chứa state scheduler
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock

from config.settings import settings

_lock = Lock()
_initialised: bool = False


@dataclass
class SchedulerState:
    enabled: bool = False
    interval_seconds: int = 3600
    last_run_time: float | None = None
    next_run_time: float | None = None
    last_summary: dict | None = None
    alert_state: str = "OK"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SchedulerState:
        return cls(
            enabled=data.get("enabled", False),
            interval_seconds=data.get("interval_seconds", 3600),
            last_run_time=data.get("last_run_time"),
            next_run_time=data.get("next_run_time"),
            last_summary=data.get("last_summary"),
            alert_state=data.get("alert_state", "OK"),
        )


def _get_db_path() -> Path:
    """Compute DB path lazily from current settings."""
    return Path(settings.chroma_path).parent / "scheduler.sqlite"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema(db_path: Path | None = None) -> None:
    global _initialised
    if _initialised:
        return
    with _lock, _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scheduler_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER NOT NULL DEFAULT 0,
                interval_seconds INTEGER NOT NULL DEFAULT 3600,
                last_run_time REAL,
                next_run_time REAL,
                last_summary TEXT,
                alert_state TEXT NOT NULL DEFAULT 'OK'
            );
            INSERT OR IGNORE INTO scheduler_state (id, enabled, interval_seconds, alert_state)
            VALUES (1, 0, 3600, 'OK');
            """
        )
    _initialised = True


def read_state(db_path: Path | None = None) -> SchedulerState:
    """Read current scheduler state from DB."""
    _ensure_schema(db_path)
    with _lock, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT enabled, interval_seconds, last_run_time, next_run_time, last_summary, alert_state "
            "FROM scheduler_state WHERE id = 1"
        ).fetchone()
    if not row:
        return SchedulerState()
    last_summary = None
    if row["last_summary"]:
        try:
            last_summary = json.loads(row["last_summary"])
        except (json.JSONDecodeError, TypeError):
            pass
    return SchedulerState(
        enabled=bool(row["enabled"]),
        interval_seconds=row["interval_seconds"] or 3600,
        last_run_time=row["last_run_time"],
        next_run_time=row["next_run_time"],
        last_summary=last_summary,
        alert_state=row["alert_state"] or "OK",
    )


def update_state(
    enabled: bool | None = None,
    interval_seconds: int | None = None,
    db_path: Path | None = None,
) -> SchedulerState:
    """Update scheduler enabled/interval and return the latest state."""
    _ensure_schema(db_path)
    state = read_state(db_path)
    if enabled is not None:
        state.enabled = bool(enabled)
    if interval_seconds is not None:
        state.interval_seconds = max(60, int(interval_seconds))

    now = time.time()
    next_run_time = now + state.interval_seconds if state.enabled else None
    with _lock, _connect(db_path) as conn:
        conn.execute(
            "UPDATE scheduler_state SET enabled = ?, interval_seconds = ?, next_run_time = ? WHERE id = 1",
            (int(state.enabled), state.interval_seconds, next_run_time),
        )
    return read_state(db_path)


def save_run_summary(
    summary: dict,
    alert_state: str = "OK",
    db_path: Path | None = None,
) -> None:
    """Save health-check run result + alert state + next run time."""
    _ensure_schema(db_path)
    state = read_state(db_path)
    now = time.time()
    next_run = now + state.interval_seconds if state.enabled else None
    summary_json = json.dumps(summary, ensure_ascii=False)
    with _lock, _connect(db_path) as conn:
        conn.execute(
            """UPDATE scheduler_state
               SET last_run_time = ?, next_run_time = ?, last_summary = ?, alert_state = ?
               WHERE id = 1""",
            (now, next_run, summary_json, alert_state),
        )
