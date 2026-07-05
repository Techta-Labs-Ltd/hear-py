from __future__ import annotations
import time
import asyncio
from copy import deepcopy
from config import settings
# DEFAULT_STORE / get_store / update_store live in the leaf module store_core so
# that low-level modules (alexa_reminders, publication_tracks) can share them
# without importing this module. Re-exported here for backwards compatibility.
from src.services.store_core import DEFAULT_STORE, get_store, update_store
from src.services.alexa_reminders import cancel_feedback_reminder
from src.utils.publication_tracks import slim_publication_track
from src.utils.normalize_content_item import is_bad_credit_name, is_id_like_label
from src.utils.normalize_content_item import pick_content_credit, content_title_for_speech
from src.utils.session_queue import sort_queue_items_by_listening_preferences, merge_browse_items_preserve_order, is_same_browse_session, clone_browse_menu_item
from src.utils.session_queue import clone_queue_item
from src.utils.lambda_deadline import persistence_load_budget_ms, should_skip_persistence_load, requires_reliable_persistence_load
from src.utils.lambda_deadline import get_lambda_remaining_ms, persistence_save_budget_ms, requires_reliable_persistence_save


_MAX_FEEDBACK_ASKED_TOKENS = 50

_TRANSIENT_OFFLOAD_FIELDS: list[str] = [
    "playbackDurationEstimateMs",
    "_requiresReliableSave",
]


def normalize_recent_track_listens(lst: object) -> list:
    """Sanitise and cap the recent-track-listens list to configured max size."""
    if not isinstance(lst, list):
        return []
    cap = settings.HEAR_MAX_TRACK_LISTEN_LOG or settings.max_history
    return [e for e in lst if isinstance(e, dict) and e.get("trackId")][:cap]


async def clear_feedback(handler_input) -> dict:
    """Clear all feedback-related state from the store and cancel any reminder."""
    try:
        await cancel_feedback_reminder(handler_input)
    except Exception:
        pass
    return update_store(handler_input, {
        "awaitingFeedback": False,
        "awaitingFollow": False,
        "awaitingNotificationOptIn": False,
        "awaitingReportDecision": False,
        "reportContext": None,
        "pendingFeedback": None,
        "feedbackContentId": None,
        "feedbackPromptText": None,
        "feedbackCategory": None,
        "feedbackCreator": None,
        "feedbackCreatorId": None,
        "feedbackContentTitle": None,
        "feedbackReminderAlertToken": None,
        "feedbackAskedForToken": None,
        "playbackDurationEstimateMs": None,
    })


def dismiss_feedback_prompt(handler_input) -> dict:
    """Dismiss the active feedback prompt without recording a rating."""
    return update_store(handler_input, {
        "awaitingFeedback": False,
        "awaitingNotificationOptIn": False,
        "pendingFeedback": None,
        "feedbackPromptText": None,
        "feedbackAskedForToken": None,
        "feedbackReminderAlertToken": None,
    })


def set_pending_feedback(
    handler_input,
    track_id: str | None = None,
    creator_id: str | None = None,
    title: str | None = None,
    creator_name: str | None = None,
) -> dict:
    """Stage a pending feedback record for the current track."""
    store = get_store(handler_input)
    resolved_track_id = (
        track_id
        or store.get("feedbackContentId")
        or store.get("playbackTrackId")
        or store.get("lastToken")
    )
    resolved_creator_id = creator_id or store.get("feedbackCreatorId") or None
    resolved_title = title or store.get("feedbackContentTitle") or None
    resolved_creator_name = creator_name or store.get("feedbackCreator") or None
    return update_store(handler_input, {
        "pendingFeedback": {
            "feedbackGiven": False,
            "trackId": str(resolved_track_id) if resolved_track_id is not None else None,
            "creatorId": str(resolved_creator_id) if resolved_creator_id is not None else None,
            "title": resolved_title,
            "creatorName": resolved_creator_name,
            "askedAt": int(time.time() * 1000),
        },
        "awaitingFeedback": True,
        "feedbackContentId": str(resolved_track_id) if resolved_track_id is not None else store.get("feedbackContentId"),
        "_requiresReliableSave": True,
    })


