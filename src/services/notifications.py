"""Per-user notification inbox and notification playback resolution."""
from __future__ import annotations

import json
import logging
import time
import uuid

import boto3
from boto3.dynamodb.conditions import Key

from config import settings
from src.services.api import search
from src.services.queue.state import create_playback_queue
from src.utils.skill_request import get_user_id
from src.utils.speech import (
    NOTIFICATIONS_MULTI_CREATOR,
    NOTIFICATIONS_SINGLE_CREATOR,
    NOTIFICATIONS_SINGLE_TRACK,
)

logger = logging.getLogger(__name__)
PENDING_STATUSES = {"pending", "offered", "resolving", "queued"}
TERMINAL_STATUSES = {"consumed", "dismissed", "unavailable"}
_memory_inbox: dict[tuple[str, str], dict] = {}
_doc_client = None


def _get_doc_client():
    global _doc_client
    if _doc_client is None:
        region = settings.HEAR_DDB_REGION or settings.AWS_REGION or "eu-west-1"
        _doc_client = boto3.resource("dynamodb", region_name=region)
    return _doc_client


def _use_memory() -> bool:
    return settings.HEAR_PERSISTENCE_DRIVER == "memory" or not settings.NOTIFICATIONS_TABLE


def _response(status_code: int, payload: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, separators=(",", ":")),
    }


def _parse_webhook(event: dict) -> tuple[dict | None, str | None]:
    body = event.get("body")
    try:
        parsed = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError:
        return None, "Invalid JSON"
    if not isinstance(parsed, dict):
        return None, "Body must be an object"
    event_id = str(parsed.get("eventId") or "").strip()
    kind = str(parsed.get("notificationType") or "").strip().lower()
    users = parsed.get("alexaUserIds")
    content_id = str(parsed.get("contentId") or "").strip() or None
    publication_id = str(parsed.get("publicationId") or "").strip() or None
    if not event_id or kind not in {"content", "publication"}:
        return None, "eventId and a valid notificationType are required"
    if not isinstance(users, list) or not any(str(value).strip() for value in users):
        return None, "alexaUserIds must contain at least one user"
    if bool(content_id) == bool(publication_id):
        return None, "Provide exactly one of contentId or publicationId"
    if kind == "content" and not content_id:
        return None, "content notifications require contentId"
    if kind == "publication" and not publication_id:
        return None, "publication notifications require publicationId"
    return {
        "eventId": event_id,
        "notificationType": kind,
        "contentId": content_id,
        "publicationId": publication_id,
        "title": str(parsed.get("title") or "").strip() or "a new recording",
        "alexaUserIds": list(dict.fromkeys(
            str(value).strip() for value in users if str(value).strip()
        )),
        "publishedAt": int(parsed.get("publishedAt") or time.time()),
    }, None


async def _put_inbox_item(item: dict) -> None:
    key = (item["alexaUserId"], item["notificationId"])
    if _use_memory():
        _memory_inbox.setdefault(key, dict(item))
        return
    table = _get_doc_client().Table(settings.NOTIFICATIONS_TABLE)
    try:
        table.put_item(
            Item=item,
            ConditionExpression=(
                "attribute_not_exists(alexaUserId) AND "
                "attribute_not_exists(notificationId)"
            ),
        )
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") != (
            "ConditionalCheckFailedException"
        ):
            raise


async def handle_notification_webhook(event: dict) -> dict:
    """Validate and expand one backend event into per-user inbox records."""
    payload, error = _parse_webhook(event)
    if error:
        return _response(400, {"error": error})
    assert payload is not None
    now = int(time.time())
    for user_id in payload["alexaUserIds"]:
        await _put_inbox_item({
            "alexaUserId": user_id,
            "notificationId": f"{payload['eventId']}:{user_id}",
            "eventId": payload["eventId"],
            "notificationType": payload["notificationType"],
            "contentId": payload["contentId"],
            "publicationId": payload["publicationId"],
            "title": payload["title"],
            "publishedAt": payload["publishedAt"],
            "status": "pending",
            "ttl": now + 7 * 24 * 60 * 60,
        })
    return _response(200, {
        "status": "ok",
        "recipients": len(payload["alexaUserIds"]),
    })


async def check_notifications(user_id: str, limit: int = 20) -> list[dict]:
    """Return newest pending inbox records for one Alexa user."""
    if not user_id:
        return []
    if _use_memory():
        items = [
            dict(item) for (uid, _), item in _memory_inbox.items()
            if uid == user_id and item.get("status") in PENDING_STATUSES
        ]
    else:
        try:
            response = _get_doc_client().Table(settings.NOTIFICATIONS_TABLE).query(
                KeyConditionExpression=Key("alexaUserId").eq(user_id),
            )
            items = [
                item for item in response.get("Items", [])
                if item.get("status") in PENDING_STATUSES
            ]
        except Exception:
            logger.exception("Notification inbox query failed")
            return []
    items.sort(key=lambda item: int(item.get("publishedAt") or 0), reverse=True)
    return items[:max(1, min(int(limit or 20), 20))]


