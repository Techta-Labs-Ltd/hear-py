from __future__ import annotations

import json
from src.services.logging_control import ApplicationLog
import time
import traceback
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import httpx

from config import settings
from src.clients.pool import HttpPool
from src.models.resolver import ResolverResult, ResolverUnavailable


class ResolverClientSupport:
    logger = ApplicationLog

    @staticmethod
    def _resolver_response_log(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": payload.get("status"),
            "intent": payload.get("intent"),
            "entityCount": len(payload.get("entities") or []),
            "slotKeys": sorted((payload.get("slots") or {}).keys()),
            "ambiguityCount": len(payload.get("ambiguities") or []),
            "timingMs": payload.get("timingMs"),
        }

    @staticmethod
    def request_body(
        utterance: str,
        timezone: str,
        country_code: str,
        alexa_user_id: str | None,
        listener_id: str | None,
    ) -> dict[str, Any]:
        body = {
            "utterance": utterance,
            "timezone": timezone,
            "country_code": country_code,
        }
        if alexa_user_id:
            body["alexaUserId"] = alexa_user_id
        if listener_id:
            body["listenerId"] = listener_id
        return body

    @staticmethod
    def request_log(body: dict, alexa_user_id: str | None, listener_id: str | None) -> dict:
        return {
            "utteranceChars": len(str(body.get("utterance") or "")),
            "timezone": body.get("timezone"),
            "country_code": body.get("country_code"),
            **({"alexaUserId": "<present>"} if alexa_user_id else {}),
            **({"listenerId": "<present>"} if listener_id else {}),
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
        return deepcopy(result)

    def put(self, key: tuple[str, str, str], result: ResolverResult) -> None:
        if self._ttl_seconds <= 0:
            return
        if len(self._values) >= self._max_items:
            oldest = min(self._values, key=lambda item: self._values[item][0])
            self._values.pop(oldest, None)
        self._values[key] = (time.monotonic() + self._ttl_seconds, deepcopy(result))


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
        self._pool = (
            pool
            if pool is not None
            else HttpPool(
                base_url=self._host,
                headers={"X-Api-Key": self._api_key},
                timeout_ms=resolved_timeout,
            )
        )
        self._pool.assert_configuration(base_url=self._host, headers={"X-Api-Key": self._api_key})
        self._cache = ResolverCache()

    async def resolve(
        self,
        utterance: str,
        *,
        alexa_user_id: str | None = None,
        listener_id: str | None = None,
        timezone: str | None = None,
        country_code: str | None = None,
        timeout_ms: int | None = None,
    ) -> ResolverResult:
        cache_key = (
            str(utterance or "").strip().casefold(),
            timezone or self._timezone,
            country_code or self._default_country,
        )
        cache_eligible = not (alexa_user_id or listener_id)
        if cache_eligible:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        body = ResolverClientSupport.request_body(
            utterance,
            timezone or self._timezone,
            country_code or self._default_country,
            alexa_user_id,
            listener_id,
        )
        logged_body = ResolverClientSupport.request_log(body, alexa_user_id, listener_id)
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
                    "/resolve",
                    json=body,
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
            if cache_eligible and result.status == "resolved":
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
        listener_id: str | None = None,
        prefer_location: bool = False,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        result = await self.resolve(
            utterance,
            alexa_user_id=alexa_user_id,
            listener_id=listener_id,
            timeout_ms=timeout_ms,
        )
        payload = result.to_alexa_payload(
            prefer_location=prefer_location,
            original_utterance=utterance,
        )
        ResolverClientSupport.logger.info(
            "Hear: resolver normalized response status=%s intent=%s slotKeys=%s",
            payload.get("status"),
            payload.get("intent"),
            sorted((payload.get("slots") or {}).keys()),
        )
        return payload
