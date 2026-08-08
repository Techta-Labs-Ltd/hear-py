from __future__ import annotations

import asyncio
import threading

import httpx


class HttpPool:
    """Thread-safe httpx.AsyncClient pool keyed by event loop.

    Each caller shares the same connection to the same base URL within a
    loop, avoiding recreation of clients on every request while remaining safe
    across threads.
    """

    def __init__(
        self,
        *,
        timeout_ms: int = 30_000,
        max_connections: int = 20,
        max_keepalive: int = 10,
    ) -> None:
        self._pool: dict[int, httpx.AsyncClient] = {}
        self._lock = threading.Lock()
        self._timeout = httpx.Timeout(timeout_ms / 1000.0)
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
        )

    def get(self, *, base_url: str = "", headers: dict | None = None) -> httpx.AsyncClient:
        key = id(asyncio.get_running_loop())
        client = self._pool.get(key)
        if client is None:
            with self._lock:
                client = self._pool.get(key)
                if client is None:
                    kwargs: dict = {
                        "timeout": self._timeout,
                        "limits": self._limits,
                    }
                    if base_url:
                        kwargs["base_url"] = base_url
                    if headers:
                        kwargs["headers"] = headers
                    client = httpx.AsyncClient(**kwargs)
                    self._pool[key] = client
        return client
