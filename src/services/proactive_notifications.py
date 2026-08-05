from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import httpx

from config import settings

_token: str | None = None
_token_expires_at = 0.0
_token_lock = asyncio.Lock()


async def _access_token(client: httpx.AsyncClient | None = None) -> str | None:
    global _token, _token_expires_at
    if not settings.ALEXA_PROACTIVE_CLIENT_ID or not settings.ALEXA_PROACTIVE_CLIENT_SECRET:
        return None
    if _token and time.time() < _token_expires_at - 60:
        return _token
    async with _token_lock:
        if _token and time.time() < _token_expires_at - 60:
            return _token
        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=10.0)
        try:
            response = await client.post(
                "https://api.amazon.com/auth/o2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.ALEXA_PROACTIVE_CLIENT_ID,
                    "client_secret": settings.ALEXA_PROACTIVE_CLIENT_SECRET,
                    "scope": "alexa::proactive_events",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                await client.aclose()
        _token = str(payload.get("access_token") or "") or None
        _token_expires_at = time.time() + int(payload.get("expires_in") or 3600)
        return _token


def _endpoint() -> str:
    stage = "development" if settings.ALEXA_PROACTIVE_STAGE.lower() != "production" else None
    base = "https://api.eu.amazonalexa.com/v1/proactiveEvents"
    return f"{base}/stages/{stage}" if stage else f"{base}/"


async def send_proactive_notification(
    item: dict,
    client: httpx.AsyncClient | None = None,
) -> bool:
    token = await _access_token(client)
    if not token:
        return False
    now = datetime.now(timezone.utc)
    creator = str(item.get("creatorName") or "Hear").strip()[:100]
    body = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "referenceId": str(item["notificationId"]).replace(":", "~")[:100],
        "expiryTime": (now + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        "event": {
            "name": "AMAZON.MessageAlert.Activated",
            "payload": {
                "state": {"status": "UNREAD", "freshness": "NEW"},
                "messageGroup": {
                    "creator": {"name": creator},
                    "count": 1,
                },
            },
        },
        "localizedAttributes": [],
        "relevantAudience": {
            "type": "Unicast",
            "payload": {"user": item["alexaUserId"]},
        },
    }
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.post(
            _endpoint(),
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        if owns_client:
            await client.aclose()
    if response.status_code == 202:
        return True
    response.raise_for_status()
    return False
