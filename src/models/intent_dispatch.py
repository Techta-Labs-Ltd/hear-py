from __future__ import annotations

import logging
import time

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from src.alexa.context import RequestContext
from src.alexa.entities import AlexaEntities
from src.alexa.playback import AlexaPlayback
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.discovery import DiscoveryConstants
from src.models.dialog import DialogStateManager
from src.models.feedback_response import (
    EnjoyedFeedback,
    NotEnjoyedFeedback,
    SkipFeedback,
    SomewhatFeedback,
)
from src.models.onboarding import SetLocation, TownCapture
from src.models.play import PlayContent, PlayCreator, PlayOrganization


class IntentDispatcher:
    logger = logging.getLogger(__name__)
    DISPATCHABLE_INTENTS = frozenset(
        {
            "trending",
            "local",
            "location",
            "creator",
            "creator_location",
            "organization",
            "publication",
            "category",
            "browse",
            "show_more",
            "following",
            "general",
            "search",
            "dismiss_choices",
            "idle_dismiss",
            "stop",
            "feedback_enjoyed",
            "feedback_not_enjoyed",
            "feedback_somewhat",
            "feedback_skip",
            "town_capture",
            "location_set",
            "unclear",
            "resolver_unavailable",
        }
    )
    NON_DISPATCHABLE_INTENTS = frozenset(
        {
            "ReportContentIntent",
            "ReportCreatorIntent",
            "FollowCreatorIntent",
            "UnfollowCreatorIntent",
            "WhoIsCreatorIntent",
            "WhatsThisAboutIntent",
            "RateContentIntent",
            "HearNotificationsIntent",
            "EnableNotificationsIntent",
            "DisableNotificationsIntent",
            "AMAZON.YesIntent",
            "AMAZON.NoIntent",
            "NavigateHomeIntent",
            "SetPlaybackSpeedIntent",
            "IncreaseSpeedIntent",
            "DecreaseSpeedIntent",
            "RewindIntent",
            "FastForwardIntent",
            "AMAZON.PauseIntent",
            "AMAZON.ResumeIntent",
            "AMAZON.NextIntent",
            "AMAZON.PreviousIntent",
            "AMAZON.RepeatIntent",
            "AMAZON.StartOverIntent",
            "AMAZON.StopIntent",
            "AMAZON.CancelIntent",
            "AMAZON.HelpIntent",
        }
    )
    ACTIONS = {
        "creator": PlayCreator,
        "organization": PlayOrganization,
        "publication": PlayContent,
        "category": PlayContent,
        "following": PlayContent,
        "general": PlayContent,
        "search": PlayContent,
        "town_capture": TownCapture,
        "location_set": SetLocation,
        "feedback_enjoyed": EnjoyedFeedback,
        "feedback_not_enjoyed": NotEnjoyedFeedback,
        "feedback_somewhat": SomewhatFeedback,
        "feedback_skip": SkipFeedback,
    }

    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_dispatch(self, handler_input: HandlerInput) -> bool:
        if AlexaRequest.get_request_type(handler_input) != "IntentRequest":
            return False
        alexa_intent = AlexaRequest.get_intent_name(handler_input)
        if alexa_intent in self.NON_DISPATCHABLE_INTENTS:
            return False
        nlp_data = RequestContext.request(handler_input).get("_nlp")
        if not nlp_data:
            return False
        if nlp_data.get("status") == "ambiguous" or (nlp_data.get("slots") or {}).get("ambiguousReferences"):
            return True
        return bool(nlp_data.get("intent") in self.DISPATCHABLE_INTENTS)

    def dispatch(self, handler_input: HandlerInput) -> Response:
        attrs = RequestContext.request(handler_input)
        nlp_data = attrs.get("_nlp", {})
        intent = nlp_data.get("intent", "general")
        clarification = attrs.pop("_resolverClarification", None)
        if clarification:
            return self._clarification_response(handler_input, attrs, intent, clarification)
        pending = attrs.pop("_pendingConfirmation", None)
        RequestContext.replace_request(handler_input, attrs)
        if pending:
            return self._confirmation_response(handler_input, nlp_data, pending)
        if nlp_data.get("status") == "ambiguous" or (nlp_data.get("slots") or {}).get("ambiguousReferences"):
            return self._ambiguity_response(handler_input, nlp_data)
        if intent == "dismiss_choices":
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.CHOICES_DISMISSED))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if intent == "idle_dismiss":
            return AlexaResponse.present_idle_next(
                handler_input,
                f"Ok. {Speech.WELCOME_REPROMPT}",
                Speech.WELCOME_REPROMPT,
            )
        if intent == "stop":
            DialogStateManager.clear_transient_discovery(handler_input)
            return (
                handler_input.response_builder.speak(Speech.GOODBYE)
                .add_directive(AlexaPlayback.build_stop_directive())
                .response
            )
        if intent == "unclear":
            return self._unclear_response(handler_input, nlp_data)
        if intent == "resolver_unavailable":
            return self._resolver_unavailable_response(handler_input)
        if intent == "trending":
            return self._deps.browse.trending(handler_input)
        if intent == "browse":
            return self._deps.browse.content(handler_input)
        if intent == "show_more":
            return self._deps.browse.more(handler_input)
        if intent in {"local", "location"}:
            return self._deps.availability.begin_local(handler_input, nlp_data)
        if intent == "creator_location":
            return self._deps.availability.begin_creator_location(handler_input, nlp_data)
        action_type = self.ACTIONS.get(intent)
        if action_type:
            return action_type(deps=self._deps).execute(handler_input)
        return self._fallback_response(handler_input)

    def _ambiguity_response(self, handler_input: HandlerInput, nlp_data: dict) -> Response:
        ambiguities = nlp_data.get("ambiguities") or (nlp_data.get("slots") or {}).get("ambiguousReferences") or []
        reference = ambiguities[0] if ambiguities else {}
        phrase = str(reference.get("phrase") or "").strip() or "that request"
        candidates = list(reference.get("candidates") or [])
        displayed = candidates[: DiscoveryConstants.CHOICE_PAGE_SIZE]
        has_more = len(candidates) > DiscoveryConstants.CHOICE_PAGE_SIZE
        now = int(time.time())
        pending = {
            "phrase": phrase,
            "candidates": candidates,
            "choiceCandidates": candidates,
            "displayedCandidates": displayed,
            "spokenCandidateOffset": min(DiscoveryConstants.CHOICE_PAGE_SIZE, len(candidates)),
            "offset": 0,
            "intent": nlp_data.get("intent") or "general",
            "searchPayload": dict(nlp_data.get("searchPayload") or {}),
            "slots": dict(nlp_data.get("slots") or {}),
            "createdAt": now,
            "expiresAt": now + 300,
        }
        self._deps.user.update(
            handler_input,
            {
                "pendingAmbiguity": pending,
                "awaitingLocationConfirm": False,
                "pendingLocationConfirm": None,
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.activate(handler_input, "ambiguity", context=pending)
        message = SearchSpeech.ambiguous_reference_message(phrase, displayed, has_more=has_more)
        reprompt = SearchSpeech.choice_reprompt(displayed, has_more=has_more)
        builder = (
            handler_input.response_builder.speak(Ssml.ssml(message))
            .reprompt(Ssml.ssml(reprompt))
            .set_should_end_session(False)
        )
        directive = AlexaEntities.build_ambiguity_dynamic_entities_directive(displayed)
        if directive:
            builder.add_directive(directive)
        return builder.response

    def _clarification_response(
        self, handler_input: HandlerInput, attrs: dict, intent: str, clarification: dict
    ) -> Response:
        attrs.pop("_pendingConfirmation", None)
        RequestContext.replace_request(handler_input, attrs)
        self.logger.info("Hear: resolver discovery clarification asked intent=%s", intent)
        builder = (
            handler_input.response_builder.speak(Ssml.ssml(clarification["speech"]))
            .reprompt(Ssml.ssml(clarification["reprompt"]))
            .set_should_end_session(False)
        )
        if clarification.get("elicitSlot"):
            builder.add_directive(
                {"type": "Dialog.ElicitSlot", "slotToElicit": clarification["elicitSlot"]}
            )
        return builder.response

    def _confirmation_response(
        self, handler_input: HandlerInput, nlp_data: dict, pending: dict
    ) -> Response:
        confirm_text = pending.get("confirmText")
        resolution = pending.get("resolution") or {}
        self._deps.user.update(
            handler_input,
            {
                "awaitingSearchConfirmation": True,
                "pendingResolution": resolution,
                "awaitingCommunityPlayback": False,
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.activate(
            handler_input,
            "search_confirmation",
            context={**resolution, "confirmationLabel": confirm_text},
        )
        self.logger.info(
            "Hear: search confirmation asked intent=%s text=%s",
            pending.get("intent"),
            confirm_text,
        )
        escaped = Speech.escape_ssml_lite(pending.get("ambiguityCandidateName") or confirm_text)
        prompt = (
            f"Did you mean {escaped}?"
            if pending.get("ambiguityResolution")
            else f"Did you want me to play {escaped}?"
        )
        prompt = f"{prompt} Please say yes or no."
        return (
            handler_input.response_builder.speak(Ssml.ssml(prompt))
            .reprompt(Ssml.ssml(prompt))
            .set_should_end_session(False)
            .response
        )

    def _unclear_response(self, handler_input: HandlerInput, nlp_data: dict) -> Response:
        suggestions = nlp_data.get("suggestions") or []
        if not suggestions:
            return self._missing_suggestion_response(handler_input)
        self._deps.user.update(handler_input, {"pendingNlpSuggestion": suggestions})
        message = (
            f"I didn't quite catch that. Did you mean {self._suggestion_label(suggestions[0])}?"
        )
        if len(suggestions) > 1:
            message += f" Or {self._suggestion_label(suggestions[1])}?"
            message += " Say yes for the first one, or no to hear the next."
        else:
            message += " Say yes to try that, or no to hear more options."
        return (
            handler_input.response_builder.speak(Ssml.ssml(message))
            .reprompt(Ssml.ssml("Say yes to confirm, or no to skip."))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def _suggestion_label(suggestion: dict) -> str:
        label = suggestion.get("displayText") or (
            f"{suggestion['intent']} {suggestion.get('query', '')}".strip()
        )
        return Speech.escape_ssml_lite(label)

    @staticmethod
    def _missing_suggestion_response(handler_input: HandlerInput) -> Response:
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(Speech.FALLBACK_SPEECH)
            )
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def _resolver_unavailable_response(handler_input: HandlerInput) -> Response:
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(
                    "I'm having trouble understanding that request right now. "
                    f"{Speech.WELCOME_REPROMPT}"
                )
            )
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def _fallback_response(handler_input: HandlerInput) -> Response:
        return (
            handler_input.response_builder.speak(Speech.FALLBACK_SPEECH)
            .reprompt(Speech.WELCOME_REPROMPT)
            .set_should_end_session(False)
            .response
        )

