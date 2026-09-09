"""
Structured logging setup -- adapted from a reference pattern, but
deliberately structlog-ONLY (no bridging into stdlib's logging module)
since this project has no existing stdlib logging config to
interoperate with. Simpler to configure and reason about than a
dual stdlib+structlog setup would be, for a project this size.

Scripts (scripts/*.py) deliberately keep using plain print() -- they
are one-shot manual runs a human watches directly in a terminal.
Structured logging's real value (consistent fields, JSON output for
log aggregation, per-request/job context) is for the LONG-RUNNING
processes -- the FastAPI app and the Celery worker -- not one-off
scripts. Call configure_logging() ONCE, at startup, before anything
else logs.
"""
from __future__ import annotations

import logging

import structlog


def configure_logging(json_logs: bool = False, log_level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )