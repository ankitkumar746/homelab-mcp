import json
import logging
import re
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = re.compile(
    r"(password|passwd|key|token|secret|psk|credential|private)", re.IGNORECASE
)


def _redact(args: dict | None) -> dict | None:
    if not args:
        return args
    return {k: ("***REDACTED***" if _SENSITIVE_KEYS.search(k) else v) for k, v in args.items()}


class JsonFormatter(logging.Formatter):
    """JSON line formatter with ClickHouse DateTime64 timestamps."""

    def format(self, record: logging.LogRecord) -> str:

        ts = datetime.fromtimestamp(record.created, tz=datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )

        entry = {
            "ts": ts,
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
            "request_id": getattr(record, "request_id", None),
            "tool": getattr(record, "tool", None),
            "node": getattr(record, "node", None),
            "args": _redact(getattr(record, "tool_args", None)),
            "duration_ms": getattr(record, "duration_ms", None),
            "status": getattr(record, "status", None),
            "safety_level": getattr(record, "safety_level", None),
            "command": getattr(record, "command", None),
            "detail": record.getMessage(),
        }
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logger(log_dir: Path, log_level: str = "INFO") -> logging.Logger:
    """Set up JSON file logger. Creates a new timestamped file per execution."""
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"homelab_mcp_{timestamp}.jsonl"

    logger = logging.getLogger("homelab")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()

    handler = logging.FileHandler(str(log_file), encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False

    return logger


@dataclass
class ToolCallContext:
    """Mutable context for a tool call. Set ``status`` to override the default 'success'."""

    request_id: str
    status: str = "success"


@contextmanager
def log_tool_call(
    logger: logging.Logger,
    tool_name: str,
    node: str | None = None,
    **kwargs: Any,
) -> Iterator[ToolCallContext]:
    """Context manager that logs tool call start/end with timing.

    Works in both sync and async tool functions:

        with log_tool_call(logger, "check_service", node="homelab") as ctx:
            result = await ssh.execute(...)
            # optionally: ctx.status = "blocked" to override default "success"
    """
    call_ctx = ToolCallContext(request_id=secrets.token_hex(4))
    start = time.monotonic()

    logger.info(
        "tool call started",
        extra={
            "event": "tool.call",
            "request_id": call_ctx.request_id,
            "tool": tool_name,
            "node": node,
            "tool_args": kwargs or None,
        },
    )

    try:
        yield call_ctx
    except Exception as e:
        duration = round((time.monotonic() - start) * 1000, 1)
        logger.error(
            str(e),
            extra={
                "event": "tool.error",
                "request_id": call_ctx.request_id,
                "tool": tool_name,
                "node": node,
                "duration_ms": duration,
                "status": "error",
            },
        )
        raise
    else:
        duration = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            "tool call completed",
            extra={
                "event": "tool.response",
                "request_id": call_ctx.request_id,
                "tool": tool_name,
                "node": node,
                "duration_ms": duration,
                "status": call_ctx.status,
            },
        )
