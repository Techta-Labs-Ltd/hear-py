from __future__ import annotations
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from src.services.playback import emit_listening_event
from src.services.playback import (
    create_playback_session,
    read_playback_session,
    write_playback_session,
)
from src.services.queue import read_playback_queue, set_queue_index_for_content
from src.services.store import get_store, update_store
from src.utils.skill_request import (
    get_audio_player_offset_ms,
    get_audio_player_token,
    get_request_type,
)
from src.dependencies import Dependencies
from src.services.queue import cached_queue_content
from src.utils.audio import (
    build_content_metadata,
    build_play_directive,
    resolve_audio_url_for_speed,
)
from config import settings
from src.utils.skill_request import (
    get_user_id,
)
from src.services.feedback import (
    activate_best_feedback_candidate,
    record_feedback_candidate,
)
from src.utils.normalize_content_item import pick_content_source
import logging

logger = logging.getLogger(__name__)


async def _enqueue_next_queued_content(handler_input, token: str, deps: Dependencies):
    """Prepare the next queue item early; repeated AudioPlayer events are harmless."""
    store = get_store(handler_input)
    state = read_playback_session(store)
    if not state or state.get("contentId") != token:
        return handler_input.response_builder.response
    queue = read_playback_queue(store)
    if not queue:
        return handler_input.response_builder.response
    next_index = int(queue.get("currentIndex") or 0) + 1
    if next_index >= len(queue["orderedContentIds"]):
        return handler_input.response_builder.response
    next_id = queue["orderedContentIds"][next_index]
    prepared = store.get("preparedNextContent")
    if isinstance(prepared, dict) and prepared.get("contentId") == next_id:
        logger.info(
            "Hear: queue item already prepared current=%s next=%s index=%s",
            token, next_id, next_index,
        )
        return handler_input.response_builder.response
    content = cached_queue_content(store, next_id)
    if not content:
        result = await deps.heara.search({
            "query": "",
            "filter": {"contentIds": [next_id]},
            "page": 0,
            "limit": 1,
            "alexaUserId": get_user_id(handler_input),
        })
        if not result.get("results"):
            logger.warning(
                "Hear: queue prefetch found no content current=%s next=%s index=%s",
                token, next_id, next_index,
            )
            return handler_input.response_builder.response
        content = result["results"][0]
    update_store(handler_input, {"preparedNextContent": content})
    playback_speeds = content.get("playbackSpeeds") or []
    audio_url = resolve_audio_url_for_speed(
        content["audioUrl"],
        store.get("playbackSpeed", settings.default_speed),
        playback_speeds,
    )
    directive = build_play_directive(
        url=audio_url,
        token=content["contentId"],
        prev_token=token,
        metadata=build_content_metadata(content),
        progress_report=True,
        duration_secs=(
            content["durationMs"] / 1000
            if isinstance(content.get("durationMs"), (int, float))
            else None
        ),
    )
    logger.info(
        "Hear: queue item enqueued current=%s next=%s index=%s",
        token, next_id, next_index,
    )
    return handler_input.response_builder.add_directive(directive).response

class PlaybackStartedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackStarted"

    async def handle(self, handler_input):
        token = get_audio_player_token(handler_input)
        offset_ms = get_audio_player_offset_ms(handler_input)
        store = get_store(handler_input)
        state = read_playback_session(store)
        prepared = store.get("preparedNextContent")
        if (
            isinstance(prepared, dict)
            and prepared.get("contentId") == token
            and (not state or state.get("contentId") != token)
        ):
            queue_index = set_queue_index_for_content(handler_input, token) or 0
            queue = read_playback_queue(get_store(handler_input))
            state = create_playback_session(
                handler_input,
                prepared,
                queue_id=queue.get("queueId") if queue else None,
                queue_index=queue_index,
                offset_ms=offset_ms,
            )
            update_store(handler_input, {"preparedNextContent": None})
        if state and state.get("contentId") == token:
            state = write_playback_session(handler_input, {
                "status": "playing",
                "offsetMs": offset_ms,
                "listenedMs": max(int(state.get("listenedMs") or 0), offset_ms),
            })
            update_store(handler_input, {
                "lastToken": token,
                "lastOffsetMs": offset_ms,
            })
            await emit_listening_event(handler_input, "started", state)
        return handler_input.response_builder.response

class PlaybackNearlyFinishedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackNearlyFinished"

    async def handle(self, handler_input):
        token = get_audio_player_token(handler_input)
        store = get_store(handler_input)
        state = read_playback_session(store)
        if not state or state.get("contentId") != token:
            return handler_input.response_builder.response
        await emit_listening_event(handler_input, "nearly_finished", state)
        return await _enqueue_next_queued_content(
            handler_input, token, self._deps,
        )

class PlaybackFinishedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackFinished"

    async def handle(self, handler_input):
        token = get_audio_player_token(handler_input)
        offset_ms = get_audio_player_offset_ms(handler_input)
        state = read_playback_session(get_store(handler_input))
        if state and state.get("contentId") == token:
            duration_ms = int(state.get("durationMs") or 0)
            listened_ms = max(
                int(state.get("listenedMs") or 0),
                offset_ms,
                duration_ms,
            )
            state = write_playback_session(handler_input, {
                "status": "completed",
                "offsetMs": max(offset_ms, duration_ms),
                "listenedMs": listened_ms,
            })
            source = {
                "contentId": state.get("contentId"),
                "organizationId": state.get("organizationId"),
                "organizationName": state.get("organizationName"),
                "creatorId": state.get("creatorId"),
                "creatorName": state.get("creatorName"),
                "completedAt": state.get("updatedAt"),
            }
            selected_source = pick_content_source(source)
            if selected_source:
                source.update({
                    "sourceKind": selected_source["kind"],
                    "sourceId": selected_source["id"],
                    "sourceName": selected_source["name"],
                })
                update_store(handler_input, {"lastCompletedSource": source})
            record_feedback_candidate(handler_input, state, completed=True)
            # AudioPlayer events cannot speak, but activating now guarantees
            # the next foreground interaction asks about this completed track.
            activate_best_feedback_candidate(handler_input)
            await emit_listening_event(handler_input, "finished", state)
            queue = read_playback_queue(get_store(handler_input))
            has_prepared_next = bool(get_store(handler_input).get("preparedNextContent"))
            if (
                queue
                and not has_prepared_next
                and int(queue.get("currentIndex") or 0)
                < len(queue["orderedContentIds"]) - 1
            ):
                logger.warning(
                    "Hear: queue could not advance because Alexa sent PlaybackFinished "
                    "without an accepted PlaybackNearlyFinished enqueue token=%s index=%s total=%s",
                    token,
                    queue.get("currentIndex"),
                    len(queue["orderedContentIds"]),
                )
        return handler_input.response_builder.response

class PlaybackStoppedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackStopped"

    async def handle(self, handler_input):
        token = get_audio_player_token(handler_input)
        offset_ms = get_audio_player_offset_ms(handler_input)
        state = read_playback_session(get_store(handler_input))
        if state and state.get("contentId") == token:
            state = write_playback_session(handler_input, {
                "status": "paused",
                "offsetMs": offset_ms,
                "listenedMs": max(int(state.get("listenedMs") or 0), offset_ms),
            })
            update_store(handler_input, {"lastOffsetMs": offset_ms, "lastToken": token})
            await emit_listening_event(handler_input, "stopped", state)
        return handler_input.response_builder.response

class PlaybackFailedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) == "AudioPlayer.PlaybackFailed"

    async def handle(self, handler_input):
        request = handler_input.request_envelope.request
        token = request.token
        state = read_playback_session(get_store(handler_input))
        if state and state.get("contentId") == token:
            state = write_playback_session(handler_input, {"status": "failed"})
            await emit_listening_event(handler_input, "failed", state)
            update_store(handler_input, {"preparedNextContent": None})
        logger.warning("Hear audio playback failed contentId=%s", token)
        return handler_input.response_builder.response

class PlaybackProgressReportHandler(AbstractRequestHandler):
    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input) -> bool:
        return get_request_type(handler_input) in {
            "AudioPlayer.PlaybackProgressReportDelayPassed",
            "AudioPlayer.PlaybackProgressReportIntervalPassed",
        }

    async def handle(self, handler_input):
        token = get_audio_player_token(handler_input)
        offset_ms = get_audio_player_offset_ms(handler_input)
        state = read_playback_session(get_store(handler_input))
        if state and state.get("contentId") == token and state.get("status") in {
            "starting", "playing", "paused",
        }:
            listened_ms = max(int(state.get("listenedMs") or 0), offset_ms)
            state = write_playback_session(handler_input, {
                "offsetMs": offset_ms,
                "listenedMs": listened_ms,
                "status": "playing",
            })
            update_store(handler_input, {
                "lastOffsetMs": offset_ms,
                "lastToken": token,
            })
            await emit_listening_event(handler_input, "progress", state)
        return handler_input.response_builder.response