def clear_pending_feedback(handler_input) -> dict:
    """Remove the current pending-feedback record."""
    return update_store(handler_input, {"pendingFeedback": None, "_requiresReliableSave": False})


def was_feedback_asked(store: dict, token: str | None) -> bool:
    """Return True if feedback has already been asked for the given token."""
    if not token:
        return False
    lst = store.get("feedbackAskedTokens") if store else None
    return isinstance(lst, list) and str(token) in lst


def mark_feedback_asked(handler_input, token: str | None) -> dict:
    """Record that feedback was asked for *token* so it won't be asked again."""
    if not token:
        return get_store(handler_input)
    store = get_store(handler_input)
    key = str(token)
    existing = store.get("feedbackAskedTokens") or []
    if key in existing:
        return store
    next_list = (existing + [key])[-_MAX_FEEDBACK_ASKED_TOKENS:]
    return update_store(handler_input, {"feedbackAskedTokens": next_list})


def _normalize_feedback_track_keys(*candidates) -> list:
    seen: set[str] = set()
    keys: list[str] = []
    for c in candidates:
        if c is None or c == "":
            continue
        k = str(c).strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def was_feedback_given(store: dict, *track_keys) -> bool:
    """Return True if any of the supplied track keys has already been rated."""
    lst = store.get("feedbackGivenTokens") if store else None
    if not isinstance(lst, list) or not lst:
        return False
    return any(k in lst for k in _normalize_feedback_track_keys(*track_keys))


def mark_feedback_given(handler_input, *track_keys) -> dict:
    """Record that feedback was given for the supplied track keys."""
    keys = _normalize_feedback_track_keys(*track_keys)
    if not keys:
        return get_store(handler_input)
    store = get_store(handler_input)
    existing = store.get("feedbackGivenTokens") or []
    next_list = list(existing)
    for k in keys:
        if k not in next_list:
            next_list.append(k)
    next_list = next_list[-_MAX_FEEDBACK_ASKED_TOKENS:]
    if len(next_list) == len(existing) and all(k in existing for k in keys):
        return store
    return update_store(handler_input, {"feedbackGivenTokens": next_list})


def mark_feedback_given_from_store(handler_input, store: dict | None = None) -> dict:
    """Convenience wrapper — marks feedback as given using keys derived from the current store."""
    s = store or get_store(handler_input)
    pf = s.get("pendingFeedback") or {}
    return mark_feedback_given(
        handler_input,
        pf.get("trackId"),
        s.get("feedbackContentId"),
        s.get("playbackTrackId"),
        s.get("lastToken"),
        s.get("currentContentId"),
    )


def _normalize_creator_for_pattern(store: dict, creator) -> str | None:
    if not creator:
        return None
    raw = str(creator).strip()
    if not raw:
        return None
    if not is_bad_credit_name(raw) and not is_id_like_label(raw):
        return raw
    creator_id = store.get("feedbackCreatorId") or store.get("currentCreatorId") or None
    if creator_id and str(creator_id) == raw:
        name = store.get("feedbackCreator") or store.get("currentCreator") or None
        if name and not is_bad_credit_name(name) and not is_id_like_label(name):
            return str(name).strip()
    for c in store.get("followedCreators") or []:
        if c.get("id") == raw:
            nm = c.get("name")
            if nm and not is_bad_credit_name(nm):
                return str(nm).strip()
    return None


def record_listening_event(
    handler_input,
    *,
    category: str | None = None,
    creator: str | None = None,
    liked: bool | None = None,
) -> dict:
    """Update the user's listening pattern with a score for category and/or creator."""
    store = get_store(handler_input)
    pattern = dict(store.get("listeningPattern") or {})
    score = 2 if liked is True else (-1 if liked is False else 1)
    if category:
        key = f"category:{category}"
        pattern[key] = (pattern.get(key) or 0) + score
    creator_label = _normalize_creator_for_pattern(store, creator)
    if creator_label:
        key = f"creator:{creator_label}"
        pattern[key] = (pattern.get(key) or 0) + score
    return update_store(handler_input, {"listeningPattern": pattern})


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


