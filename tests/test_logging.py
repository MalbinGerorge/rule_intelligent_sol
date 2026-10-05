import logging
import logging.handlers

import app.ai.agents.simulator.orchestrator as simulator_module
from app.core import logging as app_logging


def test_simulator_logs_reach_simulator_log(tmp_path, monkeypatch):
    """configure_simulator_logging() routes by logger NAME. If the simulator
    package moves without updating SIMULATOR_LOGGER_NAME, its logs silently
    stop reaching simulator.log -- no error anywhere -- so check that a real
    simulator module's logger resolves to the simulator file handler."""
    monkeypatch.setattr(app_logging, "SIMULATOR_LOG_FILE", tmp_path / "simulator.log")
    configured = logging.getLogger(app_logging.SIMULATOR_LOGGER_NAME)
    saved = (configured.handlers[:], configured.level, configured.propagate)
    try:
        app_logging.configure_simulator_logging()

        logger = logging.getLogger(simulator_module.__name__)
        while logger is not None and not logger.handlers and logger.propagate:
            logger = logger.parent
        file_handlers = [
            h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
        ]

        assert logger.name == app_logging.SIMULATOR_LOGGER_NAME
        assert [h.baseFilename for h in file_handlers] == [str(tmp_path / "simulator.log")]
    finally:
        for h in configured.handlers:
            if h not in saved[0]:
                h.close()
        configured.handlers, configured.level, configured.propagate = saved
