from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.alexa.context import RequestContext
from src.alexa.notifications import AlexaNotificationAdapter
from src.alexa.playback_events import PlaybackEventCommand, PlaybackEvents
from src.alexa.playback_workflow import Playback
from src.alexa.request import AlexaRequest
from src.models.search_contracts import CatalogueSearchGateway
from src.services.logging_control import ApplicationLog


class PlaybackStartedHandler(AbstractRequestHandler):
    def __init__(self, events: PlaybackEvents, notifications: AlexaNotificationAdapter) -> None:
        self._events = events
        self._notifications = notifications

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackStarted"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        receipt = await self._events.apply(
            RequestContext.bind(handler_input),
            PlaybackEventCommand("started", token, offset_ms),
        )
        if receipt.notify_started:
            await self._notifications.playback_started(handler_input, token)
        return handler_input.response_builder.response


class PlaybackNearlyFinishedHandler(AbstractRequestHandler):
    def __init__(self, events: PlaybackEvents, playback: Playback, heara: CatalogueSearchGateway) -> None:
        self._events = events
        self._playback = playback
        self._heara = heara

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackNearlyFinished"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        receipt = await self._events.apply(
            RequestContext.bind(handler_input),
            PlaybackEventCommand("nearly_finished", token, offset_ms),
        )
        if not receipt.enqueue_next:
            return handler_input.response_builder.response
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
        await self._events.apply(
            RequestContext.bind(handler_input),
            PlaybackEventCommand("finished", token, offset_ms),
        )
        return handler_input.response_builder.response


class PlaybackStoppedHandler(AbstractRequestHandler):
    def __init__(self, events: PlaybackEvents) -> None:
        self._events = events

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackStopped"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        await self._events.apply(
            RequestContext.bind(handler_input),
            PlaybackEventCommand("stopped", token, offset_ms),
        )
        return handler_input.response_builder.response


class PlaybackFailedHandler(AbstractRequestHandler):

    def __init__(self, events: PlaybackEvents, notifications: AlexaNotificationAdapter) -> None:
        self._events = events
        self._notifications = notifications

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "AudioPlayer.PlaybackFailed"

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        receipt = await self._events.apply(
            RequestContext.bind(handler_input),
            PlaybackEventCommand("failed", token),
        )
        if receipt.notify_failed:
            await self._notifications.playback_failed(handler_input, token)
        ApplicationLog.warning("Hear audio playback failed tokenPresent=%s", bool(token))
        return handler_input.response_builder.response


class PlaybackProgressReportHandler(AbstractRequestHandler):
    def __init__(self, events: PlaybackEvents) -> None:
        self._events = events

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) in {
            "AudioPlayer.PlaybackProgressReportDelayPassed",
            "AudioPlayer.PlaybackProgressReportIntervalPassed",
        }

    async def handle(self, handler_input):
        token = AlexaRequest.get_audio_player_token(handler_input)
        offset_ms = AlexaRequest.get_audio_player_offset_ms(handler_input)
        await self._events.apply(
            RequestContext.bind(handler_input),
            PlaybackEventCommand("progress", token, offset_ms),
        )
        return handler_input.response_builder.response
