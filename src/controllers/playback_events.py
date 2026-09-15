from __future__ import annotations

from src.services.logging_control import ApplicationLog

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.alexa.request import AlexaRequest
from src.clients.hear import HearApiClient
from src.models.notifications import Notification
from src.models.playback import Playback
from src.models.playback_events import PlaybackEvents
from src.models.user import User


class PlaybackStartedHandler(AbstractRequestHandler):
    def __init__(self, playback: Playback, user: User, notifications: Notification) -> None:
        self._playback = playback
        self._user = user
        self._notifications = notifications

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackStarted"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        store = self._user.snapshot(handler_input)
        state = self._playback.state.current(handler_input)
        if (
            state
            and state.get("contentId") == token
            and not self._playback.state.accepts_event(handler_input, state)
        ):
            return handler_input.response_builder.response
        prepared = self._playback.state.prepared(store)
        if (
            isinstance(prepared, dict)
            and prepared.get("contentId") == token
            and (not state or state.get("contentId") != token)
        ):
            queue_index = self._playback.queue.set_index_for_content(handler_input, token) or 0
            queue = self._playback.queue.read(self._user.snapshot(handler_input))
            state = self._playback.start_session(
                handler_input,
                prepared,
                queue_id=queue.get("queueId") if queue else None,
                queue_index=queue_index,
                offset_ms=offset_ms,
            )
            self._playback.state.clear_prepared(handler_input)
        if state and state.get("contentId") == token:
            state = self._playback.observe(
                handler_input,
                offset_ms=offset_ms,
                event_type="started",
                status="playing",
            )
            await self._playback.emit(handler_input, "started", state)
            await self._notifications.playback_started(handler_input, token)
        return handler_input.response_builder.response


class PlaybackNearlyFinishedHandler(AbstractRequestHandler):
    def __init__(self, playback: Playback, heara: HearApiClient) -> None:
        self._playback = playback
        self._heara = heara

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackNearlyFinished"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        state = self._playback.state.current(handler_input)
        if state and not self._playback.state.accepts_event(handler_input, state):
            return handler_input.response_builder.response
        if not state or state.get("contentId") != token:
            return handler_input.response_builder.response
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        if offset_ms <= 0 and int(state.get("offsetMs") or 0) > 0:
            offset_ms = int(state["offsetMs"])
        state = self._playback.observe(
            handler_input,
            offset_ms=offset_ms,
            event_type="nearly_finished",
            status="playing",
        )
        await self._playback.emit(handler_input, "nearly_finished", state)
        return await self._playback.enqueue_next_queued_content(
            handler_input, token, self._heara
        )


class PlaybackFinishedHandler(AbstractRequestHandler):
    def __init__(self, events: PlaybackEvents) -> None:
        self._events = events

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackFinished"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        await self._events.finish(handler_input, token, offset_ms)
        return handler_input.response_builder.response


class PlaybackStoppedHandler(AbstractRequestHandler):
    def __init__(self, playback: Playback) -> None:
        self._playback = playback

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackStopped"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        state = self._playback.state.current(handler_input)
        if state and not self._playback.state.accepts_event(handler_input, state):
            return handler_input.response_builder.response
        if state and state.get("contentId") == token:
            state = self._playback.observe(
                handler_input,
                offset_ms=offset_ms,
                event_type="stopped",
                status="paused",
            )
            await self._playback.emit(handler_input, "stopped", state)
        return handler_input.response_builder.response


class PlaybackFailedHandler(AbstractRequestHandler):

    def __init__(self, playback: Playback, notifications: Notification) -> None:
        self._playback = playback
        self._notifications = notifications

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackFailed"

    async def handle(self, handler_input):
        request = handler_input.request_envelope.request
        token = request.token
        state = self._playback.state.current(handler_input)
        if state and not self._playback.state.accepts_event(handler_input, state):
            return handler_input.response_builder.response
        if state and state.get("contentId") == token:
            state = self._playback.observe(
                handler_input,
                offset_ms=int(state.get("offsetMs") or 0),
                event_type="failed",
                status="failed",
            )
            await self._playback.emit(handler_input, "failed", state)
            await self._notifications.playback_failed(handler_input, token)
            self._playback.state.clear_prepared(handler_input)
        ApplicationLog.warning("Hear audio playback failed contentId=%s", token)
        return handler_input.response_builder.response


class PlaybackProgressReportHandler(AbstractRequestHandler):
    def __init__(self, playback: Playback) -> None:
        self._playback = playback

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) in {
            "AudioPlayer.PlaybackProgressReportDelayPassed",
            "AudioPlayer.PlaybackProgressReportIntervalPassed",
        }

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        state = self._playback.state.current(handler_input)
        if state and not self._playback.state.accepts_event(handler_input, state):
            return handler_input.response_builder.response
        if (
            state
            and state.get("contentId") == token
            and (state.get("status") in {"starting", "playing", "paused"})
        ):
            state = self._playback.observe(
                handler_input,
                offset_ms=offset_ms,
                event_type="progress",
                status="playing",
            )
            await self._playback.emit(handler_input, "progress", state)
        return handler_input.response_builder.response
