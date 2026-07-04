from __future__ import annotations

import json
import time

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
    parsed = json.loads(body) if isinstance(body, str) else body

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
        pass

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
