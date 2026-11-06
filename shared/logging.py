"""Structured JSON logging with a run_id on every record."""

import json
import logging
import uuid
from datetime import UTC, datetime

_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}


def new_run_id() -> str:
    """Return a new unique id for one job run."""
    return uuid.uuid4().hex


class JsonFormatter(logging.Formatter):
    """Format each log record as one JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": getattr(record, "run_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RunLoggerAdapter(logging.LoggerAdapter):
    """Add run_id to every record while keeping any extra fields the caller passes."""

    def process(self, msg, kwargs):
        kwargs["extra"] = {**(kwargs.get("extra") or {}), **self.extra}
        return msg, kwargs


def get_logger(name: str, run_id: str, level: str = "INFO") -> RunLoggerAdapter:
    """Return a logger that writes JSON lines and tags every record with run_id."""
    logger = logging.getLogger(name)
    if not any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(level)
    return RunLoggerAdapter(logger, {"run_id": run_id})
