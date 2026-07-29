from __future__ import annotations

import asyncio

import httpx

from config import settings


class ApiRequestError(Exception):
    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        method: str = "",
        status: int = 0,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.method = method
        self.status = status
        self.attempts = attempts


class ApiRequester:
    def __init__(
        self,
        *,
        max_attempts: int = 4,
        retry_delays_ms: tuple[int, ...] = (200, 400, 800),
    ) -> None:
        self.max_attempts = max_attempts
        self.retry_delays_ms = retry_delays_ms

    def _root(self) -> str:
        explicit = getattr(settings, "HEAR_ALEXA_API_URL", "") or ""
        if explicit:
            return str(explicit).strip().rstrip("/")
        base = (settings.api_base_url or "").strip().rstrip("/")
        if not base:
            return ""
        prefix = getattr(settings, "HEAR_API_PATH_PREFIX", "") or "api/v1/alexa"
        return f"{base}/{str(prefix).strip().strip('/')}"

    def _url(self, path: str) -> str:
        relative = path if path.startswith("/") else f"/{path}"
        return f"{self._root()}{relative}"

    def _api_key(self) -> str:
        secret = getattr(settings, "HEAR_AI_SERVICE_SECRET", "") or ""
        return str(secret).strip() or (settings.api_key or "")

    def _timeout_seconds(self, timeout_ms: int | None) -> float:
        configured = int(getattr(settings, "HEAR_API_TIMEOUT_MS", "") or "") or 0
        default = configured if configured > 0 else (settings.api_timeout_ms or 8000)
        return (timeout_ms or default) / 1000.0

    async def _retry_delay(self, attempt: int) -> None:
        index = min(attempt, len(self.retry_delays_ms) - 1)
        await asyncio.sleep(self.retry_delays_ms[index] / 1000.0)

    async def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        timeout_ms: int | None = None,
    ) -> dict | list | None:
        url = self._url(path)
        headers = {"Content-Type": "application/json"}
        api_key = self._api_key()
        if api_key:
            headers["X-Api-Key"] = api_key
        last_status = 0

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout_seconds(timeout_ms))
        ) as client:
            for attempt in range(self.max_attempts):
                try:
                    response = await client.request(
                        method,
                        url,
                        json=body,
                        headers=headers,
                    )
                    last_status = response.status_code
                    if 200 <= last_status < 300:
                        return response.json()
                    if last_status < 500:
                        raise ApiRequestError(
                            f"API {method} {path} failed: {last_status}",
                            url=url,
                            method=method,
                            status=last_status,
                            attempts=attempt + 1,
                        )
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == self.max_attempts - 1:
                        raise ApiRequestError(
                            f"API {method} {path} network error after {self.max_attempts} attempts",
                            url=url,
                            method=method,
                            attempts=self.max_attempts,
                        )
                if attempt < self.max_attempts - 1:
                    await self._retry_delay(attempt)

        raise ApiRequestError(
            f"API {method} {path} failed: {last_status}",
            url=url,
            method=method,
            status=last_status,
            attempts=self.max_attempts,
        )


api_requester = ApiRequester()


async def api_request(
    method: str,
    path: str,
    body: dict | None = None,
    timeout_ms: int | None = None,
) -> dict | list | None:
    return await api_requester.request(method, path, body, timeout_ms)
