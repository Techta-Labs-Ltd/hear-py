from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from config import settings
from src.alexa.browse import Browse
from src.alexa.dialog import DialogStateManager
from src.alexa.help import HelpSpeech
from src.alexa.onboarding import Onboarding
from src.alexa.playback import AlexaPlayback
from src.alexa.playback_speech import PlaybackSpeech
from src.alexa.playback_workflow import Playback
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.playback import PlaybackConstants
from src.models.user import User
from src.services.logging_control import ApplicationLog


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.HelpIntent"
        )

    def handle(self, handler_input: HandlerInput):
        DialogStateManager.activate(handler_input, "help", ttl_seconds=120)
        return (
            handler_input.response_builder.speak(Ssml.ssml(HelpSpeech.BRIEF_GUIDE))
            .reprompt(Ssml.ssml(HelpSpeech.MORE_REPROMPT))
            .with_simple_card(
                HelpSpeech.CARD_TITLE,
                HelpSpeech.card_text(settings.STAGE),
            )
            .set_should_end_session(False)
            .response
        )


class HelpMoreIntentHandler(AbstractRequestHandler):
    """Serve the complete guide before generic next/browse navigation runs."""

    MORE_INTENTS = frozenset({"AMAZON.NextIntent", "ShowMoreBrowseIntent"})

    def can_handle(self, handler_input: HandlerInput) -> bool:
        active = DialogStateManager.get_active(handler_input) or {}
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and active.get("type") == "help"
            and AlexaRequest.get_intent_name(handler_input) in self.MORE_INTENTS
        )

    def handle(self, handler_input: HandlerInput):
        DialogStateManager.clear(handler_input, "help")
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(HelpSpeech.full_guide(settings.STAGE))
            )
            .reprompt(Ssml.ssml(HelpSpeech.REPROMPT))
            .with_simple_card(
                HelpSpeech.CARD_TITLE,
                HelpSpeech.card_text(settings.STAGE),
            )
            .set_should_end_session(False)
            .response
        )


class CancelIntentHandler(AbstractRequestHandler):
    def __init__(self, user: User, playback: Playback) -> None:
        self._user = user
        self._playback = playback

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.CancelIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        DialogStateManager.clear_transient_discovery(handler_input)
        self._user.update(
            handler_input,
            {"awaitingLocationConfirm": False, "pendingLocationConfirm": None},
        )
        try:
            await self._playback.emit_user(
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
    def __init__(self, browse: Browse) -> None:
        self._browse = browse

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "AMAZON.NavigateHomeIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        return await self._browse.content(handler_input)


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
    def __init__(self, playback: Playback) -> None:
        self._playback = playback

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "SessionEndedRequest"

    async def handle(self, handler_input: HandlerInput):
        DialogStateManager.clear_transient_discovery(handler_input)
        try:
            reason = handler_input.request_envelope.request.reason
        except Exception:
            reason = None
        ApplicationLog.info("Session ended: %s", reason)
        try:
            await self._playback.flush_previous(
                AlexaRequest.get_user_id(handler_input) or "", None, handler_input
            )
        except Exception as err:
            ApplicationLog.warning("Hear: SessionEnded flush failed error=%s", type(err).__name__)
        return handler_input.response_builder.response


class UnknownRequestHandler(AbstractRequestHandler):
    def __init__(self, user: User, onboarding: Onboarding) -> None:
        self._user = user
        self._onboarding = onboarding

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
        ApplicationLog.warning("Hear: unmatched request type %s", request_type)
        if request_type == "IntentRequest":
            redirect = Onboarding.onboarding_pending_redirect(
                handler_input, self._user.snapshot(handler_input), self._onboarding
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
            ApplicationLog.error(
                "Hear: System.ExceptionEncountered errorType=%s",
                request.error.type,
            )
        except Exception:
            pass
