from __future__ import annotations

import logging
import re
from pathlib import Path

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

    def test_false_does_not_disable_unrelated_loggers(self, caplog) -> None:
        external = logging.getLogger("independent-service")
        with caplog.at_level(logging.INFO):
            ApplicationLog.configure(False)
            external.info("external logger remains enabled")
        assert "external logger remains enabled" in caplog.text

    def test_application_logs_do_not_use_sensitive_value_templates(self) -> None:
        source_root = Path(__file__).parents[1] / "src"
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in source_root.rglob("*.py")
        )
        assert not re.search(
            r"\b(?:query|utterance|phrase|payload|text|label|city|token|message|traceback|contentId)=%[rs]",
            source,
        )
        assert "logging.disable" not in (
            source_root / "services" / "logging_control.py"
        ).read_text(encoding="utf-8")
