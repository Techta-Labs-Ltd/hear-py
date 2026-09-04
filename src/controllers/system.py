from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from config import settings
from src.alexa.help import HelpSpeech
from src.alexa.playback import AlexaPlayback
from src.alexa.playback_speech import PlaybackSpeech
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.playback import PlaybackConstants
from src.models.dialog import DialogStateManager
from src.models.onboarding import Onboarding


class SystemControllerSupport:
    logger = logging.getLogger(__name__)


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.HelpIntent"
        )

    def handle(self, handler_input: HandlerInput):
        return (
            handler_input.response_builder.speak(Ssml.ssml(HelpSpeech.guide(settings.STAGE)))
            .reprompt(Ssml.ssml(HelpSpeech.REPROMPT))
            .with_simple_card(
                HelpSpeech.CARD_TITLE,
                HelpSpeech.card_text(settings.STAGE),
            )
            .set_should_end_session(False)
            .response
        )


class CancelIntentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.CancelIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        DialogStateManager.clear_transient_discovery(handler_input)
        self._deps.user.update(
            handler_input,
            {"awaitingLocationConfirm": False, "pendingLocationConfirm": None},
        )
        try:
            await self._deps.playback.emit_user(
                handler_input,
                {
                    "eventType": PlaybackConstants.USER_PLAYBACK_EVENT_TYPES["CANCELLED"],
                    "eventLabel": "CANCELLED",
                    "suppressFollowingStopped": True,
                    "closeSegment": True,
                },
            )
        except Exception:
            pass
        return (
            handler_input.response_builder.speak(Speech.GOODBYE)
            .add_directive(AlexaPlayback.build_stop_directive())
            .response
        )


class NavigateHomeHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.NavigateHomeIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._deps.browse.content(handler_input)


class UnsupportedIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return AlexaRequest.get_request_type(
            handler_input
        ) == "IntentRequest" and AlexaRequest.get_intent_name(handler_input) in {
            "AMAZON.LoopOnIntent",
            "AMAZON.LoopOffIntent",
            "AMAZON.ShuffleOnIntent",
            "AMAZON.ShuffleOffIntent",
        }

    def handle(self, handler_input: HandlerInput):
        return (
            handler_input.response_builder.speak(PlaybackSpeech.LOOP_SHUFFLE_UNAVAILABLE)
            .reprompt(Speech.WELCOME_REPROMPT)
            .set_should_end_session(False)
            .response
        )


class SessionEndedHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "SessionEndedRequest"

    async def handle(self, handler_input: HandlerInput):
        DialogStateManager.clear_transient_discovery(handler_input)
        try:
            reason = handler_input.request_envelope.request.reason
        except Exception:
            reason = None
        SystemControllerSupport.logger.info("Session ended: %s", reason)
        try:
            await self._deps.playback.flush_previous(
                AlexaRequest.get_user_id(handler_input), None, handler_input
            )
        except Exception as err:
            SystemControllerSupport.logger.warning("Hear: SessionEnded flush failed %s", err)
        return handler_input.response_builder.response


class UnknownRequestHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return True

    def handle(self, handler_input: HandlerInput):
        try:
            request_type = handler_input.request_envelope.request.type
        except Exception:
            request_type = "unknown"
        if request_type == "SessionEndedRequest":
            return {}
        if isinstance(request_type, str) and request_type.startswith("AudioPlayer."):
            return {}
        if request_type == "System.ExceptionEncountered":
            self._log_system_exception(handler_input)
            return {}
        SystemControllerSupport.logger.warning("Hear: unmatched request type %s", request_type)
        if request_type == "IntentRequest":
            redirect = Onboarding.onboarding_pending_redirect(
                handler_input, self._deps.user.snapshot(handler_input), deps=self._deps
            )
            if redirect is not None:
                return redirect
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.ERROR_GENERIC))
            .reprompt(Speech.WELCOME_REPROMPT)
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def _log_system_exception(handler_input: HandlerInput) -> None:
        try:
            request = handler_input.request_envelope.request
            SystemControllerSupport.logger.error(
                "Hear: System.ExceptionEncountered token=%s errorType=%s errorMessage=%s",
                request.token,
                request.error.type,
                request.error.message,
            )
        except Exception:
            pass
