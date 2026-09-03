from __future__ import annotations

import logging
import time
from dataclasses import replace

import config.permission_scopes as permission_scopes
from config import settings
from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.runtime import AlexaMetrics
from src.clients.alexa_settings import AlexaSettingsClient
from src.clients.hear import HearApiClient
from src.models.listener import IdentityContext
from src.utils.deadline import DeadlineBudget


class ListenerIdentitySupport:
    logger = logging.getLogger(__name__)

    @staticmethod
    def normalize_email(value: object) -> str | None:
        email = str(value or "").strip().casefold()
        return email if "@" in email and not email.startswith("@") else None


class ListenerIdentityService:
    __slots__ = (
        "_hear_api",
        "_settings",
        "_enabled",
        "_timeout_ms",
        "_cache",
        "_ttl_seconds",
        "_max_items",
    )

    def __init__(
        self,
        hear_api: HearApiClient,
        settings_client: AlexaSettingsClient | None = None,
        *,
        enabled: bool = True,
        timeout_ms: int | None = None,
    ) -> None:
        self._hear_api = hear_api
        self._settings = settings_client
        self._enabled = enabled
        self._timeout_ms = max(timeout_ms or settings.identity_timeout_ms, 100)
        self._cache: dict[tuple[str, str, str, str], tuple[float, str]] = {}
        self._ttl_seconds = max(settings.HEAR_IDENTITY_CACHE_TTL_MS, 0) / 1000.0
        self._max_items = max(settings.HEAR_IDENTITY_CACHE_MAX_ITEMS, 1)

    @staticmethod
    def _cache_key(identity: IdentityContext) -> tuple[str, str, str, str]:
        return (
            identity.alexa_user_id or "",
            identity.person_id or "",
            identity.skill_id or "",
            settings.STAGE,
        )

    def _cached(self, identity: IdentityContext) -> str | None:
        cached = self._cache.get(self._cache_key(identity))
        if cached is None:
            return None
        expires_at, listener_id = cached
        if expires_at <= time.monotonic():
            self._cache.pop(self._cache_key(identity), None)
            return None
        return listener_id

    def _remember(self, identity: IdentityContext, listener_id: str) -> None:
        if self._ttl_seconds <= 0:
            return
        if len(self._cache) >= self._max_items:
            oldest = min(self._cache, key=lambda key: self._cache[key][0])
            self._cache.pop(oldest, None)
        self._cache[self._cache_key(identity)] = (
            time.monotonic() + self._ttl_seconds,
            listener_id,
        )

    async def _with_profile_email(
        self, handler_input, identity: IdentityContext
    ) -> IdentityContext:
        if self._settings is None or not RequestContext.has_permission(
            handler_input, permission_scopes.PROFILE_EMAIL_READ
        ):
            return identity
        try:
            result = await self._settings.get_profile_setting(
                handler_input,
                "Profile.email",
                label="Profile.email",
            )
        except Exception as exc:
            ListenerIdentitySupport.logger.warning(
                "Hear: identity email lookup failed error=%s",
                type(exc).__name__,
            )
            return identity
        email = ListenerIdentitySupport.normalize_email((result or {}).get("value"))
        if not email:
            return identity
        AlexaMetrics.increment("CanonicalIdentityEmailAvailable")
        return replace(identity, user_email=email)

    async def resolve(self, handler_input, identity: IdentityContext) -> IdentityContext:
        if (
            not self._enabled
            or not identity.alexa_user_id
            or AlexaRequest.get_request_type(handler_input) == "CanFulfillIntentRequest"
        ):
            return identity
        cached = self._cached(identity)
        if cached:
            AlexaMetrics.increment("CanonicalIdentityCacheHit")
            return replace(identity, listener_id=cached)
        identity = await self._with_profile_email(handler_input, identity)
        remaining_ms = DeadlineBudget.get_lambda_remaining_ms(handler_input)
        timeout_ms = self._timeout_ms
        if isinstance(remaining_ms, (int, float)) and remaining_ms > 0:
            timeout_ms = min(timeout_ms, max(int(remaining_ms) - 500, 100))
        result = await self._hear_api.resolve_listener_identity(
            identity.resolution_payload(),
            timeout_ms=timeout_ms,
        )
        listener_id = str((result or {}).get("listenerId") or "").strip()
        if not listener_id:
            AlexaMetrics.increment("CanonicalIdentityFallback")
            ListenerIdentitySupport.logger.warning(
                "Hear: canonical listener resolution unavailable fallback=alexa_alias"
            )
            return identity
        self._remember(identity, listener_id)
        AlexaMetrics.increment("CanonicalIdentityResolved")
        ListenerIdentitySupport.logger.info(
            "Hear: canonical listener resolved principalType=%s",
            identity.principal_type.value,
        )
        return replace(identity, listener_id=listener_id)
