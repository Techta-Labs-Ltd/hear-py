from __future__ import annotations

import logging


class ApplicationLog:
    _logger = logging.getLogger("hear")
    _enabled = True

    @classmethod
    def configure(cls, enabled: bool) -> None:
        cls._enabled = bool(enabled)
        cls._logger.setLevel(logging.INFO)

    @classmethod
    def debug(cls, message: str, *args, **kwargs) -> None:
        if cls._enabled:
            cls._logger.debug(message, *args, **kwargs)

    @classmethod
    def info(cls, message: str, *args, **kwargs) -> None:
        if cls._enabled:
            cls._logger.info(message, *args, **kwargs)

    @classmethod
    def warning(cls, message: str, *args, **kwargs) -> None:
        if cls._enabled:
            cls._logger.warning(message, *args, **kwargs)

    @classmethod
    def error(cls, message: str, *args, **kwargs) -> None:
        if cls._enabled:
            cls._logger.error(message, *args, **kwargs)

    @classmethod
    def exception(cls, message: str, *args, **kwargs) -> None:
        if cls._enabled:
            cls._logger.exception(message, *args, **kwargs)
