from __future__ import annotations

import asyncio
import threading
import time

import httpx

from config import settings


class HttpCircuitOpen(RuntimeError):
    pass


class HttpCircuitBreaker:
    __slots__ = (
        "_failure_threshold",
        "_recovery_seconds",
        "_failures",
        "_opened_at",
        "_lock",
    )

    def __init__(self, failure_threshold: int, recovery_ms: int) -> None:
        self._failure_threshold = max(failure_threshold, 1)
        self._recovery_seconds = max(recovery_ms, 1) / 1000.0
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def before_request(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if time.monotonic() - self._opened_at >= self._recovery_seconds:
                self._opened_at = None
                self._failures = 0
                return
            raise HttpCircuitOpen("HTTP dependency circuit is open")

    def succeeded(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def failed(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = time.monotonic()


class CircuitHttpClient:
    __slots__ = ("_client", "_breaker")

    def __init__(self, client: httpx.AsyncClient, breaker: HttpCircuitBreaker) -> None:
        self._client = client
        self._breaker = breaker

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, url, **kwargs):
        requested = httpx.URL(url)
        upstream = self._client.base_url
        if (
            upstream.is_absolute_url
            and requested.is_absolute_url
            and (requested.scheme, requested.host, requested.port)
            != (upstream.scheme, upstream.host, upstream.port)
        ):
            raise ValueError("HTTP request does not match the configured upstream")
        self._breaker.before_request()
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.HTTPError:
            self._breaker.failed()
            raise
        if response.status_code >= 500:
            self._breaker.failed()
        else:
            self._breaker.succeeded()
        return response

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self.request("POST", url, **kwargs)

    async def delete(self, url, **kwargs):
        return await self.request("DELETE", url, **kwargs)


class HttpPool:
    def __init__(
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        timeout_ms: int | None = None,
        max_connections: int | None = None,
        max_keepalive: int | None = None,
    ) -> None:
        self._base_url = str(base_url).strip().rstrip("/")
        self._headers = tuple(sorted(httpx.Headers(headers or {}).items()))
        self._pool: dict[asyncio.AbstractEventLoop, CircuitHttpClient] = {}
        self._lock = threading.Lock()
        self._breaker = HttpCircuitBreaker(
            settings.HEAR_HTTP_CIRCUIT_FAILURE_THRESHOLD,
            settings.HEAR_HTTP_CIRCUIT_RECOVERY_MS,
        )
        resolved_timeout = (
            timeout_ms if timeout_ms is not None else settings.HEAR_HTTP_DEFAULT_TIMEOUT_MS
        )
        resolved_connections = (
            max_connections if max_connections is not None else settings.HEAR_HTTP_MAX_CONNECTIONS
        )
        resolved_keepalive = (
            max_keepalive
            if max_keepalive is not None
            else settings.HEAR_HTTP_MAX_KEEPALIVE_CONNECTIONS
        )
        self._timeout = httpx.Timeout(max(resolved_timeout, 1) / 1000.0)
        self._limits = httpx.Limits(
            max_connections=max(resolved_connections, 1),
            max_keepalive_connections=max(resolved_keepalive, 0),
        )

    def assert_configuration(self, *, base_url: str, headers: dict[str, str]) -> None:
        if self._base_url != str(base_url).strip().rstrip("/") or self._headers != tuple(
            sorted(httpx.Headers(headers).items())
        ):
            raise ValueError("HTTP pool configuration does not match this client")

    def get(self) -> CircuitHttpClient:
        key = asyncio.get_running_loop()
        client = self._pool.get(key)
        if client is None or client.is_closed:
            with self._lock:
                for loop in tuple(self._pool):
                    if loop.is_closed():
                        self._pool.pop(loop)
                client = self._pool.get(key)
                if client is None or client.is_closed:
                    kwargs: dict = {"timeout": self._timeout, "limits": self._limits}
                    if self._base_url:
                        kwargs["base_url"] = self._base_url
                    if self._headers:
                        kwargs["headers"] = dict(self._headers)
                    client = CircuitHttpClient(httpx.AsyncClient(**kwargs), self._breaker)
                    self._pool[key] = client
        return client

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        client = self._pool.pop(loop, None)
        if client is not None and not client.is_closed:
            await client.aclose()

    def active_client_count(self) -> int:
        return len(self._pool)
