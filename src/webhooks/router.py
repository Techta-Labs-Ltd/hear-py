"""HTTP event normalization and webhook routing."""
from __future__ import annotations

import base64
import json
import logging

from config import settings
from src.services.notifications import handle_notification_webhook
from src.services.settings import handle_settings_webhook
from src.services.taxonomy_updates import handle_taxonomy_webhook

logger = logging.getLogger(__name__)

_ROUTES = {
    "/webhook/settings": handle_settings_webhook,
    "/webhook/notification": handle_notification_webhook,
    "/webhook/taxonomy": handle_taxonomy_webhook,
}


def _verify_secret(event: dict) -> dict | None:
    headers = event.get("headers") or {}
    supplied = headers.get("x-webhook-secret") or headers.get("X-Webhook-Secret")
    if supplied and supplied == settings.WEBHOOK_SECRET:
        return None
    return _response(401, {"error": "Unauthorised"})


def is_http_event(event: dict) -> bool:
    request_context = event.get("requestContext") or {}
    return bool(request_context.get("http") or event.get("httpMethod"))


def normalize_http_event(event: dict) -> dict:
    """Normalize API Gateway v1 and v2 payloads to the v1 shape."""
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    return {
        "httpMethod": http.get("method") or event.get("httpMethod"),
        "path": http.get("path") or event.get("rawPath") or event.get("path") or "",
        "headers": event.get("headers") or {},
        "body": body,
    }


def _response(status_code: int, payload: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, separators=(",", ":")),
    }


async def route_webhook(event: dict) -> dict:
    """Authenticate and dispatch a normalized webhook request."""
    try:
        auth_response = _verify_secret(event)
        if auth_response:
            return auth_response
        route = _ROUTES.get(event.get("path") or "")
        if route is None:
            return _response(404, {"error": "Not found"})
        return await route(event)
    except Exception:
        logger.exception("Webhook routing failed")
        return _response(500, {"error": "Internal error"})
