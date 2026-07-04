from __future__ import annotations

from src.services.api import search as api_search
from src.services.persistence import get_store, update_store, bump_queue_items_completed
from src.utils.audio import resolve_track_audio
from src.utils.lambda_deadline import has_budget_for_api
from src.utils.next_content import build_playback_exclude_set
from src.utils.normalize_content_item import content_title_for_speech, pick_content_credit
from src.utils.queue_refill import maybe_refill_session_queue
from src.utils.session_queue import resolve_queue_item_for_playback
from src.utils.speech import LOCAL_CONTENT_FALLBACK
from src.utils.playback_start import start_playback


async def play_next_queued_item(handler_input, *, speak_intro: bool = True, intro_prefix: str | None = None):
    """Play the next item in the session queue, refilling if needed."""

    await maybe_refill_session_queue(handler_input, get_store(handler_input))

    store = get_store(handler_input)
    queue = store.get("upcomingQueue") or []
    q_idx = store.get("queueIndex") or 0
    next_idx = q_idx + 1

    if next_idx >= len(queue):
        await maybe_refill_session_queue(handler_input, get_store(handler_input))
        store = get_store(handler_input)
        queue = store.get("upcomingQueue") or []
        q_idx = store.get("queueIndex") or 0
        next_idx = q_idx + 1

    exclude_set = build_playback_exclude_set(store, include_future_queue=False)

    while next_idx < len(queue):
        raw = queue[next_idx]
        if isinstance(raw, dict) and raw.get("id") and str(raw["id"]) in exclude_set:
            next_idx += 1
            continue

        content = await resolve_queue_item_for_playback(raw)
        if not content:
            next_idx += 1
            continue

        track_info = resolve_track_audio(content, 0)
        if not track_info or not track_info["audioUrl"]:
            next_idx += 1
            continue

        store_snap = get_store(handler_input)
        snapshot = next(
            (i for i in (store_snap.get("pendingBrowseItems") or [])
             if isinstance(i, dict) and i.get("id") == (content.get("id") or (raw.get("id") if isinstance(raw, dict) else None))),
            raw if (isinstance(raw, dict) and (raw.get("spokenTitle") or raw.get("displayTitle") or raw.get("title"))) else None,
        )
        if snapshot:
            content = {
                **content,
                "spokenTitle": snapshot.get("spokenTitle") or content.get("spokenTitle"),
                "displayTitle": snapshot.get("displayTitle") or content.get("displayTitle"),
                "title": snapshot.get("displayTitle") or snapshot.get("title") or content.get("title"),
                "creator": snapshot.get("creator") or content.get("creator"),
                "summary": snapshot.get("summary") or content.get("summary"),
            }

        update_store(handler_input, {"queueIndex": next_idx})
        bump_queue_items_completed(handler_input)

        title = (
            content_title_for_speech(content)
            or (raw.get("spokenTitle") if isinstance(raw, dict) else None)
            or (raw.get("displayTitle") if isinstance(raw, dict) else None)
            or (raw.get("title") if isinstance(raw, dict) else None)
        )
        credit = pick_content_credit(content) or (raw.get("creator") if isinstance(raw, dict) else None)
        intro = LOCAL_CONTENT_FALLBACK(title, credit) if speak_intro else ""
        if intro_prefix and intro:
            intro = f"{intro_prefix} {intro}"
        elif intro_prefix:
            intro = intro_prefix

        return await start_playback(handler_input, content, intro, 0, preserve_session_queue=True)

    return None
