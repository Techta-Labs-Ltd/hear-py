from __future__ import annotations

from config import settings


def verify_secret(event: dict) -> dict | None:
    """Verify the webhook secret header; returns a 401 response dict if invalid."""
    headers = event.get("headers") or {}
    secret = headers.get("x-webhook-secret") or headers.get("X-Webhook-Secret") or None
    if not secret or secret != settings.WEBHOOK_SECRET:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": '{"error":"Unauthorised"}',
        }
    return None
