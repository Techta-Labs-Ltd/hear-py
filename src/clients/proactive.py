from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime, timedelta

from config import settings
from src.clients.pool import HttpPool
from src.constants.notifications import NotificationConstants


class ProactiveEventPayload:
    __slots__ = ()

    @staticmethod
    def iso_time(value: int | float | None = None) -> str:
        timestamp = float(value) if value else time.time()
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=UTC).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    @staticmethod
    def reference_id(notification_id: str) -> str:
        return hashlib.sha256(notification_id.encode("utf-8")).hexdigest()

    @staticmethod
    def provider(item: dict) -> str:
        return str(
            item.get("organizationName")
            or item.get("creatorName")
            or NotificationConstants.DEFAULT_PROVIDER
        ).strip()[:100]

    @staticmethod
    def title(item: dict) -> str:
        fallback = (
            "A new publication"
            if item.get("notificationType") == NotificationConstants.PUBLICATION
            else "A new recording"
        )
        return str(item.get("title") or fallback).strip()[:200]

    @staticmethod
    def build(item: dict) -> dict:
        now = datetime.now(tz=UTC).replace(microsecond=0)
        provider = ProactiveEventPayload.provider(item)
        title = ProactiveEventPayload.title(item)
        locale = str(item.get("locale") or NotificationConstants.DEFAULT_LOCALE)
        return {
            "timestamp": now.isoformat().replace("+00:00", "Z"),
            "referenceId": ProactiveEventPayload.reference_id(item["notificationId"]),
            "expiryTime": (now + timedelta(hours=NotificationConstants.DELIVERY_EXPIRY_HOURS))
            .isoformat()
            .replace("+00:00", "Z"),
            "event": {
                "name": NotificationConstants.EVENT_NAME,
                "payload": {
                    "availability": {
                        "startTime": ProactiveEventPayload.iso_time(item.get("publishedAt")),
                        "provider": {"name": "localizedattribute:providerName"},
                        "method": "STREAM",
                    },
                    "content": {
                        "name": "localizedattribute:contentName",
                        "contentType": "EPISODE",
                    },
                },
            },
            "localizedAttributes": [
                {
                    "locale": locale,
                    "providerName": provider,
                    "contentName": title,
                }
            ],
            "relevantAudience": {
                "type": "Unicast",
                "payload": {"user": item["alexaUserId"]},
            },
        }


class ProactiveEventsClient:
    __slots__ = (
        "_client_id",
        "_client_secret",
        "_endpoint",
        "_pool",
        "_token",
        "_token_expires_at",
        "_token_lock",
    )

    def __init__(
        self,
        *,
        client_id: str = "",
        client_secret: str = "",
        stage: str = "development",
        pool: HttpPool | None = None,
    ) -> None:
        self._client_id = str(client_id or "").strip()
        self._client_secret = str(client_secret or "").strip()
        self._endpoint = (
            NotificationConstants.PRODUCTION_ENDPOINT
            if str(stage or "").strip().casefold() == "production"
            else NotificationConstants.DEVELOPMENT_ENDPOINT
        )
        self._pool = pool or HttpPool(timeout_ms=settings.HEAR_PROACTIVE_TIMEOUT_MS)
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def _access_token(self) -> dict:
        if self._token and time.monotonic() < self._token_expires_at:
            return {"token": self._token}
        async with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return {"token": self._token}
            try:
                response = await self._pool.get().post(
                    NotificationConstants.LWA_TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "scope": NotificationConstants.LWA_SCOPE,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except Exception as exc:
                return {
                    "errorCode": type(exc).__name__,
                    "retryable": True,
                    "httpStatus": None,
                }
            if response.status_code != 200:
                return {
                    "errorCode": "lwa_token_rejected",
                    "retryable": response.status_code >= 500 or response.status_code == 429,
                    "httpStatus": response.status_code,
                }
            body = response.json()
            token = str(body.get("access_token") or "").strip()
            if not token:
                return {
                    "errorCode": "lwa_token_missing",
                    "retryable": False,
                    "httpStatus": 200,
                }
            expires_in = max(60, int(body.get("expires_in") or 3600))
            self._token = token
            self._token_expires_at = time.monotonic() + max(30, expires_in - 60)
            return {"token": token}

    async def deliver(self, item: dict) -> dict:
        if not self.enabled:
            return {"sent": False, "retryable": False, "errorCode": "not_configured"}
        if not item.get("alexaUserId"):
            return {"sent": False, "retryable": False, "errorCode": "missing_recipient"}
        token_result = await self._access_token()
        token = token_result.get("token")
        if not token:
            return {"sent": False, **token_result}
        try:
            response = await self._pool.get().post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=ProactiveEventPayload.build(item),
            )
        except Exception as exc:
            return {
                "sent": False,
                "retryable": True,
                "errorCode": type(exc).__name__,
                "httpStatus": None,
            }
        status = int(response.status_code)
        if status == 202:
            return {"sent": True, "retryable": False, "httpStatus": status}
        error_code = "proactive_event_rejected"
        try:
            error_code = str((response.json() or {}).get("code") or error_code)
        except Exception:
            pass
        return {
            "sent": False,
            "retryable": status in NotificationConstants.DELIVERY_RETRYABLE_STATUSES,
            "httpStatus": status,
            "errorCode": error_code,
        }
