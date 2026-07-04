from __future__ import annotations

import json
import time

import boto3
from boto3.dynamodb.conditions import Attr

from config import settings
from src.utils.speech import NOTIFICATIONS_SINGLE_TRACK, NOTIFICATIONS_SINGLE_CREATOR, NOTIFICATIONS_MULTI_CREATOR

_doc_client = None


def _get_doc_client():
    """Return a cached DynamoDB resource client."""
    global _doc_client
    if _doc_client is not None:
        return _doc_client
    region = settings.HEAR_DDB_REGION or settings.AWS_REGION or "eu-west-1"
    _doc_client = boto3.resource("dynamodb", region_name=region)
    return _doc_client


async def handle_notification_webhook(event: dict) -> dict:
    """Handle an incoming notification webhook by writing a track to DynamoDB."""
    body = event.get("body")
    parsed = json.loads(body) if isinstance(body, str) else body

    table_name = settings.NOTIFICATIONS_TABLE or "hear_notifications"
    now = int(time.time())
    ttl = (parsed.get("publishedAt") or now) + 604800

    item = {
        "pk": f"track#{parsed.get('trackId')}",
        "title": parsed.get("title") or "",
        "creator": parsed.get("creator") or "",
        "creatorId": parsed.get("creatorId") or "",
        "organisation": parsed.get("organisation") or "",
        "category": parsed.get("category") or "",
        "audioUrl": parsed.get("audioUrl") or "",
        "duration": parsed.get("duration") or 0,
        "publishedAt": parsed.get("publishedAt") or now,
        "ttl": ttl,
    }

    try:
        client = _get_doc_client()
        table = client.Table(table_name)
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    except Exception as e:
        if hasattr(e, "response") and e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            pass
        else:
            raise

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"status": "ok"}),
    }


async def check_notifications(user_id: str) -> list:
    """Check for unannounced notifications for a given user."""
    if not user_id:
        return []
    table_name = settings.NOTIFICATIONS_TABLE or "hear_notifications"
    try:
        client = _get_doc_client()
        table = client.Table(table_name)
        resp = table.scan(
            FilterExpression="NOT contains(announcedTo, :userId)",
            ExpressionAttributeValues={":userId": user_id},
        )
        items = resp.get("Items") or []
        result = []
        for item in items:
            result.append({
                "trackId": item.get("pk", "").replace("track#", "") if item.get("pk") else None,
                "title": item.get("title") or "",
                "creator": item.get("creator") or "",
                "creatorId": item.get("creatorId") or "",
                "organisation": item.get("organisation") or "",
                "category": item.get("category") or "",
                "audioUrl": item.get("audioUrl") or "",
                "duration": item.get("duration") or 0,
                "publishedAt": item.get("publishedAt") or 0,
            })
        return result
    except Exception:
        return []


async def mark_track_announced(track_id: str, user_id: str):
    """Mark a notification track as announced to a specific user."""
    if not track_id or not user_id:
        return
    table_name = settings.NOTIFICATIONS_TABLE or "hear_notifications"
    try:
        client = _get_doc_client()
        table = client.Table(table_name)
        table.update_item(
            Key={"pk": f"track#{track_id}"},
            UpdateExpression="ADD announcedTo :userId",
            ExpressionAttributeValues={":userId": {user_id}},
        )
    except Exception:
        pass


async def mark_track_heard(track_id: str, user_id: str):
    """Mark a notification track as heard by a specific user."""
    if not track_id or not user_id:
        return
    table_name = settings.NOTIFICATIONS_TABLE or "hear_notifications"
    try:
        client = _get_doc_client()
        table = client.Table(table_name)
        table.update_item(
            Key={"pk": f"track#{track_id}"},
            UpdateExpression="ADD heardBy :userId",
            ExpressionAttributeValues={":userId": {user_id}},
        )
    except Exception:
        pass


async def mark_all_tracks_announced(track_ids: list, user_id: str):
    """Mark multiple notification tracks as announced to a specific user."""
    for tid in track_ids:
        await mark_track_announced(tid, user_id)


def group_notifications_by_creator(tracks: list) -> list:
    """Group notification tracks by their creator."""
    if not tracks:
        return []

    by_creator: dict = {}
    for t in tracks:
        cid = t.get("creatorId") or t.get("creator") or "unknown"
        if cid not in by_creator:
            by_creator[cid] = {"creatorId": cid, "creatorName": t.get("creator") or "unknown", "tracks": []}
        by_creator[cid]["tracks"].append(t)

    for group in by_creator.values():
        group["tracks"].sort(key=lambda x: x.get("publishedAt") or 0, reverse=True)

    groups = list(by_creator.values())
    groups.sort(key=lambda g: len(g["tracks"]), reverse=True)
    return groups


def build_notification_speech(groups: list) -> str:
    """Build the spoken notification intro from grouped tracks."""
    if not groups:
        return ""
    total_tracks = sum(len(g["tracks"]) for g in groups)
    if len(groups) == 1 and len(groups[0]["tracks"]) == 1:
        t = groups[0]["tracks"][0]
        return NOTIFICATIONS_SINGLE_TRACK(t.get("title"), t.get("creator"))
    if len(groups) == 1:
        g = groups[0]
        return NOTIFICATIONS_SINGLE_CREATOR(g["creatorName"], g["tracks"])
    return NOTIFICATIONS_MULTI_CREATOR(total_tracks, groups)
