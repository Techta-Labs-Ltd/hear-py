from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.alexa.request import AlexaRequest
from src.models.playback_events import PlaybackEvents
from src.models.playback_state import PlaybackQueue


class PlaybackStartedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackStarted"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        store = self._deps.user.snapshot(handler_input)
        state = self._deps.playback.state.current(handler_input)
        if (
            state
            and state.get("contentId") == token
            and not self._deps.playback.state.accepts_event(handler_input, state)
        ):
            return handler_input.response_builder.response
        prepared = self._deps.playback.state.prepared(store)
        if (
            isinstance(prepared, dict)
            and prepared.get("contentId") == token
            and (not state or state.get("contentId") != token)
        ):
            queue_index = self._deps.playback.queue.set_index_for_content(handler_input, token) or 0
            queue = PlaybackQueue.read(self._deps.user.snapshot(handler_input))
            state = self._deps.playback.start_session(
                handler_input,
                prepared,
                queue_id=queue.get("queueId") if queue else None,
                queue_index=queue_index,
                offset_ms=offset_ms,
            )
            self._deps.playback.state.clear_prepared(handler_input)
        if state and state.get("contentId") == token:
            state = self._deps.playback.observe(
                handler_input,
                offset_ms=offset_ms,
                event_type="started",
                status="playing",
            )
            await self._deps.playback.emit(handler_input, "started", state)
        return handler_input.response_builder.response


class PlaybackNearlyFinishedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackNearlyFinished"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        self._deps.user.snapshot(handler_input)
        state = self._deps.playback.state.current(handler_input)
        if state and not self._deps.playback.state.accepts_event(handler_input, state):
            return handler_input.response_builder.response
        if not state or state.get("contentId") != token:
            return handler_input.response_builder.response
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        if offset_ms <= 0 and int(state.get("offsetMs") or 0) > 0:
            offset_ms = int(state["offsetMs"])
        state = self._deps.playback.observe(
            handler_input,
            offset_ms=offset_ms,
            event_type="nearly_finished",
            status="playing",
        )
        await self._deps.playback.emit(handler_input, "nearly_finished", state)
        return await self._deps.playback.enqueue_next_queued_content(
            handler_input, token, self._deps.heara
        )


class PlaybackFinishedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps
        self._events = PlaybackEvents(deps=deps)

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackFinished"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        await self._events.finish(handler_input, token, offset_ms)
        return handler_input.response_builder.response


class PlaybackStoppedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackStopped"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        state = self._deps.playback.state.current(handler_input)
        if state and not self._deps.playback.state.accepts_event(handler_input, state):
            return handler_input.response_builder.response
        if state and state.get("contentId") == token:
            state = self._deps.playback.observe(
                handler_input,
                offset_ms=offset_ms,
                event_type="stopped",
                status="paused",
            )
            await self._deps.playback.emit(handler_input, "stopped", state)
        return handler_input.response_builder.response


class PlaybackFailedHandler(AbstractRequestHandler):
    logger = logging.getLogger(__name__)

    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackFailed"

    async def handle(self, handler_input):
        request = handler_input.request_envelope.request
        token = request.token
        state = self._deps.playback.state.current(handler_input)
        if state and not self._deps.playback.state.accepts_event(handler_input, state):
            return handler_input.response_builder.response
        if state and state.get("contentId") == token:
            state = self._deps.playback.observe(
                handler_input,
                offset_ms=int(state.get("offsetMs") or 0),
                event_type="failed",
                status="failed",
            )
            await self._deps.playback.emit(handler_input, "failed", state)
            self._deps.playback.state.clear_prepared(handler_input)
        self.logger.warning("Hear audio playback failed contentId=%s", token)
        return handler_input.response_builder.response


class PlaybackProgressReportHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) in {
            "AudioPlayer.PlaybackProgressReportDelayPassed",
            "AudioPlayer.PlaybackProgressReportIntervalPassed",
        }

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        state = self._deps.playback.state.current(handler_input)
        if state and not self._deps.playback.state.accepts_event(handler_input, state):
            return handler_input.response_builder.response
        if (
            state
            and state.get("contentId") == token
            and (state.get("status") in {"starting", "playing", "paused"})
        ):
            state = self._deps.playback.observe(
                handler_input,
                offset_ms=offset_ms,
                event_type="progress",
                status="playing",
            )
            await self._deps.playback.emit(handler_input, "progress", state)
        return handler_input.response_builder.response
