from __future__ import annotations
import boto3
from config import settings

_memory_store: dict[str, dict] = {}


def _table_name() -> str:
    return str(getattr(settings, "DYNAMO_PLAYBACK_STATE_TABLE", "") or "").strip()


def _region() -> str:
    return (
        getattr(settings, "HEAR_DDB_REGION", None)
        or getattr(settings, "AWS_REGION", None)
        or "eu-west-1"
    )


_doc_client = None


def _get_doc_client():
    """Return a cached DynamoDB DocumentClient, creating one on first call."""
    global _doc_client
    if _doc_client is not None:
        return _doc_client
    _doc_client = boto3.resource("dynamodb", region_name=_region())
    return _doc_client


def _use_memory() -> bool:
    return not _table_name()


async def get_state(alexa_user_id: str) -> dict | None:
    """Retrieve the stored playback state for a user from DynamoDB or memory."""
    if not alexa_user_id:
        return None
    if _use_memory():
        return _memory_store.get(alexa_user_id) or None
    try:
        table = _get_doc_client().Table(_table_name())
        resp = table.get_item(Key={"alexaUserId": alexa_user_id})
        return resp.get("Item") or None
    except Exception:
        return None


async def set_state(alexa_user_id: str, fields: dict) -> dict | None:
    """Merge fields into the stored playback state for a user and persist."""
    if not alexa_user_id or not isinstance(fields, dict):
        return None
    existing = await get_state(alexa_user_id) or {}
    merged: dict = {"alexaUserId": alexa_user_id, **existing, **fields}
    if _use_memory():
        _memory_store[alexa_user_id] = merged
        return merged
    try:
        table = _get_doc_client().Table(_table_name())
        table.put_item(Item=merged)
        return merged
    except Exception:
        return None


async def clear_state(alexa_user_id: str) -> None:
    """Remove the stored playback state for a user entirely."""
    if not alexa_user_id:
        return
    if _use_memory():
        _memory_store.pop(alexa_user_id, None)
        return
    try:
        table = _get_doc_client().Table(_table_name())
        table.delete_item(Key={"alexaUserId": alexa_user_id})
    except Exception:
        pass


def reset_memory_store_for_tests() -> None:
    """Reset the in-memory store; for test teardown only."""
    _memory_store.clear()
