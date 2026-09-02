from __future__ import annotations

from ask_sdk_core.handler_input import HandlerInput

from config import settings
from src.alexa.playback import AlexaPlayback
from src.alexa.speech import Speech
from src.constants.playback import PlaybackConstants
from src.models.playback import Playback
from src.utils.playback import PlaybackUtils


class PlaybackControls:
    @staticmethod
    async def restart_active(
        handler_input: HandlerInput,
        *,
        offset_ms: int | None = None,
        speech: str = Speech.RESUMING,
        deps: object | None = None,
    ):
        d = deps
        state = d.playback.state.current(handler_input)
        if not state:
            return Playback.open_queue_response(handler_input, Speech.NOTHING_TO_RESUME)
        resume_state = {
            **state,
            "offsetMs": state.get("offsetMs", 0) if offset_ms is None else offset_ms,
        }
        await d.playback.emit(handler_input, "resumed", resume_state)
        return await d.playback.resume(handler_input, resume_state, speech)

    @staticmethod
    async def _apply_speed(
        handler_input: HandlerInput, speed: float, *, deps: object | None = None
    ):
        d = deps
        store = d.user.snapshot(handler_input)
        state = d.playback.state.current(handler_input)
        variants = store.get("currentPlaybackSpeeds") or []
        if (
            speed != settings.default_speed
            and variants
            and (not PlaybackUtils.find_speed_url(variants, speed))
        ):
            available = ", ".join((f"{value.get('speed')}x" for value in variants))
            return Playback.open_queue_response(
                handler_input, Speech.PLAYBACK_SPEED_UNAVAILABLE(speed, available)
            )
        d.playback.state.set_speed(handler_input, speed)
        if not state or state.get("status") not in PlaybackConstants.ACTIVE_PLAYBACK_STATUSES:
            return Playback.open_queue_response(
                handler_input, Speech.PLAYBACK_SPEED_SET_IDLE(speed)
            )
        return await PlaybackControls.restart_active(
            handler_input,
            offset_ms=state.get("offsetMs", 0),
            speech=Speech.PLAYBACK_SPEED_SET(speed),
            deps=d,
        )

    @staticmethod
    async def _step_speed(
        handler_input: HandlerInput, direction: str, *, deps: object | None = None
    ):
        d = deps
        store = d.user.snapshot(handler_input)
        variants = store.get("currentPlaybackSpeeds") or []
        if not variants:
            return Playback.open_queue_response(handler_input, Speech.PLAYBACK_SPEED_NOT_SUPPORTED)
        value = PlaybackUtils.get_next_speed(
            variants, store.get("playbackSpeed", settings.default_speed), direction
        )
        if not value:
            return Playback.open_queue_response(
                handler_input,
                Speech.PLAYBACK_SPEED_MAX if direction == "up" else Speech.PLAYBACK_SPEED_MIN,
            )
        return await PlaybackControls._apply_speed(handler_input, value["speed"], deps=d)

    @staticmethod
    async def _seek(
        handler_input: HandlerInput,
        direction: int,
        speech: str,
        *,
        deps: object | None = None,
    ):
        d = deps
        state = d.playback.state.current(handler_input)
        if not state:
            return Playback.open_queue_response(handler_input, Speech.CANNOT_SEEK)
        amount = max(1, AlexaPlayback.resolve_seek_ms(handler_input))
        target = max(0, int(state.get("offsetMs", 0)) + direction * amount)
        duration = state.get("durationMs")
        if isinstance(duration, (int, float)):
            target = min(target, max(0, int(duration) - 1000))
        return await PlaybackControls.restart_active(
            handler_input, offset_ms=target, speech=speech, deps=d
        )
