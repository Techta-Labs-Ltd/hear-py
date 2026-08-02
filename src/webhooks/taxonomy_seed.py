from __future__ import annotations

import json
import logging
import urllib.request

import boto3

from config import settings

logger = logging.getLogger(__name__)


def _send_cloudformation_response(event: dict, context, status: str, reason: str) -> None:
    response_url = event.get("ResponseURL")
    if not response_url:
        return
    body = json.dumps({
        "Status": status,
        "Reason": reason,
        "PhysicalResourceId": "hear-runtime-taxonomy-v1",
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


def _seed_revision(revision: str, manifest_url: str) -> None:
    table = boto3.resource("dynamodb", region_name=settings.ddb_region).Table(
        settings.HEAR_TAXONOMY_REVISION_TABLE
    )
    try:
        table.put_item(
            Item={
                "pk": "taxonomy#current",
                "revision": revision,
                "manifestUrl": manifest_url,
                "status": "active",
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") != (
            "ConditionalCheckFailedException"
        ):
            raise


def handler(event: dict, context=None) -> None:
    try:
        if event.get("RequestType") != "Delete":
            properties = event.get("ResourceProperties") or {}
            revision = str(properties.get("Revision") or "v1").strip()
            manifest_url = str(
                properties.get("ManifestUrl")
                or settings.HEAR_TAXONOMY_MANIFEST_URL
            ).strip()
            if not revision or not manifest_url:
                raise ValueError("Revision and ManifestUrl are required")
            _seed_revision(revision, manifest_url)
        _send_cloudformation_response(event, context, "SUCCESS", "complete")
    except Exception as exc:
        logger.exception("Taxonomy revision bootstrap failed")
        _send_cloudformation_response(event, context, "FAILED", str(exc))

