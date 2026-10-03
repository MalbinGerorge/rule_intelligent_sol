"""
Structured logging setup. configure_logging() sets up the general
app.log (console + rotating file), same as before.

configure_simulator_logging() is a SEPARATE, additional setup --
routes everything logged under the "app.agents.simulator" namespace
(every module there uses structlog.get_logger(__name__), so this
covers attack_interpreter, and every future agent added under that
package) into its own file, logs/simulator.log, instead of the
general app.log. propagate=False means simulator events do NOT also
appear in app.log -- keeps the two logs genuinely separate, so
reviewing simulator behavior (agent reasoning, timing, tool calls)
never requires filtering it out of unrelated application noise.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import structlog

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_FILE = LOG_DIR / "app.log"
SIMULATOR_LOG_FILE = LOG_DIR / "simulator.log"

MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5

_PRIORITY_KEYS = ["timestamp", "level", "logger", "event"]


def _reorder_keys(logger, method_name, event_dict):
    ordered = {}
    for key in _PRIORITY_KEYS:
        if key in event_dict:
            ordered[key] = event_dict.pop(key)
    ordered.update(event_dict)
    return ordered


def _shared_processors():
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _reorder_keys,
    ]


def configure_logging(log_level: str = "INFO") -> None:
    LOG_DIR.mkdir(exist_ok=True)
    shared_processors = _shared_processors()

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(), foreign_pre_chain=shared_processors
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)

    file_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(), foreign_pre_chain=shared_processors
    )
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [console_handler, file_handler]
    root_logger.setLevel(log_level)


def configure_simulator_logging(log_level: str = "INFO") -> None:
    """Call this ONCE, alongside configure_logging(), at startup.
    Routes every app.agents.simulator.* log event into its own file."""
    LOG_DIR.mkdir(exist_ok=True)
    shared_processors = _shared_processors()

    file_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(), foreign_pre_chain=shared_processors
    )
    file_handler = logging.handlers.RotatingFileHandler(
        SIMULATOR_LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)

    simulator_logger = logging.getLogger("app.agent.simulator")
    simulator_logger.handlers = [file_handler]
    simulator_logger.setLevel(log_level)
    simulator_logger.propagate = False  # don't ALSO send these to app.log