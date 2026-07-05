from __future__ import annotations

from config import settings
from src.services.api import search as api_search
from src.services.persistence import get_store, update_store, append_to_queue, set_browse_catalog, get_browse_catalog
from src.utils.audio import resolve_track_audio
from src.utils.browse_catalog import catalog_search_context, has_more_server_pages, build_catalog_from_search_result
from src.utils.content_playback import queue_parent_for_token_fallback
from src.utils.lambda_deadline import has_budget_for_api, compute_search_timeout_ms
from src.utils.next_content import build_playback_exclude_set, pick_next_search_item
from src.utils.normalize_content_item import normalize_content_items, content_title_for_speech, pick_content_credit
from src.utils.search_filters import build_search_filters
from src.utils.session_queue import resolve_queue_item_for_playback, clone_queue_item
from src.utils.speech import ssml, LOCAL_CONTENT_FALLBACK, QUEUE_FINISHED
from src.utils.playback_start import start_playback
from src.utils.queue_advance import play_next_queued_item
from src.utils.queue_refill import append_local_catalog_to_queue


def resolve_item_at_index(store: dict, index: int) -> dict | None:
    """Resolve a content item at the given index from the queue or catalog."""
    catalog = get_browse_catalog(store)
    queue = store.get("upcomingQueue") or []
    if 0 <= index < len(queue) and queue[index]:
        return {"item": queue[index], "catalog": catalog}
    if catalog and catalog.get("items") and 0 <= index < len(catalog["items"]) and catalog["items"][index]:
        return {"item": catalog["items"][index], "catalog": catalog}
    return None


def _merge_catalog_onto_content(content: dict | None, catalog_item: dict | None, snapshot: dict | None) -> dict | None:
    """Merge catalog and snapshot data onto a content item for playback."""
    if not content:
        return None
    merged = dict(content)
    if catalog_item:
        merged = {
            **catalog_item,
            **merged,
            "audioUrl": merged.get("audioUrl") or catalog_item.get("audioUrl"),
            "tracks": merged.get("tracks") if isinstance(merged.get("tracks"), list) and merged["tracks"] else catalog_item.get("tracks"),
            "playback_speed": merged.get("playback_speed") or catalog_item.get("playback_speed"),
        }
    if snapshot:
        merged = {
            **merged,
            "spokenTitle": snapshot.get("spokenTitle") or merged.get("spokenTitle"),
            "displayTitle": snapshot.get("displayTitle") or merged.get("displayTitle"),
            "title": snapshot.get("displayTitle") or snapshot.get("title") or merged.get("title"),
            "creator": snapshot.get("creator") or merged.get("creator"),
            "summary": snapshot.get("summary") or merged.get("summary"),
            "audioUrl": merged.get("audioUrl") or snapshot.get("audioUrl"),
            "tracks": merged.get("tracks") if isinstance(merged.get("tracks"), list) and merged["tracks"] else snapshot.get("tracks"),
        }
    return merged


async def _resolve_content_for_playback(handler_input, raw: dict, store: dict) -> dict | None:
    """Resolve full content data for a catalog item, fetching from API if needed."""
    if not raw:
        return None
    catalog = get_browse_catalog(store)
    catalog_item = next((i for i in (catalog.get("items") or []) if isinstance(i, dict) and i.get("id") and raw.get("id") and str(i["id"]) == str(raw["id"])), None) if catalog else None
    snapshot = next((i for i in (store.get("pendingBrowseItems") or []) if isinstance(i, dict) and i.get("id") == raw.get("id")), catalog_item)
    if raw.get("audioUrl") or (isinstance(raw.get("tracks"), list) and raw["tracks"]):
        return _merge_catalog_onto_content(dict(raw), catalog_item, snapshot)
    if catalog_item and (catalog_item.get("audioUrl") or catalog_item.get("tracks")):
        return _merge_catalog_onto_content(dict(catalog_item), catalog_item, snapshot)
    if snapshot and (snapshot.get("audioUrl") or snapshot.get("tracks")):
        return _merge_catalog_onto_content(dict(snapshot), catalog_item, snapshot)
    if not has_budget_for_api(handler_input):
        return None
    content = await resolve_queue_item_for_playback(raw)
    return _merge_catalog_onto_content(content, catalog_item, snapshot)


