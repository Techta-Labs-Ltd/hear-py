"""Foreground playback controls for the canonical content queue."""
from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.utils.request_util import get_slot_value

from config import settings
from src.services.api import search
from src.services.playback.session import read_playback_session, write_playback_session
from src.services.playback.start import start_playback
from src.services.queue.state import move_queue
from src.services.storage.persistence import get_store, update_store
from src.utils.audio import (
    build_stop_directive,
    find_speed_url,
    get_next_speed,
    normalise_speed,
    resolve_seek_ms,
)
from src.utils.skill_request import get_intent_name, get_request_type
from src.utils.speech import (
    CANNOT_SEEK,
    FAST_FORWARDED,
    NO_CONTENT_AVAILABLE,
    NO_PREVIOUS,
    NOTHING_TO_RESUME,
    PLAYBACK_SPEED_INVALID,
    PLAYBACK_SPEED_MAX,
    PLAYBACK_SPEED_MIN,
    PLAYBACK_SPEED_NOT_SUPPORTED,
    PLAYBACK_SPEED_SET,
    PLAYBACK_SPEED_UNAVAILABLE,
    PLAYING_PREVIOUS,
    REPLAYING,
    RESUMING,
    REWOUND,
    WELCOME_REPROMPT,
    ssml,
)

PLAYBACK_CONTROLLER = {
    "PAUSE": "PlaybackController.PauseCommandIssued",
    "PLAY": "PlaybackController.PlayCommandIssued",
    "NEXT": "PlaybackController.NextCommandIssued",
    "PREVIOUS": "PlaybackController.PreviousCommandIssued",
}


def _open_response(handler_input: HandlerInput, speech: str):
    return (
        handler_input.response_builder.speak(ssml(speech))
        .reprompt(ssml(WELCOME_REPROMPT))
        .set_should_end_session(False)
        .response
    )


async def _find_content(content_id: str) -> dict | None:
    result = await search({
        "query": "",
        "filter": {"contentIds": [content_id]},
        "page": 0,
        "limit": 1,
    })
    return next(
        (item for item in result.get("results", []) if item.get("contentId") == content_id),
        None,
    )


async def _restart_active(
    handler_input: HandlerInput,
    *,
    offset_ms: int | None = None,
    speech: str = RESUMING,
):
    state = read_playback_session(get_store(handler_input))
    if not state:
        return _open_response(handler_input, NOTHING_TO_RESUME)
    content = await _find_content(state["contentId"])
    if not content:
        return _open_response(handler_input, NO_CONTENT_AVAILABLE)
    return await start_playback(
        handler_input,
        content,
        speech,
        options={"offsetMs": state.get("offsetMs", 0) if offset_ms is None else offset_ms},
    )


async def _play_queue_delta(handler_input: HandlerInput, delta: int, speech: str):
    content_id = move_queue(handler_input, delta)
    if not content_id:
        return _open_response(
            handler_input,
            NO_PREVIOUS if delta < 0 else NO_CONTENT_AVAILABLE,
        )
    content = await _find_content(content_id)
    if not content:
        # Restore the queue cursor when resolution fails.
        move_queue(handler_input, -delta)
        return _open_response(handler_input, NO_CONTENT_AVAILABLE)
    return await start_playback(handler_input, content, speech)


async def _apply_speed(handler_input: HandlerInput, speed: float):
    store = get_store(handler_input)
    state = read_playback_session(store)
    variants = store.get("currentPlaybackSpeeds") or []
    if variants and not find_speed_url(variants, speed):
        available = ", ".join(f"{value.get('speed')}x" for value in variants)
        return _open_response(handler_input, PLAYBACK_SPEED_UNAVAILABLE(speed, available))
    update_store(handler_input, {"playbackSpeed": speed})
    if not state:
        return _open_response(handler_input, PLAYBACK_SPEED_SET(speed))
    return await _restart_active(
        handler_input,
        offset_ms=state.get("offsetMs", 0),
        speech=PLAYBACK_SPEED_SET(speed),
    )


class SetPlaybackSpeedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "SetPlaybackSpeedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        raw = get_slot_value(handler_input, "speed")
        speed = settings.default_speed if not raw else normalise_speed(raw)
        if speed is None:
            return _open_response(handler_input, PLAYBACK_SPEED_INVALID)
        return await _apply_speed(handler_input, speed)


async def _step_speed(handler_input: HandlerInput, direction: str):
    store = get_store(handler_input)
    variants = store.get("currentPlaybackSpeeds") or []
    if not variants:
        return _open_response(handler_input, PLAYBACK_SPEED_NOT_SUPPORTED)
    value = get_next_speed(
        variants,
        store.get("playbackSpeed", settings.default_speed),
        direction,
    )
    if not value:
        return _open_response(
            handler_input,
            PLAYBACK_SPEED_MAX if direction == "up" else PLAYBACK_SPEED_MIN,
        )
    return await _apply_speed(handler_input, value["speed"])


class IncreaseSpeedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "IncreaseSpeedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await _step_speed(handler_input, "up")


class DecreaseSpeedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "DecreaseSpeedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await _step_speed(handler_input, "down")


class PauseIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        request_type = get_request_type(handler_input)
        return request_type == PLAYBACK_CONTROLLER["PAUSE"] or (
            request_type == "IntentRequest"
            and get_intent_name(handler_input) in ("AMAZON.PauseIntent", "AMAZON.StopIntent")
        )

    def handle(self, handler_input: HandlerInput):
        write_playback_session(handler_input, {"status": "paused"})
        return handler_input.response_builder.add_directive(build_stop_directive()).response


class ResumeIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        request_type = get_request_type(handler_input)
        return request_type == PLAYBACK_CONTROLLER["PLAY"] or (
            request_type == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.ResumeIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await _restart_active(handler_input)


class NextIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        request_type = get_request_type(handler_input)
        return request_type == PLAYBACK_CONTROLLER["NEXT"] or (
            request_type == "IntentRequest"
            and get_intent_name(handler_input) in ("AMAZON.NextIntent", "AMAZON.SkipIntent")
        )

    async def handle(self, handler_input: HandlerInput):
        return await _play_queue_delta(handler_input, 1, "Playing the next recording.")


class PreviousIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        request_type = get_request_type(handler_input)
        return request_type == PLAYBACK_CONTROLLER["PREVIOUS"] or (
            request_type == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.PreviousIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await _play_queue_delta(handler_input, -1, PLAYING_PREVIOUS)


class RepeatIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) in ("AMAZON.RepeatIntent", "AMAZON.StartOverIntent")
        )

    async def handle(self, handler_input: HandlerInput):
        return await _restart_active(handler_input, offset_ms=0, speech=REPLAYING)


async def _seek(handler_input: HandlerInput, direction: int, speech: str):
    state = read_playback_session(get_store(handler_input))
    if not state:
        return _open_response(handler_input, CANNOT_SEEK)
    amount = max(1, resolve_seek_ms(handler_input))
    target = max(0, int(state.get("offsetMs", 0)) + direction * amount)
    duration = state.get("durationMs")
    if isinstance(duration, (int, float)):
        target = min(target, max(0, int(duration) - 1000))
    return await _restart_active(handler_input, offset_ms=target, speech=speech)


class RewindIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "RewindIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await _seek(handler_input, -1, REWOUND)


class FastForwardIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "FastForwardIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await _seek(handler_input, 1, FAST_FORWARDED)