def add_to_history(handler_input, content_or_id, recording_id: str | None = None) -> dict:
    """Insert an entry at the front of the play history, deduping and capping.

    Accepts a full content dict (to store a playable snapshot) or a plain
    content-id string/dict for backward compatibility.
    """
    store = get_store(handler_input)
    history = [_normalize_play_history_entry(e) for e in (store.get("playHistory") or [])]
    history = [h for h in history if h is not None]
    if isinstance(content_or_id, dict) and content_or_id.get("audioUrl"):
        entry = _normalize_play_history_entry(content_or_id)
        if not entry:
            return store
        cid = entry["id"]
    else:
        cid = str(content_or_id) if content_or_id is not None else None
        entry = {"id": cid} if cid else None
    if not cid:
        return store
    for i, h in enumerate(history):
        if h["id"] == cid:
            history.pop(i)
            break
    history.insert(0, entry)
    cap = settings.max_history
    return update_store(handler_input, {"playHistory": history[:cap]})


def add_followed_creator(handler_input, creator_id: str, creator_name: str) -> dict:
    """Add a creator to the user's followed list (idempotent)."""
    store = get_store(handler_input)
    followed = list(store.get("followedCreators") or [])
    if any(c.get("id") == creator_id for c in followed):
        return store
    followed.append({"id": creator_id, "name": creator_name})
    return update_store(handler_input, {"followedCreators": followed})


def remove_followed_creator(handler_input, creator_id: str) -> dict:
    """Remove a creator from the user's followed list."""
    store = get_store(handler_input)
    followed = [c for c in (store.get("followedCreators") or []) if c.get("id") != creator_id]
    return update_store(handler_input, {"followedCreators": followed})


def is_following(store: dict, creator_id: str) -> bool:
    """Return True if *creator_id* is in the user's followed list."""
    return any(c.get("id") == creator_id for c in (store.get("followedCreators") or []))


def resolve_preferred_category(listening_pattern: dict) -> str | None:
    """Return the highest-scored category from the listening pattern."""
    entries = sorted(
        [(k, v) for k, v in (listening_pattern or {}).items() if k.startswith("category:")],
        key=lambda x: x[1],
        reverse=True,
    )
    return entries[0][0].replace("category:", "") if entries else None


def resolve_top_categories(listening_pattern: dict, limit: int = 999999) -> list:
    """Return the top-scored categories from the listening pattern, ordered by score."""
    entries = sorted(
        [(k, v) for k, v in (listening_pattern or {}).items() if k.startswith("category:")],
        key=lambda x: x[1],
        reverse=True,
    )
    return [k.replace("category:", "") for k, _ in entries[:limit]]


def resolve_preferred_creator(listening_pattern: dict) -> str | None:
    """Return the highest-scored creator from the listening pattern."""
    entries = sorted(
        [(k, v) for k, v in (listening_pattern or {}).items() if k.startswith("creator:")],
        key=lambda x: x[1],
        reverse=True,
    )
    return entries[0][0].replace("creator:", "") if entries else None


