from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import asyncio
import boto3
from config import settings
import time
from ask_sdk_core.dispatch_components import (
    AbstractRequestInterceptor,
    AbstractResponseInterceptor,
)
from src.models import PERSISTED_FIELDS
from src.services.store import DEFAULT_STORE
from src.utils.lambda_deadline import (
    persistence_load_budget_ms,
    should_skip_persistence_load,
    requires_reliable_persistence_load,
)
from src.utils.lambda_deadline import (
    persistence_save_budget_ms,
    requires_reliable_persistence_save,
)
from src.services.dialog_state import migrate_active_dialog
class PlaybackStateRepository:
    def __init__(self, table_name: str = "", region: str = "") -> None:
        self.table_name = table_name.strip()
        self.region = region.strip()
        self._memory: dict[str, dict] = {}
        self._dynamodb = None

    def _resolved_table_name(self) -> str:
        return self.table_name or ""

    def _resolved_region(self) -> str:
        return self.region or settings.HEAR_DDB_REGION or "eu-west-1"

    def _table(self):
        if self._dynamodb is None:
            self._dynamodb = boto3.resource(
                "dynamodb",
                region_name=self._resolved_region(),
            )
        return self._dynamodb.Table(self._resolved_table_name())

    async def get(self, user_id: str) -> dict | None:
        if not user_id:
            return None
        if not self._resolved_table_name():
            return self._memory.get(user_id)
        try:
            response = await asyncio.to_thread(
                self._table().get_item, Key={"alexaUserId": user_id}
            )
            return response.get("Item")
        except Exception:
            return None

    async def set(self, user_id: str, fields: dict) -> dict | None:
        if not user_id or not isinstance(fields, dict):
            return None
        if not self._resolved_table_name():
            existing = await self.get(user_id) or {}
            state = {"alexaUserId": user_id, **existing, **fields}
            self._memory[user_id] = state
            return state
        try:
            names = {f"#f{index}": key for index, key in enumerate(fields)}
            values = {f":v{index}": value for index, value in enumerate(fields.values())}
            response = await asyncio.to_thread(
                self._table().update_item,
                Key={"alexaUserId": user_id},
                UpdateExpression="SET " + ", ".join(
                    f"#f{index} = :v{index}" for index in range(len(fields))
                ),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
            return response.get("Attributes")
        except Exception:
            return None

    async def clear(self, user_id: str) -> None:
        if not user_id:
            return
        if not self._resolved_table_name():
            self._memory.pop(user_id, None)
            return
        try:
            await asyncio.to_thread(
                self._table().delete_item, Key={"alexaUserId": user_id}
            )
        except Exception:
            return

def normalize_recent_track_listens(lst: object) -> list:
    """Sanitise and cap the recent-track-listens list to configured max size."""
    if not isinstance(lst, list):
        return []
    cap = settings.HEAR_MAX_TRACK_LISTEN_LOG or settings.max_history
    return [e for e in lst if isinstance(e, dict) and e.get("contentId")][:cap]


def _normalize_play_history_entry(entry) -> dict | None:
    if isinstance(entry, str):
        return {"id": entry}
    if isinstance(entry, dict) and entry.get("id"):
        if entry.get("audioUrl"):
            return {
                "id": str(entry["id"]),
                "title": entry.get("title"),
                "audioUrl": entry.get("audioUrl"),
                "durationSecs": entry.get("durationSecs") if "durationSecs" in entry else None,
                "tracks": entry.get("tracks") if entry.get("tracks") else None,
                "playback_speed": entry.get("playback_speed") if entry.get("playback_speed") else None,
                "creator": entry.get("creator"),
                "category": entry.get("category"),
                "summary": entry.get("summary"),
            }
        return {"id": str(entry["id"])}
    return None


def _migrate_playback_fields(merged: dict) -> dict:
    """Read legacy playback fields once and remove them from persisted state."""
    if not merged.get("activePlayback") and merged.get("currentContentId"):
        content_id = str(merged["currentContentId"])
        offset_ms = max(0, int(merged.get("lastOffsetMs") or 0))
        merged["activePlayback"] = {
            "contentId": content_id,
            "token": content_id,
            "title": merged.get("currentContentTitle") or merged.get("feedbackContentTitle"),
            "creatorId": merged.get("currentCreatorId") or merged.get("feedbackCreatorId"),
            "creatorName": merged.get("currentCreator") or merged.get("feedbackCreator"),
            "publicationId": merged.get("currentPublicationId"),
            "publicationTitle": None,
            "queueId": None,
            "queueIndex": 0,
            "audioUrl": merged.get("currentAudioUrl"),
            "durationMs": (
                int(merged["currentDurationSecs"] * 1000)
                if isinstance(merged.get("currentDurationSecs"), (int, float))
                else None
            ),
            "offsetMs": offset_ms,
            "listenedMs": offset_ms,
            "sessionId": f"migrated:{content_id}",
            "status": "paused",
            "startedAt": int(time.time() * 1000),
            "updatedAt": int(time.time() * 1000),
        }
    legacy_queue = merged.get("upcomingQueue")
    if not merged.get("playbackQueue") and isinstance(legacy_queue, list):
        content_ids = [
            str(item.get("contentId") or item.get("id"))
            for item in legacy_queue
            if isinstance(item, dict) and (item.get("contentId") or item.get("id"))
        ]
        if content_ids:
            merged["playbackQueue"] = {
                "queueId": f"migrated:{int(time.time() * 1000)}",
                "source": "migrated",
                "publicationId": None,
                "publicationTitle": None,
                "orderedContentIds": list(dict.fromkeys(content_ids)),
                "currentIndex": max(0, int(merged.get("queueIndex") or 0)),
                "createdAt": int(time.time() * 1000),
            }
    for key in (
        "playbackParentId", "playbackContentType", "playbackContentId",
        "currentPublicationId", "currentTrackIndex", "currentTotalTracks",
        "currentTracks", "upcomingQueue", "queueIndex", "queueSource",
        "queueLocality", "queueCategory", "queueItemsCompleted",
        "activeListenSession", "playbackSession", "recentTrackListens",
    ):
        merged.pop(key, None)
    return merged


def merge_initial_store(stored: dict | None) -> dict:
    """Merge persisted attributes into DEFAULT_STORE and apply migrations."""
    merged = {**DEFAULT_STORE, **(stored if isinstance(stored, dict) else {})}
    merged["recentTrackListens"] = normalize_recent_track_listens(merged.get("recentTrackListens"))
    merged = _migrate_playback_fields(merged)
    merged = migrate_active_dialog(merged)
    for key in list(merged):
        if key not in PERSISTED_FIELDS:
            merged.pop(key, None)
    pattern = merged.get("listeningPattern")
    if isinstance(pattern, dict):
        merged["listeningPattern"] = dict(list(pattern.items())[:40])
    followed = merged.get("followedCreators")
    if isinstance(followed, list):
        normalized_followed = []
        seen = set()
        for item in followed:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            source_type = "organization" if item.get("type") == "organization" else "creator"
            key = (source_type, str(item["id"]))
            if key in seen:
                continue
            seen.add(key)
            normalized_followed.append({
                "id": str(item["id"]),
                "name": item.get("name"),
                "type": source_type,
            })
        merged["followedCreators"] = normalized_followed[-50:]
    return merged


def build_persisted_snapshot(store: dict) -> dict:
    """Produce a size-optimised copy of *store* for DynamoDB persistence."""
    if not isinstance(store, dict):
        return {}
    return {key: value for key, value in store.items() if key in PERSISTED_FIELDS}


class LoadPersistenceInterceptor(AbstractRequestInterceptor):
    """Request interceptor that loads persisted session state into request attributes."""

    async def process(self, handler_input) -> None:

        if getattr(handler_input.request_envelope.request, "type", None) == "CanFulfillIntentRequest":
            handler_input.attributes_manager.request_attributes = {"_store": merge_initial_store({}), "_dirty": False}
            return

        if should_skip_persistence_load(handler_input):
            handler_input.attributes_manager.request_attributes = {"_store": merge_initial_store({}), "_dirty": False}
            return

        reliable_load = requires_reliable_persistence_load(handler_input)
        budget_ms = 0 if reliable_load else persistence_load_budget_ms(handler_input)
        stored: dict = {}
        try:
            if budget_ms and budget_ms > 0:
                load_promise = handler_input.attributes_manager.persistent_attributes
                try:
                    stored = await asyncio.wait_for(load_promise, timeout=budget_ms / 1000.0) or {}
                except asyncio.TimeoutError:
                    stored = {}
            else:
                stored = await handler_input.attributes_manager.persistent_attributes or {}
        except Exception as exc:
            logger.warning(
                "Hear: persistence load failed error=%s degraded=true",
                type(exc).__name__,
            )
            stored = {}

        store = merge_initial_store(stored)
        handler_input.attributes_manager.request_attributes = {"_store": store, "_dirty": False}


class SavePersistenceInterceptor(AbstractResponseInterceptor):
    """Response interceptor that saves the session store to persistent attributes."""

    async def process(self, handler_input) -> None:
        try:
            attrs = handler_input.attributes_manager.request_attributes
            if not attrs.get("_dirty"):
                return

            reliable_save = requires_reliable_persistence_save(handler_input)
            budget_ms = None if reliable_save else persistence_save_budget_ms(handler_input)
            snapshot = build_persisted_snapshot(attrs.get("_store") or {})
            handler_input.attributes_manager.persistent_attributes = snapshot

            if not reliable_save and budget_ms is not None and budget_ms < 200:
                return

            save_promise = handler_input.attributes_manager.save_persistent_attributes()
            if budget_ms is not None and not reliable_save:
                try:
                    await asyncio.wait_for(save_promise, timeout=budget_ms / 1000.0)
                except asyncio.TimeoutError:
                    logger.warning("Hear: persistence save timed out degraded=true")
            else:
                await save_promise
        except Exception as exc:
            logger.warning(
                "Hear: persistence save failed error=%s",
                type(exc).__name__,
            )
