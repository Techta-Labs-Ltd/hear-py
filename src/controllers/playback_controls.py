from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from config import settings
from src.alexa.playback_speech import PlaybackSpeech
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.constants.playback import PlaybackConstants
from src.models.dialog import DialogStateManager
from src.models.playback import Playback
from src.models.playback_controls import PlaybackControls
from src.utils.playback import PlaybackUtils


class SetPlaybackSpeedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "SetPlaybackSpeedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        intent = handler_input.request_envelope.request.intent
        slot = ((intent.get("slots") if intent else None) or {}).get("speed")
        speed = (
            settings.default_speed
            if slot is None
            else PlaybackUtils.normalise_speed(AlexaRequest.get_resolved_slot_value(slot))
        )
        if speed is None:
            return Playback.open_queue_response(handler_input, PlaybackSpeech.SPEED_INVALID)
        return await PlaybackControls._apply_speed(handler_input, speed, deps=self._deps)


class IncreaseSpeedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "IncreaseSpeedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await PlaybackControls._step_speed(handler_input, "up", deps=self._deps)


class DecreaseSpeedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "DecreaseSpeedIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await PlaybackControls._step_speed(handler_input, "down", deps=self._deps)


class PauseIntentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        request_type = AlexaRequest.get_request_type(handler_input)
        return request_type == PlaybackConstants.CONTROLLER_REQUESTS["PAUSE"] or (
            request_type == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input)
            in ("AMAZON.PauseIntent", "AMAZON.StopIntent")
        )

    async def handle(self, handler_input: HandlerInput):
        if (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.StopIntent"
        ):
            DialogStateManager.clear_transient_discovery(handler_input)
            directive = await PlaybackControls.pause_active(handler_input, deps=self._deps)
            return (
                handler_input.response_builder.speak(Speech.GOODBYE)
                .add_directive(directive)
                .response
            )
        directive = await PlaybackControls.pause_active(handler_input, deps=self._deps)
        return handler_input.response_builder.add_directive(
            directive
        ).response


class ResumeIntentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        request_type = AlexaRequest.get_request_type(handler_input)
        return request_type == PlaybackConstants.CONTROLLER_REQUESTS["PLAY"] or (
            request_type == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.ResumeIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await PlaybackControls.restart_active(handler_input, deps=self._deps)


class NextIntentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        request_type = AlexaRequest.get_request_type(handler_input)
        return request_type == PlaybackConstants.CONTROLLER_REQUESTS["NEXT"] or (
            request_type == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input)
            in ("AMAZON.NextIntent", "AMAZON.SkipIntent")
        )

    async def handle(self, handler_input: HandlerInput):
        return await Playback.play_queue_delta(
            handler_input, 1, PlaybackSpeech.PLAYING_NEXT, deps=self._deps
        )


class PreviousIntentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        request_type = AlexaRequest.get_request_type(handler_input)
        return request_type == PlaybackConstants.CONTROLLER_REQUESTS["PREVIOUS"] or (
            request_type == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.PreviousIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await Playback.play_queue_delta(
            handler_input, -1, PlaybackSpeech.PLAYING_PREVIOUS, deps=self._deps
        )


class RepeatIntentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return AlexaRequest.get_request_type(
            handler_input
        ) == "IntentRequest" and AlexaRequest.get_intent_name(handler_input) in (
            "AMAZON.RepeatIntent",
            "AMAZON.StartOverIntent",
        )

    async def handle(self, handler_input: HandlerInput):
        return await PlaybackControls.restart_active(
            handler_input, offset_ms=0, speech=PlaybackSpeech.REPLAYING, deps=self._deps
        )


class RewindIntentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "RewindIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await PlaybackControls._seek(handler_input, -1, deps=self._deps)


class FastForwardIntentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "FastForwardIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await PlaybackControls._seek(handler_input, 1, deps=self._deps)
