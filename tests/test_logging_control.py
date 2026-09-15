from __future__ import annotations

import logging

from src.services.logging_control import ApplicationLog


class TestApplicationLog:
    def teardown_method(self) -> None:
        ApplicationLog.configure(True)

    def test_false_suppresses_application_logs(self, caplog) -> None:
        logger = logging.getLogger("hear")
        with caplog.at_level(logging.INFO, logger=logger.name):
            ApplicationLog.configure(False)
            ApplicationLog.error("hidden application log")
        assert "hidden application log" not in caplog.text

    def test_true_allows_application_logs(self, caplog) -> None:
        logger = logging.getLogger("hear")
        with caplog.at_level(logging.INFO, logger=logger.name):
            ApplicationLog.configure(True)
            ApplicationLog.info("visible application log")
        assert "visible application log" in caplog.text
