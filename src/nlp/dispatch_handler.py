from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from src.services.storage.persistence import update_store
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import ssml, escape_ssml_lite, FALLBACK_SPEECH, WELCOME_REPROMPT
from src.handlers.intents import PlayContentHandler, PlayByCreatorHandler, PlayByOrganizationHandler, BrowseContentHandler, ShowMoreBrowseHandler, WhatsTrendingHandler, TownCaptureHandler, SetLocationHandler
from src.handlers.feedback import FeedbackEnjoyedHandler, FeedbackNotEnjoyedHandler, FeedbackSomewhatHandler, SkipFeedbackHandler

logger = logging.getLogger(__name__)

DISPATCHABLE_INTENTS: list[str] = [
    "trending", "local", "creator", "organization", "category",
    "browse", "show_more", "following", "general",
    "feedback_enjoyed", "feedback_not_enjoyed", "feedback_somewhat", "feedback_skip",
    "town_capture", "location_set", "unclear",
    "resolver_unavailable",
]

# Query-driven intents that are confirmed with the user before any search runs.
# Broad "show me stuff" intents (trending/browse/following/show_more) act
# immediately since there is no specific entity that could be misheard.
NON_DISPATCHABLE_INTENTS: list[str] = [
    "ReportContentIntent", "ReportCreatorIntent",
    "FollowCreatorIntent", "UnfollowCreatorIntent", "WhoIsCreatorIntent", "WhatsThisAboutIntent",
    "EnableNotificationsIntent", "DisableNotificationsIntent",
    "AMAZON.YesIntent", "AMAZON.NoIntent",
    "NavigateHomeIntent",
    "SetPlaybackSpeedIntent", "IncreaseSpeedIntent", "DecreaseSpeedIntent",
    "RewindIntent", "FastForwardIntent",
    "AMAZON.PauseIntent", "AMAZON.ResumeIntent", "AMAZON.NextIntent", "AMAZON.PreviousIntent",
    "AMAZON.RepeatIntent", "AMAZON.StartOverIntent",
    "AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.HelpIntent",
]


class IntentDispatchHandler(AbstractRequestHandler):
    """Request handler that dispatches NLP-classified intents to the appropriate handlers."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        """Check whether this handler can handle the given request."""
        if get_request_type(handler_input) != "IntentRequest":
            return False
        alexa_intent = get_intent_name(handler_input)
        if alexa_intent in NON_DISPATCHABLE_INTENTS:
            return False
        attrs = handler_input.attributes_manager.request_attributes
        nlp_data = attrs.get("_nlp")
        if not nlp_data or not nlp_data.get("intent"):
            return False
        return nlp_data["intent"] in DISPATCHABLE_INTENTS

    def handle(self, handler_input: HandlerInput) -> Response:
        """Dispatch the NLP intent to the appropriate handler."""
        attrs = handler_input.attributes_manager.request_attributes
        nlp_data = attrs.get("_nlp", {})
        intent = nlp_data.get("intent", "general")

        pending = attrs.pop("_pendingConfirmation", None)
        handler_input.attributes_manager.request_attributes = attrs
        if pending:
            return self._ask_search_confirmation(
                handler_input, nlp_data, pending,
            )

        if intent == "unclear":
            return self._handle_unclear(handler_input, nlp_data)
        if intent == "resolver_unavailable":
            return handler_input.response_builder \
                .speak(ssml("I'm having trouble understanding that request right now. Please try again.")) \
                .reprompt(ssml("Please say your request again.")) \
                .set_should_end_session(False) \
                .get_response()

        dispatch_map = {
            "trending": WhatsTrendingHandler,
            "local": PlayContentHandler,
            "creator": PlayByCreatorHandler,
            "organization": PlayByOrganizationHandler,
            "category": PlayContentHandler,
            "browse": BrowseContentHandler,
            "show_more": ShowMoreBrowseHandler,
            "following": PlayContentHandler,
            "general": PlayContentHandler,
            "town_capture": TownCaptureHandler,
            "location_set": SetLocationHandler,
            "feedback_enjoyed": FeedbackEnjoyedHandler,
            "feedback_not_enjoyed": FeedbackNotEnjoyedHandler,
            "feedback_somewhat": FeedbackSomewhatHandler,
            "feedback_skip": SkipFeedbackHandler,
        }

        handler_cls = dispatch_map.get(intent)
        if handler_cls:
            return handler_cls().handle(handler_input)

        return handler_input.response_builder \
            .speak(FALLBACK_SPEECH) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .get_response()

    def _ask_search_confirmation(self, handler_input: HandlerInput, nlp_data: dict, pending: dict) -> Response:
        """Confirm the classified search with the user before running it.

        Stores the pending intent/query/slots so ``YesIntentHandler`` can
        execute the search on confirmation, and ``NoIntentHandler`` can offer
        the alternatives instead.
        """
        confirm_text = pending.get("confirmText")
        update_store(handler_input, {
            "awaitingSearchConfirmation": True,
            "pendingResolution": pending.get("resolution") or {},
            "_requiresReliableSave": True,
        })
        logger.info("Hear: search confirmation asked intent=%s text=%s",
                    pending.get("intent"), confirm_text)
        return handler_input.response_builder \
            .speak(ssml(f"Did you want me to play {escape_ssml_lite(confirm_text)}?")) \
            .reprompt(ssml("Say yes to go ahead, or no for other options.")) \
            .set_should_end_session(False) \
            .get_response()

    def _handle_unclear(self, handler_input: HandlerInput, nlp_data: dict) -> Response:
        """Handle an unclear intent by offering suggestions to the user."""
        suggestions = nlp_data.get("suggestions") or []

        if not suggestions:
            return handler_input.response_builder.speak(
                ssml("Sorry, I didn't catch that. You can say play followed by a topic, what's trending, or play from a creator by name. What would you like?")
            ).reprompt(
                ssml("Try saying what's trending, or play followed by a topic.")
            ).set_should_end_session(False).get_response()

        update_store(handler_input, {"pendingNlpSuggestion": suggestions})

        top = suggestions[0]
        display_text = top.get("displayText") or f"{top['intent']} {top.get('query', '')}".strip()
        msg = f"I didn't quite catch that. Did you mean {escape_ssml_lite(display_text)}?"

        if len(suggestions) > 1:
            second = suggestions[1]
            second_text = second.get("displayText") or f"{second['intent']} {second.get('query', '')}".strip()
            msg += f" Or {escape_ssml_lite(second_text)}?"
            msg += " Say yes for the first one, or no to hear the next."
        else:
            msg += " Say yes to try that, or no to hear more options."

        return handler_input.response_builder.speak(
            ssml(msg)
        ).reprompt(
            ssml("Say yes to confirm, or no to skip.")
        ).set_should_end_session(False).get_response()
