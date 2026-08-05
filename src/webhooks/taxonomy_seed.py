from __future__ import annotations

import hashlib
import json
import logging
import urllib.request

from config import settings
from src.services.taxonomy_updates import queue_taxonomy_snapshot

logger = logging.getLogger(__name__)


def _send_cloudformation_response(
    event: dict, context, status: str, reason: str,
) -> None:
    response_url = event.get("ResponseURL")
    if not response_url:
        return
    body = json.dumps({
        "Status": status,
        "Reason": reason,
        "PhysicalResourceId": "hear-runtime-taxonomy-manifest-bootstrap-v2",
        "StackId": event.get("StackId"),
        "RequestId": event.get("RequestId"),
        "LogicalResourceId": event.get("LogicalResourceId"),
        "NoEcho": False,
        "Data": {},
    }).encode("utf-8")
    request = urllib.request.Request(
        response_url,
        data=body,
        method="PUT",
        headers={"Content-Type": "", "Content-Length": str(len(body))},
    )
    with urllib.request.urlopen(request, timeout=10):
        pass


def _read_manifest(manifest_url: str) -> tuple[int, str]:
    """Fetch and validate the exact manifest bytes used for activation."""
    request = urllib.request.Request(
        manifest_url,
        headers={"Accept": "application/json", "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        content = response.read(1024 * 1024 + 1)
    if not content or len(content) > 1024 * 1024:
        raise ValueError("Taxonomy manifest is empty or exceeds 1 MB")
    manifest = json.loads(content)
    revision = int(manifest.get("currentRevision") or 0)
    snapshot_revision = int(manifest.get("snapshotRevision") or 0)
    if (
        int(manifest.get("schemaVersion") or 0) != 2
        or revision <= 0
        or snapshot_revision != revision
        or not isinstance(manifest.get("routing"), dict)
        or not isinstance(manifest.get("shards"), dict)
    ):
        raise ValueError("Manifest must be a complete schema-v2 SQLite snapshot")
    return revision, hashlib.sha256(content).hexdigest()


def bootstrap_manifest(manifest_url: str) -> int:
    revision, manifest_sha256 = _read_manifest(manifest_url)
    queue_taxonomy_snapshot(revision, manifest_url, manifest_sha256)
    return revision


def handler(event: dict, context=None) -> None:
    try:
        if event.get("RequestType") != "Delete":
            properties = event.get("ResourceProperties") or {}
            manifest_url = str(
                properties.get("ManifestUrl")
                or settings.HEAR_TAXONOMY_MANIFEST_URL
            ).strip()
            if not manifest_url.startswith("https://"):
                raise ValueError("An HTTPS manifest URL is required")
            revision = bootstrap_manifest(manifest_url)
            reason = f"queued taxonomy snapshot revision {revision}"
        else:
            reason = "complete"
        _send_cloudformation_response(event, context, "SUCCESS", reason)
    except Exception as exc:
        logger.exception("Taxonomy manifest bootstrap failed")
        _send_cloudformation_response(event, context, "FAILED", str(exc))
