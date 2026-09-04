from __future__ import annotations

import logging

from src.services.logging_control import LoggingControl


class TestLoggingControl:
    def teardown_method(self) -> None:
        LoggingControl.configure(True)

    def test_false_suppresses_application_logs(self, caplog) -> None:
        logger = logging.getLogger("src.test.logging")
        with caplog.at_level(logging.INFO, logger=logger.name):
            LoggingControl.configure(False)
            logger.error("hidden application log")
        assert "hidden application log" not in caplog.text

    def test_true_allows_application_logs(self, caplog) -> None:
        logger = logging.getLogger("src.test.logging")
        with caplog.at_level(logging.INFO, logger=logger.name):
            LoggingControl.configure(True)
            logger.info("visible application log")
        assert "visible application log" in caplog.text