def _migrate_playback_fields(merged: dict) -> dict:
    if not merged.get("playbackParentId") and merged.get("currentPublicationId"):
        merged["playbackParentId"] = merged["currentPublicationId"]
        if not merged.get("playbackContentType"):
            merged["playbackContentType"] = "publication"
    if not merged.get("currentContentId") and merged.get("feedbackContentId"):
        merged["currentContentId"] = merged["feedbackContentId"]
    if not merged.get("currentContentTitle") and merged.get("feedbackContentTitle"):
        merged["currentContentTitle"] = merged["feedbackContentTitle"]
    if not merged.get("currentCreator") and merged.get("feedbackCreator"):
        merged["currentCreator"] = merged["feedbackCreator"]
    if not merged.get("currentCreatorId") and merged.get("feedbackCreatorId"):
        merged["currentCreatorId"] = merged["feedbackCreatorId"]
    if not merged.get("currentCategory") and merged.get("feedbackCategory"):
        merged["currentCategory"] = merged["feedbackCategory"]
    tracks = merged.get("currentTracks")
    if not merged.get("currentTotalTracks") and isinstance(tracks, list) and tracks:
        merged["currentTotalTracks"] = len(tracks)
    return merged


def recent_content_ids(store: dict, limit: int | None = None) -> list:
    """Compile the list of recently-seen content IDs for exclusion filters."""
    cap = limit or settings.HEAR_RECENT_EXCLUDE_LIMIT or settings.max_history or 20
    seen: set[str] = set()
    out: list[str] = []

    def push(val) -> None:
        k = str(val) if val is not None else None
        if k and k not in seen:
            seen.add(k)
            out.append(k)

    push(store.get("currentContentId"))
    push(store.get("feedbackContentId"))
    push(store.get("playbackTrackId"))
    push(store.get("lastToken"))
    for entry in store.get("recentTrackListens") or []:
        if not isinstance(entry, dict):
            continue
        push(entry.get("contentId"))
        push(entry.get("trackId"))
        push(entry.get("parentId"))
        if len(out) >= cap:
            return out[:cap]

    has_recent = bool((store.get("recentTrackListens") or []))
    if not has_recent:
        for entry in store.get("playHistory") or []:
            n = _normalize_play_history_entry(entry)
            if n:
                push(n["id"])
            if len(out) >= cap:
                return out[:cap]
    return out[:cap]


def recent_exclude_filters(store: dict, limit: int | None = None) -> dict:
    """Build an exclusion-filters dict for search queries."""
    return {"contentIds": recent_content_ids(store, limit)}


def merge_initial_store(stored: dict | None) -> dict:
    """Merge persisted attributes into DEFAULT_STORE and apply migrations."""
    merged = {**DEFAULT_STORE, **(stored if isinstance(stored, dict) else {})}
    merged["recentTrackListens"] = normalize_recent_track_listens(merged.get("recentTrackListens"))
    return _migrate_playback_fields(merged)


