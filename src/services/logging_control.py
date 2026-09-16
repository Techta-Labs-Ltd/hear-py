from __future__ import annotations

import logging


class ApplicationLog:
    _logger = logging.getLogger("hear")

    @classmethod
    def configure(cls, enabled: bool) -> None:
        logging.disable(logging.NOTSET if enabled else logging.CRITICAL)
        cls._logger.setLevel(logging.INFO)

    @classmethod
    def debug(cls, message: str, *args, **kwargs) -> None:
        cls._logger.debug(message, *args, **kwargs)

    @classmethod
    def info(cls, message: str, *args, **kwargs) -> None:
        cls._logger.info(message, *args, **kwargs)

    @classmethod
    def warning(cls, message: str, *args, **kwargs) -> None:
        cls._logger.warning(message, *args, **kwargs)

    @classmethod
    def error(cls, message: str, *args, **kwargs) -> None:
        cls._logger.error(message, *args, **kwargs)

    @classmethod
    def exception(cls, message: str, *args, **kwargs) -> None:
        cls._logger.exception(message, *args, **kwargs)
