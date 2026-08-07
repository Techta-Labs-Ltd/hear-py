from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings
from src.clients.pool import HttpPool
from src.models import ResolvedEntity, ResolverResult, ResolverUnavailable

logger = logging.getLogger(__name__)

_RESOLVER_POOL = HttpPool(timeout_ms=2000)


class ResolverClient:
    __slots__ = ("_host", "_api_key", "_default_country", "_timeout", "_pool", "_transport")

    def __init__(
        self,
        *,
        host: str,
        api_key: str,
        default_country: str = "gb",
        timeout_ms: int = 2000,
        transport: httpx.AsyncBaseTransport | None = None,
        pool: HttpPool | None = None,
    ) -> None:
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._default_country = default_country
        self._timeout = httpx.Timeout(max(timeout_ms, 1) / 1000.0)
        self._transport = transport
        self._pool = pool or _RESOLVER_POOL

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
                response = await self._pool.get().post(
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

    async def resolve_utterance(
        self,
        utterance: str,
        *,
        alexa_user_id: str | None = None,
        timezone: str = "Europe/London",
        country_code: str | None = None,
    ) -> dict[str, Any]:
        result = await self.resolve(
            utterance,
            alexa_user_id=alexa_user_id,
            timezone=timezone,
            country_code=country_code,
        )
        return result.to_alexa_payload()


client = ResolverClient(
    host=getattr(settings, "RESOLVER_HOST", None) or "https://resolver.hear.media",
    api_key=settings.HEAR_API_KEY,
    default_country=getattr(settings, "RESOLVER_DEFAULT_COUNTRY", None) or "gb",
    timeout_ms=getattr(settings, "RESOLVER_TIMEOUT_MS", None) or 2000,
)

resolve_utterance = client.resolve_utterance

__all__ = [
    "ResolverClient",
    "ResolverResult",
    "ResolvedEntity",
    "ResolverUnavailable",
    "resolve_utterance",
]
