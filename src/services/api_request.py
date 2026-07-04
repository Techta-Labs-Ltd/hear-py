from __future__ import annotations
import asyncio
import httpx
from config import settings

_MAX_ATTEMPTS = 4
_RETRY_DELAYS_MS = [200, 400, 800]


class ApiRequestError(Exception):
    """Raised when a Hear API request fails after all retries."""

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


def _resolve_alexa_api_root() -> str:
    explicit = getattr(settings, "HEAR_ALEXA_API_URL", "") or ""
    if explicit:
        return str(explicit).strip().rstrip("/")
    base = (settings.api_base_url or "").strip().rstrip("/")
    if not base:
        return ""
    prefix = getattr(settings, "HEAR_API_PATH_PREFIX", "") or "api/v1/alexa"
    prefix = str(prefix).strip().strip("/")
    return f"{base}/{prefix}"


def _build_url(path: str) -> str:
    root = _resolve_alexa_api_root()
    rel = path if path.startswith("/") else f"/{path}"
    return f"{root}{rel}"


def _is_retryable_error(err: Exception) -> bool:
    if isinstance(err, httpx.TimeoutException):
        return False
    if isinstance(err, httpx.NetworkError):
        return True
    if isinstance(err, httpx.HTTPStatusError):
        return err.response.status_code >= 500
    return True


def _resolve_api_key() -> str:
    secret = getattr(settings, "HEAR_AI_SERVICE_SECRET", "") or ""
    return str(secret).strip() or (settings.api_key or "")


async def api_request(
    method: str,
    path: str,
    body: dict | None = None,
    timeout_ms: int | None = None,
) -> dict | list | None:
    """Issue an HTTP request to the Hear backend with automatic retry.

    Args:
        method: HTTP method (GET, POST, PATCH, DELETE).
        path: URL path relative to the Alexa API root.
        body: JSON body for POST/PATCH requests.
        timeout_ms: Per-request timeout in milliseconds.

    Returns:
        Parsed JSON response body on success.

    Raises:
        ApiRequestError: When all retries are exhausted or a non-retryable
                         4xx status is received.
    """
    url = _build_url(path)
    api_key = _resolve_api_key()
    env_timeout = int(getattr(settings, "HEAR_API_TIMEOUT_MS", "") or "") or 0
    default_timeout = env_timeout if env_timeout > 0 else (settings.api_timeout_ms or 8000)
    timeout_secs = (timeout_ms if timeout_ms else default_timeout) / 1000.0

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key

    last_status = 0

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_secs)) as client:
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await client.request(method, url, json=body, headers=headers)
                last_status = resp.status_code
                if 200 <= resp.status_code < 300:
                    return resp.json()
                if resp.status_code < 500:
                    raise ApiRequestError(
                        f"API {method} {path} failed: {resp.status_code}",
                        url=url,
                        method=method,
                        status=resp.status_code,
                        attempts=attempt + 1,
                    )
                if attempt < _MAX_ATTEMPTS - 1:
                    delay = _RETRY_DELAYS_MS[min(attempt, len(_RETRY_DELAYS_MS) - 1)] / 1000.0
                    await asyncio.sleep(delay)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt < _MAX_ATTEMPTS - 1:
                    delay = _RETRY_DELAYS_MS[min(attempt, len(_RETRY_DELAYS_MS) - 1)] / 1000.0
                    await asyncio.sleep(delay)
                else:
                    raise ApiRequestError(
                        f"API {method} {path} network error after {_MAX_ATTEMPTS} attempts",
                        url=url,
                        method=method,
                        status=0,
                        attempts=_MAX_ATTEMPTS,
                    )

    raise ApiRequestError(
        f"API {method} {path} failed: {last_status}",
        url=url,
        method=method,
        status=last_status,
        attempts=_MAX_ATTEMPTS,
    )
