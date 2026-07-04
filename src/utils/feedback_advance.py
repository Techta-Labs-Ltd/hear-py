from __future__ import annotations

from config import settings
from src.services.api import search as api_search
from src.services.persistence import get_store, update_store, append_to_queue, get_browse_catalog
from src.utils.audio import build_play_directive
from src.utils.browse_catalog import catalog_search_context
from src.utils.content_playback import queue_parent_for_token_fallback
from src.utils.feedback_resume import url_at_store_speed
from src.utils.listen_tracker import begin_listen_segment
from src.utils.next_content import build_playback_exclude_set, pick_next_search_item, record_current_playback_for_skip
from src.utils.normalize_content_item import normalize_content_items, content_title_for_speech, pick_content_credit
from src.utils.publication_tracks import has_more_publication_tracks, resolve_publication_track_at_index
from src.utils.search_filters import build_search_filters
from src.utils.session_queue import clone_queue_item
from src.utils.speech import ssml, FEEDBACK_SKIP_INTRO, LOCAL_CONTENT_FALLBACK, NO_CONTENT_AVAILABLE, WELCOME_REPROMPT
from src.utils.queue_advance import play_next_queued_item
from src.utils.queue_refill import maybe_refill_session_queue
from src.utils.playback_start import start_playback


async def _advance_publication_track_play(handler_input, store: dict):
    """Advance to the next track within a multi-track publication."""
    next_index = (store.get("currentTrackIndex") or 0) + 1
    resolved = await resolve_publication_track_at_index(handler_input, store, next_index)
    if not resolved or not resolved["track"].get("audioUrl"):
        return None
    queue_parent = queue_parent_for_token_fallback(store)
    track = resolved["track"]
    token = track.get("id") or f"{queue_parent}:{next_index}"
    play_url = url_at_store_speed(store, track["audioUrl"], track.get("playback_speed"))
    title = track.get("title") or store.get("feedbackContentTitle")
    intro = f"{FEEDBACK_SKIP_INTRO} {LOCAL_CONTENT_FALLBACK(title, pick_content_credit(store))}"
    update_store(handler_input, {
        "currentTrackIndex": next_index,
        "currentTotalTracks": resolved["total"],
        "currentDurationSecs": track["durationSecs"] if isinstance(track.get("durationSecs"), (int, float)) else store.get("currentDurationSecs"),
        "feedbackContentId": token,
        "playbackTrackId": track.get("id") or None,
        "feedbackCategory": track.get("category") if track.get("category") else store.get("feedbackCategory"),
        "feedbackAskedForToken": None,
        "awaitingFeedback": False,
    })
    begin_listen_segment(handler_input, token=token, offset_ms=0)
    return handler_input.response_builder \
        .speak(ssml(intro)) \
        .add_directive(build_play_directive(
            url=play_url, token=token,
            metadata={"title": track.get("title") or "Hear", "subtitle": store.get("feedbackContentTitle") or ""},
            progress_report=True,
            duration_secs=track["durationSecs"] if isinstance(track.get("durationSecs"), (int, float)) else store.get("currentDurationSecs"),
            handler_input=handler_input,
        )) \
        .with_should_end_session(True) \
        .get_response()


async def advance_after_negative_feedback(handler_input):
    """Find and play the next content item after negative feedback or skip."""

    store = get_store(handler_input)

    if has_more_publication_tracks(store):
        response = await _advance_publication_track_play(handler_input, store)
        if response:
            return response

    queued = await play_next_queued_item(handler_input, speak_intro=True, intro_prefix=FEEDBACK_SKIP_INTRO)
    if queued:
        return queued

    store_after_queue = get_store(handler_input)
    await maybe_refill_session_queue(handler_input, store_after_queue)
    retry = await play_next_queued_item(handler_input, speak_intro=True, intro_prefix=FEEDBACK_SKIP_INTRO)
    if retry:
        return retry

    record_current_playback_for_skip(handler_input, store_after_queue)
    catalog = get_browse_catalog(store_after_queue)
    exclude_set = build_playback_exclude_set(store_after_queue)
    queue_parent = queue_parent_for_token_fallback(store_after_queue)

    ctx = catalog_search_context(catalog) if catalog else {"intent": "general", "q": ""}
    payload = build_search_filters(handler_input, store_after_queue, q=ctx.get("q") or "", limit=settings.search_page_limit, page=0)
    payload["filters"] = {
        **(payload.get("filters") or {}),
        "excludeIds": list(dict.fromkeys((payload.get("filters") or {}).get("excludeIds") or [] + list(exclude_set)))[:20],
    }

    result = await api_search(payload)
    next_item = pick_next_search_item(result.get("results") or [], exclude_set, queue_parent)

    if not next_item:
        return handler_input.response_builder \
            .speak(ssml(NO_CONTENT_AVAILABLE)) \
            .reprompt(WELCOME_REPROMPT) \
            .get_response()

    if catalog and result.get("results"):
        fresh_items = [clone_queue_item(i) for i in normalize_content_items(result["results"]) if isinstance(i, dict) and i.get("id") and str(i["id"]) not in exclude_set]
        if fresh_items:
            append_to_queue(handler_input, fresh_items)

    title = content_title_for_speech(next_item)
    credit = pick_content_credit(next_item)
    intro = f"{FEEDBACK_SKIP_INTRO} {LOCAL_CONTENT_FALLBACK(title, credit)}"
    return await start_playback(handler_input, next_item, intro, 0, preserve_session_queue=True)