async def update_notification_status(
    user_id: str,
    notification_id: str,
    status: str,
) -> None:
    if not user_id or not notification_id or status not in PENDING_STATUSES | TERMINAL_STATUSES:
        return
    key = (user_id, notification_id)
    if _use_memory():
        if key in _memory_inbox:
            _memory_inbox[key]["status"] = status
        return
    try:
        _get_doc_client().Table(settings.NOTIFICATIONS_TABLE).update_item(
            Key={"alexaUserId": user_id, "notificationId": notification_id},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": status},
        )
    except Exception:
        logger.exception("Notification status update failed status=%s", status)


async def consume_notification_for_content(user_id: str, content_id: str) -> None:
    """Consume queued inbox records only after PlaybackStarted."""
    for item in await check_notifications(user_id):
        if item.get("contentId") == content_id and item.get("status") == "queued":
            await update_notification_status(
                user_id, item["notificationId"], "consumed",
            )


async def consume_notification_for_playback(
    user_id: str,
    content_id: str,
    publication_id: str | None = None,
) -> None:
    """Consume the queued content or publication notification that started."""
    for item in await check_notifications(user_id):
        matches = item.get("contentId") == content_id or (
            publication_id
            and item.get("publicationId") == publication_id
        )
        if matches and item.get("status") == "queued":
            await update_notification_status(
                user_id, item["notificationId"], "consumed",
            )


async def reset_notification_for_content(user_id: str, content_id: str) -> None:
    """Return queued notification content to pending when audio never starts."""
    for item in await check_notifications(user_id):
        if item.get("contentId") == content_id and item.get("status") == "queued":
            await update_notification_status(
                user_id, item["notificationId"], "pending",
            )


async def resolve_notification_queue(handler_input, notifications: list[dict]) -> dict:
    """Resolve pending notification references through catalog search."""
    user_id = get_user_id(handler_input)
    pending = list(notifications or [])[:20]
    content_items = [item for item in pending if item.get("contentId")]
    publication_items = [item for item in pending if item.get("publicationId")]
    selected = content_items or publication_items[:1]
    if not selected:
        return {"results": [], "failed": False}
    for item in selected:
        await update_notification_status(
            item.get("alexaUserId") or user_id,
            item["notificationId"],
            "resolving",
        )
    filter_value = (
        {"contentIds": [item["contentId"] for item in selected]}
        if content_items
        else {"publicationIds": [selected[0]["publicationId"]]}
    )
    result = await search({
        "query": "",
        "filter": filter_value,
        "page": 0,
        "limit": 20,
        "alexaUserId": user_id,
    })
    if result.get("failed"):
        for item in selected:
            await update_notification_status(
                item.get("alexaUserId") or user_id,
                item["notificationId"],
                "pending",
            )
        return result
    by_id = {
        item["contentId"]: item for item in result.get("results", [])
        if item.get("contentId")
    }
    if content_items:
        ordered = [by_id[item["contentId"]] for item in selected if item["contentId"] in by_id]
        for item in selected:
            status = "queued" if item["contentId"] in by_id else "unavailable"
            await update_notification_status(
                item.get("alexaUserId") or user_id,
                item["notificationId"],
                status,
            )
        publication_id = None
        publication_title = None
        source = "content_notifications"
    else:
        ordered = list(result.get("results", []))
        status = "queued" if ordered else "unavailable"
        await update_notification_status(
            selected[0].get("alexaUserId") or user_id,
            selected[0]["notificationId"],
            status,
        )
        publication_id = selected[0]["publicationId"]
        publication_title = selected[0].get("title")
        source = "publication_notification"
        for item in ordered:
            item["publicationId"] = item.get("publicationId") or publication_id
            item["publicationTitle"] = item.get("publicationTitle") or publication_title
    if ordered:
        queue = create_playback_queue(
            handler_input,
            [item["contentId"] for item in ordered],
            source=source,
            publication_id=publication_id,
            publication_title=publication_title,
        )
    else:
        queue = None
    return {**result, "results": ordered, "queue": queue}


def group_notifications_by_creator(items: list) -> list:
    """Retain the existing speech interface for compact notification prompts."""
    return [{"creatorId": "notifications", "creatorName": "your subscriptions", "tracks": items}] if items else []


def build_notification_speech(groups: list) -> str:
    if not groups:
        return ""
    items = groups[0]["tracks"]
    if len(items) == 1:
        item = items[0]
        return NOTIFICATIONS_SINGLE_TRACK(item.get("title"), "your subscriptions")
    if len(groups) == 1:
        return NOTIFICATIONS_SINGLE_CREATOR("your subscriptions", items)
    return NOTIFICATIONS_MULTI_CREATOR(len(items), groups)


def reset_memory_notifications_for_tests() -> None:
    _memory_inbox.clear()
