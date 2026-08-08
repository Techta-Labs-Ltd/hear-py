from __future__ import annotations

import logging
import json
import traceback
from typing import Any

import httpx

from config import settings
from src.clients.pool import HttpPool
from src.models import ResolvedEntity, ResolverResult, ResolverUnavailable

logger = logging.getLogger(__name__)

RESOLVER_HOST = "https://resolver.hear.media"
RESOLVER_TIMEOUT_MS = 5000
RESOLVER_DEFAULT_COUNTRY = "gb"

_RESOLVER_POOL = HttpPool(timeout_ms=RESOLVER_TIMEOUT_MS)


class ResolverClient:
    __slots__ = ("_host", "_api_key", "_default_country", "_timeout", "_pool", "_transport")

    def __init__(
        self,
        *,
        host: str = RESOLVER_HOST,
        api_key: str,
        default_country: str = RESOLVER_DEFAULT_COUNTRY,
        timeout_ms: int = RESOLVER_TIMEOUT_MS,
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
        logged_body = {
            **body,
            **({"alexaUserId": "<present>"} if alexa_user_id else {}),
        }
        logger.info(
            "Hear: resolver request payload=%s",
            json.dumps(logged_body, sort_keys=True, separators=(",", ":")),
        )
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
        except ResolverUnavailable as exc:
            logger.warning("Resolver response rejected reason=%s", exc)
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Resolver request failed error=%s traceback=%s", type(exc).__name__, traceback.format_exc())
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
        payload = result.to_alexa_payload()
        logger.info(
            "Hear: resolver normalized response status=%s intent=%s slots=%s",
            payload.get("status"),
            payload.get("intent"),
            json.dumps(payload.get("slots") or {}, sort_keys=True, separators=(",", ":")),
        )
        return payload


client = ResolverClient(
    api_key=settings.HEAR_API_KEY,
)

resolve_utterance = client.resolve_utterance

__all__ = [
    "ResolverClient",
    "ResolverResult",
    "ResolvedEntity",
    "ResolverUnavailable",
    "resolve_utterance",
]
