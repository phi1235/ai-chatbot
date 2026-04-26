"""Structured JSON logging với request_id correlation.

Usage:
    from observability import get_logger, set_request_id, clear_request_id

    logger = get_logger(__name__)
    set_request_id("req-abc-123")
    logger.info("message", extra={"latency_ms": 12.3, "topic": "kubernetes"})
    clear_request_id()

Output (1 dòng JSON / 1 record):
    {"ts":"2026-04-26T10:30:00Z","level":"INFO","logger":"agent",
     "msg":"chat completed","request_id":"req-abc-123","latency_ms":12.3,...}

Bật JSON format mặc định khi `LOG_FORMAT=json` (production) hoặc khi không phải TTY.
TTY (dev local) dùng plain text dễ đọc.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import UTC, datetime

# Standard fields bị bỏ khỏi `extra` để tránh lặp
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}

# Context var để propagate request_id qua các log calls trong cùng request
_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def set_request_id(request_id: str | None) -> None:
    """Gắn request_id cho tất cả log trong context hiện tại."""
    _request_id_ctx.set(request_id)


def clear_request_id() -> None:
    _request_id_ctx.set(None)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


class JsonFormatter(logging.Formatter):
    """Format mỗi log record thành 1 dòng JSON."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Inject request_id từ context nếu có
        rid = getattr(record, "request_id", None) or _request_id_ctx.get()
        if rid:
            out["request_id"] = rid

        # Extra fields (mọi attr không thuộc reserved)
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_") or key == "request_id":
                continue
            try:
                json.dumps(value)
                out[key] = value
            except (TypeError, ValueError):
                out[key] = repr(value)

        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)

        return json.dumps(out, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Format dễ đọc cho dev local (TTY)."""

    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", None) or _request_id_ctx.get() or "-"
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        base = f"{ts} {record.levelname:5s} [{record.name}] req={rid[:8]} {record.getMessage()}"
        # Append extra fields
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_") and k != "request_id"
        }
        if extras:
            extra_str = " ".join(f"{k}={v}" for k, v in extras.items())
            base = f"{base}  {extra_str}"
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        return base


def _choose_formatter() -> logging.Formatter:
    fmt = os.getenv("LOG_FORMAT", "").lower()
    if fmt == "json":
        return JsonFormatter()
    if fmt == "text":
        return TextFormatter()
    # Auto: json khi không phải TTY (production / docker), text khi dev
    return TextFormatter() if sys.stdout.isatty() else JsonFormatter()


_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_FORMATTER: logging.Formatter | None = None


def get_logger(name: str) -> logging.Logger:
    global _FORMATTER
    if _FORMATTER is None:
        _FORMATTER = _choose_formatter()

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_FORMATTER)
    logger.addHandler(handler)
    logger.setLevel(_LEVEL)
    logger.propagate = False
    return logger
