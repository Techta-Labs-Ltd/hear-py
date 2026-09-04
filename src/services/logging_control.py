from __future__ import annotations

import logging


class LoggingControl:
    @staticmethod
    def configure(enabled: bool) -> None:
        logging.disable(logging.NOTSET if enabled else logging.CRITICAL)
