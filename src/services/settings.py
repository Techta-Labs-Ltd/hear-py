"""Global settings service and inbound update endpoint."""
from __future__ import annotations

import json
import time
from urllib.parse import urlparse

import boto3

from config import settings

_cached_settings: dict | None = None
_doc_client = None


def _get_doc_client():
    """Return a cached DynamoDB resource client."""
    global _doc_client
    if _doc_client is not None:
        return _doc_client
    region = settings.HEAR_DDB_REGION or settings.AWS_REGION or "eu-west-1"
    _doc_client = boto3.resource("dynamodb", region_name=region)
    return _doc_client


async def get_settings() -> dict:
    """Fetch and cache global settings from the DynamoDB settings table."""
    global _cached_settings
    if _cached_settings is not None:
        return _cached_settings

    table_name = settings.SETTINGS_TABLE or "hear_settings"
    try:
        client = _get_doc_client()
        table = client.Table(table_name)
        resp = table.get_item(Key={"pk": "global"})
        item = resp.get("Item")
        if item:
            _cached_settings = {
                "autoPlay": item.get("autoPlay") is not False,
                "outroEnabled": bool(item.get("outroEnabled")),
                "outroUrl": item.get("outroUrl") or None,
                "outroUrlFinal": item.get("outroUrlFinal") or None,
                "feedbackEnabled": item.get("feedbackEnabled") is not False,
            }
        else:
            _cached_settings = _default_settings()
    except Exception:
        _cached_settings = _default_settings()

    return _cached_settings


def invalidate_settings():
    """Invalidate the cached settings so the next read fetches from the table."""
    global _cached_settings
    _cached_settings = None


async def handle_settings_webhook(event: dict) -> dict:
    """Handle an incoming settings webhook by writing to DynamoDB."""
    body = event.get("body")
    try:
        parsed = json.loads(body) if isinstance(body, str) else body
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if not isinstance(parsed, dict):
        return {"statusCode": 400, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "Body must be a JSON object"})}
    allowed = {"autoPlay", "outroEnabled", "outroUrl", "outroUrlFinal", "feedbackEnabled"}
    unknown = sorted(set(parsed) - allowed)
    if unknown:
        return {"statusCode": 400, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "Unknown settings fields", "fields": unknown})}
    for field in ("outroUrl", "outroUrlFinal"):
        value = parsed.get(field)
        if value:
            parsed_url = urlparse(str(value))
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                return {"statusCode": 400, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": f"{field} must be an HTTPS URL"})}

    table_name = settings.SETTINGS_TABLE or "hear_settings"
    item = {
        "pk": "global",
        "autoPlay": parsed.get("autoPlay") is not False,
        "outroEnabled": bool(parsed.get("outroEnabled")),
        "outroUrl": parsed.get("outroUrl") or None,
        "outroUrlFinal": parsed.get("outroUrlFinal") or None,
        "feedbackEnabled": parsed.get("feedbackEnabled") is not False,
        "updatedAt": int(time.time()),
    }

    try:
        client = _get_doc_client()
        table = client.Table(table_name)
        table.put_item(Item=item)
    except Exception:
        return {"statusCode": 503, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "Settings store unavailable"})}

    invalidate_settings()

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"status": "ok"}),
    }


def _default_settings() -> dict:
    """Return default settings when the table is unavailable."""
    return {
        "autoPlay": True,
        "outroEnabled": False,
        "outroUrl": None,
        "outroUrlFinal": None,
        "feedbackEnabled": False,
    }