async def play_catalog_item_at_index(handler_input, index: int):
    """Play a specific catalog item by its index."""
    store = get_store(handler_input)
    resolved = resolve_item_at_index(store, index)
    if not resolved or not resolved.get("item"):
        return None
    content = await _resolve_content_for_playback(handler_input, resolved["item"], store)
    if not content:
        return None
    track_info = resolve_track_audio(content, 0)
    if not track_info or not track_info["audioUrl"]:
        return None
    update_store(handler_input, {"queueIndex": index})
    title = content_title_for_speech(content) or (resolved["item"].get("spokenTitle") or resolved["item"].get("displayTitle") or resolved["item"].get("title"))
    credit = pick_content_credit(content) or resolved["item"].get("creator")
    intro = LOCAL_CONTENT_FALLBACK(title, credit)
    return await start_playback(handler_input, content, intro, 0, preserve_session_queue=True)


async def _fetch_next_browse_page_and_play(handler_input, store: dict, catalog: dict):
    """Fetch the next page of browse results from the server and play the next item."""

    if not has_budget_for_api(handler_input):
        return None
    next_page = (catalog.get("currentPage") or 0) + 1
    ctx = catalog_search_context(catalog)
    exclude_set = build_playback_exclude_set(store, include_future_queue=False)
    payload = build_search_filters(handler_input, store, q=ctx.get("q") or "", limit=catalog.get("limit") or settings.search_page_limit, page=next_page)
    payload["filters"] = {
        **(payload.get("filters") or {}),
        "excludeIds": list(dict.fromkeys((payload.get("filters") or {}).get("excludeIds") or [] + list(exclude_set)))[:20],
    }
    result = await api_search(payload, timeout_ms=compute_search_timeout_ms(handler_input))
    if result.get("failed") or not result.get("results"):
        return None
    merged = build_catalog_from_search_result(result, **ctx, page=next_page, limit=catalog.get("limit") or settings.search_page_limit, existing_catalog=catalog, append=True)
    set_browse_catalog(handler_input, merged, intent=catalog.get("intent"))
    fresh_items = [clone_queue_item(i) for i in normalize_content_items(result["results"]) if isinstance(i, dict) and i.get("id") and str(i["id"]) not in exclude_set]
    if fresh_items:
        append_to_queue(handler_input, fresh_items)
    queue_index = store.get("queueIndex") or 0
    if queue_index + 1 < len(merged.get("items") or []):
        return await play_catalog_item_at_index(handler_input, queue_index + 1)
    skip_parent_id = queue_parent_for_token_fallback(store)
    next_item = pick_next_search_item(result.get("results") or [], exclude_set, skip_parent_id)
    if not next_item:
        return None
    return await start_playback(handler_input, next_item, LOCAL_CONTENT_FALLBACK(content_title_for_speech(next_item), pick_content_credit(next_item)), 0, preserve_session_queue=True)


async def play_next_in_browse_session(handler_input):
    """Advance to the next item in the current browse session, fetching more if needed."""

    store = get_store(handler_input)
    catalog = get_browse_catalog(store)
    queue_index = store.get("queueIndex") or 0
    if catalog and catalog.get("items") and queue_index + 1 < len(catalog["items"]):
        played = await play_catalog_item_at_index(handler_input, queue_index + 1)
        if played:
            return played
    queued = await play_next_queued_item(handler_input)
    if queued:
        return queued
    store = get_store(handler_input)
    if append_local_catalog_to_queue(handler_input, store):
        catalog_queued = await play_next_queued_item(handler_input)
        if catalog_queued:
            return catalog_queued
    store = get_store(handler_input)
    catalog_after = get_browse_catalog(store)
    if catalog_after and has_more_server_pages(catalog_after):
        page_play = await _fetch_next_browse_page_and_play(handler_input, store, catalog_after)
        if page_play:
            return page_play
    if (catalog and catalog.get("items")) or (store.get("upcomingQueue") or []):
        return handler_input.response_builder.speak(ssml(QUEUE_FINISHED)).get_response()
    return None


async def play_previous_in_browse_session(handler_input):
    """Go back to the previous item in the browse session."""
    store = get_store(handler_input)
    queue_index = store.get("queueIndex") or 0
    if queue_index > 0:
        return await play_catalog_item_at_index(handler_input, queue_index - 1)
    return None


def _find_next_unplayed_catalog_item(store: dict) -> dict | None:
    """Find the next unplayed item in the catalog beyond the current index."""
    catalog = get_browse_catalog(store)
    if not catalog or not catalog.get("items"):
        return None
    queue_index = store.get("queueIndex") or 0
    exclude_set = build_playback_exclude_set(store, include_future_queue=False)
    for i in range(queue_index + 1, len(catalog["items"])):
        item = catalog["items"][i]
        if isinstance(item, dict) and item.get("id") and str(item["id"]) not in exclude_set:
            return item
    return None
