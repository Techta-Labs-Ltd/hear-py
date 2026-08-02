import json

import pytest

from src.utils.webhook_signing import signed_webhook_headers
from src.webhooks import router


@pytest.mark.asyncio
async def test_inbound_webhook_requires_valid_api_key_and_hmac(monkeypatch):
    body = json.dumps({"value": 1})
    monkeypatch.setattr(router.settings, "WEBHOOK_ALLOW_LEGACY_SECRET", False)
    monkeypatch.setattr(router.settings, "HEAR_API_KEY", "api-key")
    monkeypatch.setattr(router.settings, "WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setattr(router.settings, "WEBHOOK_REPLAY_TABLE", "")
    headers = signed_webhook_headers(body, "webhook-secret", "api-key")

    accepted = await router.route_webhook({
        "path": "/unknown",
        "headers": headers,
        "body": body,
    })
    rejected = await router.route_webhook({
        "path": "/unknown",
        "headers": {**headers, "X-Api-Key": "wrong"},
        "body": body,
    })

    assert accepted["statusCode"] == 404
    assert rejected["statusCode"] == 401


@pytest.mark.asyncio
async def test_legacy_secret_can_only_be_enabled_explicitly(monkeypatch):
    monkeypatch.setattr(router.settings, "WEBHOOK_ALLOW_LEGACY_SECRET", True)
    monkeypatch.setattr(router.settings, "WEBHOOK_SECRET", "legacy-secret")

    response = await router.route_webhook({
        "path": "/unknown",
        "headers": {"x-webhook-secret": "legacy-secret"},
        "body": "{}",
    })

    assert response["statusCode"] == 404
