from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import time
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler,
    AbstractExceptionHandler,
)
from ask_sdk_core.handler_input import HandlerInput
from src.services.store import get_store, update_store
from src.utils.skill_request import get_user_id as get_alexa_user_id
from src.services.playback import flush_previous_track
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml,
    HELP,
    GOODBYE,
    IDLE_DO_NEXT_REPROMPT,
    WELCOME_REPROMPT,
    ERROR_GENERIC,
    LOOP_SHUFFLE_UNAVAILABLE,
)
from src.utils.audio import build_stop_directive
from src.services.playback import emit_user_playback_event, USER_PLAYBACK_EVENT_TYPES
from src.handlers.onboarding import onboarding_pending_redirect
from src.handlers.browse import BrowseContentHandler
from src.services.observability import (
    capture_skill_exception,
    flush_sentry,
    last_resort_skill_response,
)
from src.services.dialog_state import clear_active_dialog
def _current_timestamp_ms() -> int:
    """Return current UTC time in milliseconds."""
    return int(time.time() * 1000)


class HelpIntentHandler(AbstractRequestHandler):
    """Provides help guidance to the user."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.HelpIntent"
        )

    def handle(self, handler_input: HandlerInput):
        return handler_input.response_builder \
            .speak(ssml(HELP)) \
            .reprompt(ssml(IDLE_DO_NEXT_REPROMPT)) \
            .set_should_end_session(False) \
            .response


class CancelIntentHandler(AbstractRequestHandler):
    """Stops playback and ends the session."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.CancelIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        update_store(handler_input, {
            "pendingAmbiguity": None,
            "awaitingLocationConfirm": False,
            "pendingLocationConfirm": None,
        })
        clear_active_dialog(handler_input, "ambiguity")
        try:
            await emit_user_playback_event(handler_input, {
                "eventType": USER_PLAYBACK_EVENT_TYPES["CANCELLED"],
                "eventLabel": "CANCELLED",
                "suppressFollowingStopped": True,
                "closeSegment": True,
            })
        except Exception:
            pass

        return handler_input.response_builder \
            .speak(GOODBYE) \
            .add_directive(build_stop_directive()) \
            .response


class NavigateHomeHandler(AbstractRequestHandler):
    """Routes NavigateHome to browse content."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.NavigateHomeIntent"
        )

    def handle(self, handler_input: HandlerInput):
        return BrowseContentHandler().handle(handler_input)


class UnsupportedIntentHandler(AbstractRequestHandler):
    """Handles unsupported intents (loop/shuffle)."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) in (
                "AMAZON.LoopOnIntent", "AMAZON.LoopOffIntent",
                "AMAZON.ShuffleOnIntent", "AMAZON.ShuffleOffIntent",
            )
        )

    def handle(self, handler_input: HandlerInput):
        return handler_input.response_builder \
            .speak(LOOP_SHUFFLE_UNAVAILABLE) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response


class SessionEndedHandler(AbstractRequestHandler):
    """Handles SessionEndedRequest — flushes state on session close."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "SessionEndedRequest"

    async def handle(self, handler_input: HandlerInput):
        reason = None
        try:
            reason = handler_input.request_envelope.request.reason
        except Exception:
            pass
        logger.info("Session ended: %s", reason)
        try:
            await flush_previous_track(get_alexa_user_id(handler_input), None, handler_input)
        except Exception as err:
            logger.warning("Hear: SessionEnded flush failed %s", err)
        return handler_input.response_builder.response


class UnknownRequestHandler(AbstractRequestHandler):
    """Ultimate catch-all for any request type not otherwise handled."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return True

    def handle(self, handler_input: HandlerInput):
        try:
            rt = handler_input.request_envelope.request.type
        except Exception:
            rt = "unknown"

        if rt == "SessionEndedRequest":
            return {}
        if isinstance(rt, str) and rt.startswith("AudioPlayer."):
            return {}
        if rt == "System.ExceptionEncountered":
            try:
                req = handler_input.request_envelope.request
                logger.error(
                    "Hear: System.ExceptionEncountered token=%s errorType=%s errorMessage=%s",
                    req.token, req.error.type, req.error.message,
                )
            except Exception:
                pass
            return {}

        logger.warning("Hear: unmatched request type %s", rt)
        if rt == "IntentRequest":
            redirect = onboarding_pending_redirect(
                handler_input, get_store(handler_input),
            )
            if redirect is not None:
                return redirect
        return handler_input.response_builder \
            .speak(ssml(ERROR_GENERIC)) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response


class ErrorHandler(AbstractExceptionHandler):
    """Global exception handler — flushes state, logs to Sentry, returns generic error."""

    def can_handle(self, handler_input: HandlerInput, exception: Exception) -> bool:
        return True

    async def handle(self, handler_input: HandlerInput, exception: Exception):
        try:
            try:
                await flush_previous_track(get_alexa_user_id(handler_input), None, handler_input)
            except Exception as flush_err:
                logger.warning("Hear: ErrorHandler flush failed %s", flush_err)

            try:
                capture_skill_exception(handler_input, exception)
                await flush_sentry(2000)
            except Exception as cap_err:
                logger.warning("Hear: captureSkillException failed %s", cap_err)

            logger.error(
                "Unhandled error: requestType=%s intent=%s message=%s",
                get_request_type(handler_input), get_intent_name(handler_input), exception,
            )

            if get_request_type(handler_input) == "SessionEndedRequest":
                return {}

            rt = get_request_type(handler_input)
            if isinstance(rt, str) and rt.startswith("AudioPlayer."):
                return {}

            if handler_input and hasattr(handler_input, "response_builder"):
                return handler_input.response_builder \
                    .speak(ERROR_GENERIC) \
                    .reprompt(ERROR_GENERIC) \
                    .set_should_end_session(False) \
                    .response
        except Exception as inner:
            logger.error("Hear: ErrorHandler failed %s", inner)

        try:
            return last_resort_skill_response()
        except Exception:
            return {}
