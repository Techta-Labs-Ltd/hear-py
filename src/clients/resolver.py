from __future__ import annotations

import json
import logging
import time
import traceback
from dataclasses import dataclass
from typing import Any

import httpx

from config import settings
from src.clients.pool import HttpPool
from src.models.resolver import ResolverResult, ResolverUnavailable


class ResolverClientSupport:
    logger = logging.getLogger(__name__)

    @staticmethod
    def _without_coordinates(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: ResolverClientSupport._without_coordinates(item)
                for key, item in value.items()
                if key not in {"latitude", "longitude"}
            }
        if isinstance(value, list):
            return [ResolverClientSupport._without_coordinates(item) for item in value]
        return value

    @staticmethod
    def _resolver_response_log(payload: dict[str, Any]) -> dict[str, Any]:
        """Return useful resolver diagnostics without coordinates or account data."""
        safe_slots = ResolverClientSupport._without_coordinates(payload.get("slots") or {})
        safe_entities = []
        for entity in payload.get("entities") or []:
            if not isinstance(entity, dict):
                continue
            safe_entities.append(
                {
                    "type": entity.get("entityType") or entity.get("type"),
                    "id": entity.get("entityId") or entity.get("id"),
                    "value": entity.get("canonicalValue") or entity.get("name"),
                }
            )
        return {
            "status": payload.get("status"),
            "intent": payload.get("intent"),
            "entities": safe_entities,
            "slots": safe_slots,
            "ambiguityCount": len(payload.get("ambiguities") or []),
            "timingMs": payload.get("timingMs"),
        }


class ResolverCache:
    __slots__ = ("_values", "_ttl_seconds", "_max_items")

    def __init__(self) -> None:
        self._values: dict[tuple[str, str, str], tuple[float, ResolverResult]] = {}
        self._ttl_seconds = max(settings.HEAR_RESOLVER_CACHE_TTL_MS, 0) / 1000.0
        self._max_items = max(settings.HEAR_RESOLVER_CACHE_MAX_ITEMS, 1)

    def get(self, key: tuple[str, str, str]) -> ResolverResult | None:
        cached = self._values.get(key)
        if cached is None:
            return None
        expires_at, result = cached
        if expires_at <= time.monotonic():
            self._values.pop(key, None)
            return None
        return result

    def put(self, key: tuple[str, str, str], result: ResolverResult) -> None:
        if self._ttl_seconds <= 0:
            return
        if len(self._values) >= self._max_items:
            oldest = min(self._values, key=lambda item: self._values[item][0])
            self._values.pop(oldest, None)
        self._values[key] = (time.monotonic() + self._ttl_seconds, result)


@dataclass(frozen=True, slots=True)
class ResolverOptions:
    api_key: str
    host: str | None = None
    default_country: str | None = None
    timezone: str | None = None
    timeout_ms: int | None = None
    transport: httpx.AsyncBaseTransport | None = None


class ResolverClient:
    __slots__ = (
        "_host",
        "_api_key",
        "_default_country",
        "_timezone",
        "_timeout",
        "_pool",
        "_transport",
        "_cache",
    )

    def __init__(self, options: ResolverOptions, *, pool: HttpPool | None = None) -> None:
        resolved_timeout = (
            options.timeout_ms
            if options.timeout_ms is not None
            else settings.HEAR_RESOLVER_TIMEOUT_MS
        )
        self._host = (options.host or settings.HEAR_RESOLVER_URL).rstrip("/")
        self._api_key = options.api_key
        self._default_country = options.default_country or settings.HEAR_RESOLVER_DEFAULT_COUNTRY
        self._timezone = options.timezone or settings.HEAR_RESOLVER_TIMEZONE
        self._timeout = httpx.Timeout(max(resolved_timeout, 1) / 1000.0)
        self._transport = options.transport
        self._pool = pool or HttpPool(timeout_ms=resolved_timeout)
        self._cache = ResolverCache()

    async def resolve(
        self,
        utterance: str,
        *,
        alexa_user_id: str | None = None,
        timezone: str | None = None,
        country_code: str | None = None,
        timeout_ms: int | None = None,
    ) -> ResolverResult:
        cache_key = (
            str(utterance or "").strip().casefold(),
            timezone or self._timezone,
            country_code or self._default_country,
        )
        if not alexa_user_id:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        body: dict[str, Any] = {
            "utterance": utterance,
            "timezone": timezone or self._timezone,
            "country_code": country_code or self._default_country,
        }
        if alexa_user_id:
            body["alexaUserId"] = alexa_user_id
        logged_body = {
            **body,
            **({"alexaUserId": "<present>"} if alexa_user_id else {}),
        }
        ResolverClientSupport.logger.info(
            "Hear: resolver request payload=%s",
            json.dumps(logged_body, sort_keys=True, separators=(",", ":")),
        )
        try:
            timeout = httpx.Timeout(max(timeout_ms or int(self._timeout.read * 1000), 1) / 1000.0)
            if self._transport is not None:
                async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
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
                    timeout=timeout,
                )
            if not 200 <= response.status_code < 300:
                raise ResolverUnavailable(f"resolver returned HTTP {response.status_code}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise ResolverUnavailable("resolver response must be an object")
            ResolverClientSupport.logger.info(
                "Hear: resolver response httpStatus=%s payload=%s",
                response.status_code,
                json.dumps(
                    ResolverClientSupport._resolver_response_log(payload),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            result = ResolverResult.from_payload(payload)
            if not alexa_user_id:
                self._cache.put(cache_key, result)
            return result
        except ResolverUnavailable as exc:
            ResolverClientSupport.logger.warning("Resolver response rejected reason=%s", exc)
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            ResolverClientSupport.logger.warning(
                "Resolver request failed error=%s traceback=%s",
                type(exc).__name__,
                traceback.format_exc(),
            )
            raise ResolverUnavailable("resolver request failed") from exc

    async def resolve_utterance(
        self,
        utterance: str,
        *,
        alexa_user_id: str | None = None,
        prefer_location: bool = False,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        result = await self.resolve(utterance, alexa_user_id=alexa_user_id, timeout_ms=timeout_ms)
        payload = result.to_alexa_payload(
            prefer_location=prefer_location,
            original_utterance=utterance,
        )
        ResolverClientSupport.logger.info(
            "Hear: resolver normalized response status=%s intent=%s slots=%s",
            payload.get("status"),
            payload.get("intent"),
            json.dumps(payload.get("slots") or {}, sort_keys=True, separators=(",", ":")),
        )
        return payload