def _playback_fields_for_snapshot(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    tracks = item.get("tracks") or []
    first_track = tracks[0] if tracks else {}
    return {
        "audioUrl": item.get("audioUrl") or first_track.get("audioUrl") or None,
        "playback_speed": item.get("playback_speed") or first_track.get("playback_speed") or None,
        "durationSecs": item.get("durationSecs") if "durationSecs" in item else (first_track.get("durationSecs") if first_track else None),
        "tracks": [{
            "id": first_track.get("id"),
            "audioUrl": first_track.get("audioUrl"),
            "playback_speed": first_track.get("playback_speed"),
            "durationSecs": first_track.get("durationSecs"),
            "title": first_track.get("title"),
        }] if first_track else [],
    }


def _browse_item_snapshot(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    credit = pick_content_credit(item)
    spoken = content_title_for_speech(item)
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "displayTitle": spoken or item.get("displayTitle"),
        "spokenTitle": spoken,
        "creator": credit or item.get("creator"),
        "summary": item.get("summary") or None,
        "category": item.get("category") or None,
        **_playback_fields_for_snapshot(item),
    }


def set_browse_catalog(
    handler_input,
    catalog: dict | None,
    *,
    intent: str | None = None,
    category: str | None = None,
) -> dict:
    """Store a browsable catalog in the session and prepare queue/snapshot data."""

    store = get_store(handler_input)
    raw_items = catalog.get("items", []) if catalog else []
    prev = store.get("browseCatalog")
    same_session = is_same_browse_session(prev, catalog, intent) if prev else False
    has_fresh_spoken_menu = isinstance(catalog.get("spokenMenu"), list) and len(catalog.get("spokenMenu") or []) > 0 if catalog else False

    if same_session:
        sorted_items = merge_browse_items_preserve_order(prev.get("items", []), raw_items) if prev else raw_items
    else:
        sorted_items = raw_items if has_fresh_spoken_menu else sort_queue_items_by_listening_preferences(
            raw_items, store.get("listeningPattern"), store.get("locality")
        )

    browse_ids = [i.get("id") for i in sorted_items if i.get("id")]
    cap = min(len(sorted_items), settings.HEAR_BROWSE_MAX_CATALOG or 50)
    capped = sorted_items[:cap]
    snapshot = [s for s in (_browse_item_snapshot(i) for i in capped) if s is not None]
    queue_cap = min(len(capped), settings.HEAR_QUEUE_PREFETCH_LIMIT or 20)
    browse_queue_items = [clone_browse_menu_item(i) for i in capped[:queue_cap]] if queue_cap else None

    clean = {
        "intent": (catalog.get("intent") if catalog else None) or intent or "general",
        "q": str(catalog.get("q", "")) if catalog else "",
        "categorySlug": catalog.get("categorySlug") or None if catalog else None,
        "tags": catalog.get("tags") or None if catalog else None,
        "limit": (catalog.get("limit") if catalog else None) or settings.search_page_limit,
        "currentPage": (catalog.get("currentPage") if catalog else None) or 0,
        "totalHits": (catalog.get("totalHits") if catalog else None) or len(capped),
        "totalPages": (catalog.get("totalPages") if catalog else None) or 0,
        "spokenOffset": (catalog.get("spokenOffset") if catalog else None) or 0,
        "items": capped,
        "spokenMenu": (catalog.get("spokenMenu") if catalog else None) or [],
    }
    return update_store(handler_input, {
        "browseCatalog": clean,
        "launchBrowseIds": browse_ids or None,
        "pendingDiscoveryIntent": intent or clean.get("intent") or None,
        "pendingDiscoveryCategory": category or None,
        "pendingBrowseItems": snapshot or None,
        "browseQueueItems": browse_queue_items,
    })


def get_browse_catalog(store: dict) -> dict | None:
    """Return the active browse catalog from the store, falling back to pending items."""
    if isinstance(store, dict):
        bc = store.get("browseCatalog")
        if bc and isinstance(bc.get("items"), list) and bc["items"]:
            return bc
        pbi = store.get("pendingBrowseItems")
        if isinstance(pbi, list) and pbi:
            return {
                "intent": store.get("pendingDiscoveryIntent") or "general",
                "q": "",
                "categorySlug": None,
                "tags": None,
                "limit": settings.search_page_limit,
                "currentPage": 0,
                "totalHits": len(pbi),
                "totalPages": 1,
                "spokenOffset": 0,
                "items": pbi,
            }
    return None


def init_queue(
    handler_input,
    items: list,
    *,
    source: str | None = None,
    locality: str | None = None,
    category: str | None = None,
    start_index: int = 0,
) -> dict:
    """Initialise the upcoming playback queue."""
    queue = [clone_queue_item(i) for i in (items or [])]
    return update_store(handler_input, {
        "upcomingQueue": queue,
        "queueIndex": start_index,
        "queueSource": source,
        "queueLocality": locality,
        "queueCategory": category,
        "queueItemsCompleted": 0,
        "awaitingStillListening": False,
    })


def peek_has_next_queue_item(store: dict) -> bool:
    """Return True if there is at least one more item after the current queue index."""
    queue = store.get("upcomingQueue") or []
    idx = store.get("queueIndex") or 0
    return idx + 1 < len(queue)


def append_to_queue(handler_input, items: list) -> dict:
    """Append items to the end of the upcoming queue."""
    store = get_store(handler_input)
    queue = list(store.get("upcomingQueue") or []) + list(items or [])
    return update_store(handler_input, {"upcomingQueue": queue})


def queue_remaining(store: dict) -> int:
    """Return the number of remaining items in the queue after the current index."""
    queue = store.get("upcomingQueue") or []
    idx = store.get("queueIndex") or 0
    return max(0, len(queue) - idx - 1)


def clear_queue(handler_input) -> dict:
    """Empty the queue and reset all queue-related state."""
    return update_store(handler_input, {
        "upcomingQueue": [],
        "queueIndex": 0,
        "queueSource": None,
        "queueLocality": None,
        "queueCategory": None,
        "queueItemsCompleted": 0,
        "awaitingStillListening": False,
    })


def bump_queue_items_completed(handler_input) -> dict:
    """Increment the count of completed queue items."""
    store = get_store(handler_input)
    return update_store(handler_input, {"queueItemsCompleted": (store.get("queueItemsCompleted") or 0) + 1})


def reset_queue_items_completed(handler_input) -> dict:
    """Reset the completed-queue-items counter to zero."""
    return update_store(handler_input, {"queueItemsCompleted": 0})


def _slim_stored_queue_item(item) -> dict | None:
    if not isinstance(item, dict):
        return item
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "spokenTitle": item.get("spokenTitle"),
        "creator": item.get("creator"),
        "creatorId": item.get("creatorId"),
        "category": item.get("category"),
        "type": item.get("type"),
        "locality": item.get("locality"),
        "audioUrl": item.get("audioUrl") or None,
        "playback_speed": item.get("playback_speed") or None,
        "durationSecs": None if "durationSecs" not in item else item.get("durationSecs"),
        "tracks": item.get("tracks") or None,
    }


