from __future__ import annotations
import asyncio
import logging
import threading
from typing import Any
import httpx
from config import settings
from src.models import ResolverResult, ResolvedEntity, ResolverUnavailable
logger = logging.getLogger(__name__)


RESOLVER_URL = "https://resolver.hear.media"


DEFAULT_COUNTRY_CODE = "gb"


DEFAULT_TIMEOUT_MS = 2000


_client_pool: dict[int, httpx.AsyncClient] = {}


_client_pool_lock = threading.Lock()


def _pooled_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    key = id(loop)
    client = _client_pool.get(key)
    if client is None:
        with _client_pool_lock:
            client = _client_pool.get(key)
            if client is None:
                client = httpx.AsyncClient(
                    timeout=httpx.Timeout(DEFAULT_TIMEOUT_MS / 1000.0),
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                )
                _client_pool[key] = client
    return client


class ResolverClient:
    def __init__(
        self,
        *,
        host: str,
        api_key: str,
        default_country: str = "gb",
        timeout_ms: int = 2000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._default_country = default_country
        self._timeout = httpx.Timeout(max(timeout_ms, 1) / 1000.0)
        self._transport = transport

    async def resolve(
        self,
        utterance: str,
        *,
        alexa_user_id: str | None = None,
        timezone: str = "Europe/London",
        country_code: str | None = None,
    ) -> ResolverResult:
        body: dict[str, Any] = {
            "utterance": utterance,
            "timezone": timezone,
            "country_code": country_code or self._default_country,
        }
        if alexa_user_id:
            body["alexaUserId"] = alexa_user_id
        try:
            if self._transport is not None:
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    transport=self._transport,
                ) as client:
                    response = await client.post(
                        f"{self._host}/resolve",
                        json=body,
                        headers={"x-api-key": self._api_key},
                    )
            else:
                response = await _pooled_client().post(
                    f"{self._host}/resolve",
                    json=body,
                    headers={"x-api-key": self._api_key},
                    timeout=self._timeout,
                )
            if not 200 <= response.status_code < 300:
                raise ResolverUnavailable(f"resolver returned HTTP {response.status_code}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise ResolverUnavailable("resolver response must be an object")
            return ResolverResult.from_payload(payload)
        except ResolverUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Resolver request failed error=%s", type(exc).__name__)
            raise ResolverUnavailable("resolver request failed") from exc


def _configured_client() -> ResolverClient:
    return ResolverClient(
        host=RESOLVER_URL,
        api_key=settings.HEAR_API_KEY,
        default_country=DEFAULT_COUNTRY_CODE,
        timeout_ms=DEFAULT_TIMEOUT_MS,
    )


async def resolve_utterance(
    utterance: str,
    *,
    alexa_user_id: str | None = None,
    timezone: str = "Europe/London",
    country_code: str | None = None,
) -> dict[str, Any]:
    result = await _configured_client().resolve(
        utterance,
        alexa_user_id=alexa_user_id,
        timezone=timezone,
        country_code=country_code,
    )
    return result.to_alexa_payload()


__all__ = [
    "ResolverClient",
    "ResolverResult",
    "ResolvedEntity",
    "ResolverUnavailable",
    "resolve_utterance",
]
