from __future__ import annotations

from config import settings
from src.clients.pool import HttpPool


class AlexaClient:
    __slots__ = ("_pool",)

    def __init__(self, pool: HttpPool | None = None) -> None:
        self._pool = pool or HttpPool(timeout_ms=settings.HEAR_ALEXA_API_TIMEOUT_MS)
