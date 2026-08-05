"""Record taxonomy update events without performing NLP work."""
from __future__ import annotations

import json
import logging
import time

import boto3

from config import settings

logger = logging.getLogger(__name__)


def _response(status: int, payload: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, separators=(",", ":")),
    }


def _store_revision(revision: int, manifest_url: str, manifest_sha256: str) -> None:
    if not settings.HEAR_TAXONOMY_REVISION_TABLE:
        return
    table = boto3.resource("dynamodb", region_name=settings.ddb_region).Table(
        settings.HEAR_TAXONOMY_REVISION_TABLE
    )
    table.put_item(Item={
        "pk": f"taxonomy#revision#{revision}",
        "revision": revision,
        "manifestUrl": manifest_url,
        "manifestSha256": manifest_sha256,
        "status": "pending",
        "updatedAt": int(time.time()),
    })


def _enqueue_refresh(revision: int, manifest_url: str, manifest_sha256: str) -> None:
    if not settings.HEAR_TAXONOMY_REFRESH_QUEUE_URL:
        raise RuntimeError("Taxonomy refresh queue is not configured")
    boto3.client("sqs", region_name=settings.ddb_region).send_message(
        QueueUrl=settings.HEAR_TAXONOMY_REFRESH_QUEUE_URL,
        MessageBody=json.dumps({
            "revision": revision,
            "manifestUrl": manifest_url,
            "manifestSha256": manifest_sha256,
        }, separators=(",", ":")),
        MessageGroupId="taxonomy-refresh",
        MessageDeduplicationId=f"{revision}:{manifest_sha256}",
    )


def queue_taxonomy_snapshot(
    revision: int, manifest_url: str, manifest_sha256: str,
) -> None:
    """Persist and enqueue one validated snapshot publication."""
    _store_revision(revision, manifest_url, manifest_sha256)
    _enqueue_refresh(revision, manifest_url, manifest_sha256)


async def handle_taxonomy_webhook(event: dict) -> dict:
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON"})
    if payload.get("event") != "taxonomy.snapshot.published":
        return _response(400, {"error": "Unsupported event"})
    try:
        revision = int(payload.get("revision") or 0)
    except (TypeError, ValueError):
        revision = 0
    manifest_url = str(
        payload.get("manifestUrl") or settings.HEAR_TAXONOMY_MANIFEST_URL
    ).strip()
    manifest_sha256 = str(payload.get("manifestSha256") or "").strip().lower()
    if (
        revision <= 0
        or not manifest_url.startswith("https://")
        or len(manifest_sha256) != 64
        or any(character not in "0123456789abcdef" for character in manifest_sha256)
    ):
        return _response(400, {"error": "revision, immutable manifestUrl and manifestSha256 are required"})
    try:
        queue_taxonomy_snapshot(revision, manifest_url, manifest_sha256)
    except Exception:
        logger.exception("Could not persist taxonomy revision")
        return _response(503, {"error": "Taxonomy refresh unavailable"})
    return _response(202, {"ok": True, "revision": revision})
