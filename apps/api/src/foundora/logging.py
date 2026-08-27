from __future__ import annotations

import contextvars
import json
import logging
from datetime import UTC, datetime
from typing import Any

correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")


class JsonFormatter(logging.Formatter):
    _extra_fields = (
        "event",
        "http_method",
        "http_path",
        "http_status",
        "duration_ms",
        "sandbox_execution_id",
        "sandbox_outcome",
        "sandbox_duration_ms",
        "sandbox_cleanup_status",
        "sandbox_cleanup_attempts",
        "sandbox_remaining_resources",
        "sandbox_worker_recoveries",
        "sandbox_recovered",
        "sandbox_failed",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": "foundora",
            "correlation_id": correlation_id.get(),
            "message": record.getMessage(),
        }
        for field in self._extra_fields:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "rq.worker"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
