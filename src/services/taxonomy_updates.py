"""Record taxonomy update events without performing NLP work."""
from __future__ import annotations

import json
import logging

import boto3

from config import settings

logger = logging.getLogger(__name__)


def _response(status: int, payload: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, separators=(",", ":")),
    }


def _store_revision(revision: str, manifest_url: str) -> None:
    if not settings.HEAR_TAXONOMY_REVISION_TABLE:
        return
    table = boto3.resource("dynamodb", region_name=settings.ddb_region).Table(
        settings.HEAR_TAXONOMY_REVISION_TABLE
    )
    table.put_item(Item={
        "pk": "taxonomy#current",
        "revision": revision,
        "manifestUrl": manifest_url,
    })


async def handle_taxonomy_webhook(event: dict) -> dict:
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON"})
    if payload.get("event") != "taxonomy.updated":
        return _response(400, {"error": "Unsupported event"})
    revision = str(payload.get("revision") or "").strip()
    manifest_url = str(
        payload.get("manifestUrl") or settings.HEAR_TAXONOMY_MANIFEST_URL
    ).strip()
    if not revision or not manifest_url:
        return _response(400, {"error": "revision and manifestUrl are required"})
    try:
        _store_revision(revision, manifest_url)
    except Exception:
        logger.exception("Could not persist taxonomy revision")
        return _response(503, {"error": "Revision store unavailable"})
    return _response(202, {"ok": True, "revision": revision})