def build_persisted_snapshot(store: dict) -> dict:
    """Produce a size-optimised copy of *store* for DynamoDB persistence."""
    if not isinstance(store, dict):
        return {}
    snapshot = dict(store)
    for field in _TRANSIENT_OFFLOAD_FIELDS:
        snapshot.pop(field, None)
    if isinstance(snapshot.get("currentTracks"), list):
        snapshot["currentTracks"] = [slim_publication_track(t) for t in snapshot["currentTracks"]]
    if isinstance(snapshot.get("upcomingQueue"), list):
        snapshot["upcomingQueue"] = [_slim_stored_queue_item(i) for i in snapshot["upcomingQueue"]]
    return snapshot


class LoadPersistenceInterceptor:
    """Request interceptor that loads persisted session state into request attributes."""

    @staticmethod
    async def process(handler_input) -> None:

        if getattr(handler_input.request_envelope.request, "type", None) == "CanFulfillIntentRequest":
            handler_input.attributes_manager.request_attributes = {"_store": merge_initial_store({}), "_dirty": False}
            return

        if should_skip_persistence_load(handler_input):
            handler_input.attributes_manager.request_attributes = {"_store": merge_initial_store({}), "_dirty": False}
            return

        reliable_load = requires_reliable_persistence_load(handler_input)
        budget_ms = 0 if reliable_load else persistence_load_budget_ms(handler_input)
        stored: dict = {}
        load_capped = False
        started = int(time.time() * 1000)

        try:
            if budget_ms and budget_ms > 0:
                load_promise = handler_input.attributes_manager.persistent_attributes
                try:
                    stored = await asyncio.wait_for(load_promise, timeout=budget_ms / 1000.0) or {}
                except asyncio.TimeoutError:
                    load_capped = True
                    stored = {}
            else:
                stored = await handler_input.attributes_manager.persistent_attributes or {}
        except Exception:
            stored = {}

        elapsed = int(time.time() * 1000) - started
        store = merge_initial_store(stored)
        handler_input.attributes_manager.request_attributes = {"_store": store, "_dirty": False}


class SavePersistenceInterceptor:
    """Response interceptor that saves the session store to persistent attributes."""

    @staticmethod
    async def process(handler_input) -> None:
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
                    pass
            else:
                await save_promise
        except Exception:
            pass
