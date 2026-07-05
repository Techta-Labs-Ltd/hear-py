"""
System-level handlers: Help, Cancel, Yes/No state machine, NavigateHome,
Unsupported intents, SessionEnded, Fallback, Unmatched, Unknown, and Error handler.

Contains 11 handlers:
- HelpIntentHandler          - CancelIntentHandler        - YesIntentHandler
- NoIntentHandler            - NavigateHomeHandler        - UnsupportedIntentHandler
- SessionEndedHandler        - FallbackHandler            - UnmatchedIntentHandler
- UnknownRequestHandler      - ErrorHandler (AbstractExceptionHandler)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractExceptionHandler
from ask_sdk_core.handler_input import HandlerInput

from config import settings

from src.services.persistence import (
    get_store, update_store, clear_queue, clear_feedback, reset_queue_items_completed,
)
from src.services.alexa_api_client import get_alexa_user_id
from src.services.flush_previous_track import flush_previous_track
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml, escape_ssml_lite, is_bad_credit, HELP, GOODBYE, IDLE_DO_NEXT_REPROMPT,
    WELCOME_REPROMPT, ERROR_GENERIC, FALLBACK_SPEECH, LOOP_SHUFFLE_UNAVAILABLE,
    FLAGGED_CONTINUE_YES_ACK, NO_CONTENT_AVAILABLE, CONFIRM_NO, CONFIRM_NO_MATCH,
    NOTIFICATIONS_ENABLE_FAILED, NOTIFICATIONS_ENABLED, NOTIFICATIONS_DECLINED,
    FEEDBACK_FOLLOW_DECLINED, FOLLOW_CREATOR_NOTIFICATION_DECLINED,
    FOLLOW_NOTIFICATION_DECLINED_GENERIC, ASK_LISTEN_FIRST, ASK_LISTEN_NEXT,
    END_OF_LIST, NO_TRACKS_AVAILABLE, QUEUE_FINISHED, QUEUE_NEXT_ANNOUNCE,
    LOCATION_ASK_CITY, LOCATION_CONFIRMED, LOCATION_DECLINED, LOCATION_RETRY,
)
from src.services.api import save_location
from src.handlers.intents.onboarding import ONBOARDING_ASK_TOWN
from src.utils.audio import build_stop_directive
from src.utils.playback_user_events import emit_user_playback_event, USER_PLAYBACK_EVENT_TYPES
from src.utils.feedback_gate import enforce_interaction_gate
from src.utils.feedback_flow import idle_next_response
from src.handlers.notifications import (
    has_notification_permission, complete_notification_opt_in,
    build_notification_permission_response,
)
from src.utils.playback_start import start_playback
from src.webhooks.notification_webhook import mark_all_tracks_announced
from src.webhooks.settings import get_settings
from src.utils.session_queue import resolve_queue_item_for_playback
from src.handlers.intents.play import PlayByCreatorHandler
from src.handlers.intents.play import PlayByOrganizationHandler
from src.handlers.intents.play import PlayContentHandler
from src.handlers.intents.play import BrowseContentHandler
from src.handlers.feedback.enjoyed import FeedbackEnjoyedHandler
from src.handlers.intents.social import FollowCreatorHandler
from src.handlers.intents.play import discover_content_via_search, auto_play_first_from_search
from src.handlers.intents.play import WhatsTrendingHandler
from src.handlers.intents.play import ShowMoreBrowseHandler
from src.handlers.feedback.not_enjoyed import FeedbackNotEnjoyedHandler
from src.handlers.intents.playback import NextIntentHandler
from src.handlers.feedback.skip import SkipFeedbackHandler
from src.services.sentry import capture_skill_exception, flush_sentry, last_resort_skill_response

logger = logging.getLogger(__name__)


def _current_timestamp_ms() -> int:
    """Return current UTC time in milliseconds."""
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Help, Cancel
# ---------------------------------------------------------------------------


class HelpIntentHandler(AbstractRequestHandler):
    """Provides help guidance to the user."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.HelpIntent"
        )

    def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated
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


# ---------------------------------------------------------------------------
# YesIntentHandler (state machine)
# ---------------------------------------------------------------------------


class YesIntentHandler(AbstractRequestHandler):
    """State-machine based Yes handler.

    Routes the Yes intent based on the current store/session state:
    1. awaitingSearchConfirmation  -> execute confirmed search
    2. listModeActive              -> play current list item
    3. awaitingNotificationChoice  -> queue pending notifications
    4. awaitingStillListening      -> advance queue
    5. awaitingContinueAfterFlag   -> acknowledge continue
    6. awaitingFeedback            -> delegate to FeedbackEnjoyed
    7. awaitingFollow              -> delegate to FollowCreator
    8. awaitingNotificationOptIn   -> complete opt-in
    9. pendingNlpSuggestion        -> confirm NLP suggestion
    Fallback                       -> generic welcome reprompt
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.YesIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = get_store(handler_input)
        session_attrs = handler_input.attributes_manager.get_session_attributes() or {}

        # 0a. Location onboarding choice — user agrees to give their city
        if store.get("awaitingLocationChoice"):
            update_store(handler_input, {
                "onboardingStage": ONBOARDING_ASK_TOWN,
                "onboardingTownAttempts": 0,
                "awaitingLocationChoice": False,
            })
            return handler_input.response_builder \
                .speak(ssml(LOCATION_ASK_CITY)) \
                .reprompt(ssml(LOCATION_ASK_CITY)) \
                .set_should_end_session(False) \
                .response

        # 0b. Location confirmation — user confirms the town to save
        if store.get("awaitingLocationConfirm"):
            return await self._confirm_location(handler_input, store)

        # 1. Search confirmation
        if store.get("awaitingSearchConfirmation") or session_attrs.get("awaitingSearchConfirmation"):
            return await self._handle_search_confirmation(handler_input, store, session_attrs)

        # 2. List mode active
        if store.get("listModeActive"):
            return await self._handle_list_mode_yes(handler_input, store)

        # 3. Notification choice pending
        if store.get("awaitingNotificationChoice"):
            return await self._handle_notification_choice(handler_input, store)

        # 4. Still listening prompt
        if store.get("awaitingStillListening"):
            return await self._handle_still_listening_yes(handler_input, store)

        # 5. Awaiting continue after flag
        if store.get("awaitingContinueAfterFlag"):
            update_store(handler_input, {"awaitingContinueAfterFlag": False})
            return handler_input.response_builder \
                .speak(ssml(FLAGGED_CONTINUE_YES_ACK)) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response

        # 6. Awaiting feedback
        if store.get("awaitingFeedback"):
            return await FeedbackEnjoyedHandler().handle(handler_input)

        # 7. Awaiting follow
        if store.get("awaitingFollow"):
            return await FollowCreatorHandler().handle(handler_input)

        # 8. Awaiting notification opt-in
        if store.get("awaitingNotificationOptIn"):
            return await self._handle_notification_opt_in(handler_input)

        # 9. Pending NLP suggestion confirmation
        if store.get("pendingNlpSuggestion") and store["pendingNlpSuggestion"]:
            return await self._confirm_nlp_suggestion(handler_input, store)

        # Fallback
        return handler_input.response_builder \
            .speak(WELCOME_REPROMPT) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response

    async def _confirm_location(self, handler_input, store):
        """Confirm and persist the pending location, calling the backend to save it."""
        pending = store.get("pendingLocationConfirm") or {}
        city = pending.get("city")
        if not city:
            update_store(handler_input, {
                "awaitingLocationConfirm": False,
                "pendingLocationConfirm": None,
                "onboardingStage": None,
            })
            return handler_input.response_builder \
                .speak(ssml(LOCATION_RETRY)) \
                .set_should_end_session(False) \
                .response

        user_id = get_alexa_user_id(handler_input)
        resolved = None
        if user_id:
            try:
                resolved = await save_location(user_id, city)
            except Exception as err:
                logger.warning("Hear: save_location failed %s", err)

        final_city = (resolved.get("city") if resolved else None) or city
        update_store(handler_input, {
            "userCity": final_city,
            "locality": (resolved.get("locality") if resolved else None) or final_city,
            "userState": resolved.get("state") if resolved else None,
            "userCountry": resolved.get("country") if resolved else None,
            "latitude": resolved.get("latitude") if resolved else None,
            "longitude": resolved.get("longitude") if resolved else None,
            "onboardingComplete": True,
            "onboardingStage": None,
            "locationSource": "manual",
            "localityResolvedAt": _current_timestamp_ms(),
            "awaitingLocationConfirm": False,
            "pendingLocationConfirm": None,
        })
        return handler_input.response_builder \
            .speak(ssml(LOCATION_CONFIRMED(final_city))) \
            .reprompt(ssml(IDLE_DO_NEXT_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    async def _handle_search_confirmation(self, handler_input, store, session_attrs):
        """Execute a pending search that was awaiting user confirmation."""
        intent = store.get("pendingSearchIntent") or session_attrs.get("pendingSearchIntent")
        query = store.get("pendingSearchQuery") or session_attrs.get("pendingSearchQuery")
        suggestion_idx = store.get("suggestionIndex") or session_attrs.get("suggestionIndex", 0)
        suggestions = (
            store.get("pendingSuggestions") if store.get("pendingSuggestions") and store["pendingSuggestions"]
            else session_attrs.get("pendingSuggestions", [])
        )
        pending_slots = (
            store.get("pendingSearchSlots") if store.get("pendingSearchSlots") and store["pendingSearchSlots"]
            else session_attrs.get("pendingSearchSlots")
        )

        using_alternative = False
        if suggestion_idx > 0 and suggestion_idx < len(suggestions):
            alt = suggestions[suggestion_idx]
            intent = alt.get("intent") or intent
            query = alt.get("query") or query
            using_alternative = True

        update_store(handler_input, {
            "awaitingSearchConfirmation": False,
            "pendingSearchIntent": None,
            "pendingSearchQuery": None,
            "pendingSearchSlots": {},
            "pendingSuggestions": [],
            "suggestionIndex": 0,
            "excludedSuggestions": [],
        })
        handler_input.attributes_manager.set_session_attributes({})

        if intent:
            effective_query = query or ""
            if not using_alternative and pending_slots and isinstance(pending_slots, dict):
                r_attrs = handler_input.attributes_manager.get_request_attributes()
                r_attrs["_nlp"] = {
                    "intent": intent,
                    "alexaIntent": intent,
                    "slots": pending_slots,
                    "confidence": "high",
                    "nlpMatchesAlexa": True,
                    "needsRedirect": False,
                }
                handler_input.attributes_manager.set_request_attributes(r_attrs)
                effective_query = ""

            logger.info("Hear: YesIntentHandler search START intent=%s q=%s", intent, effective_query)

            search_result = await discover_content_via_search(handler_input, {
                "q": effective_query, "intent": intent,
            })

            logger.info("Hear: YesIntentHandler search DONE hits=%s",
                         len(search_result.get("results", [])))

            if search_result and search_result.get("results"):
                response = await auto_play_first_from_search(handler_input, search_result, {
                    "discoveryIntent": "PlayContentIntent",
                    "q": effective_query,
                })
                if response:
                    return response

            return handler_input.response_builder \
                .speak(ssml(f"I couldn't find any {effective_query or intent} tracks. Try a different category or name.")) \
                .response

        return handler_input.response_builder \
            .speak(WELCOME_REPROMPT) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response

    async def _handle_list_mode_yes(self, handler_input, store):
        """Play the current item in list mode."""
        queue = store.get("listQueue") or store.get("upcomingQueue") or []
        pos = store.get("listPosition") or 0
        item = queue[pos] if pos < len(queue) else None

        if not item:
            update_store(handler_input, {"listModeActive": False})
            return handler_input.response_builder \
                .speak(ssml(NO_TRACKS_AVAILABLE)) \
                .response

        update_store(handler_input, {"listModeActive": False})
        await clear_feedback(handler_input)

        return await start_playback(handler_input, item, "", 0)

    async def _handle_notification_choice(self, handler_input, store):
        """Queue pending notification tracks and optionally auto-play."""

        tracks = store.get("pendingNotificationQueue") or []
        track_ids = [t.get("trackId") for t in tracks if t.get("trackId")]
        queue = list(store.get("upcomingQueue") or [])
        for t in reversed(tracks):
            queue.insert(0, t)

        update_store(handler_input, {
            "upcomingQueue": queue,
            "awaitingNotificationChoice": False,
            "pendingNotificationQueue": None,
        })
        mark_all_tracks_announced(track_ids, get_alexa_user_id(handler_input))

        settings_data = await get_settings()
        auto_play = settings_data.get("autoPlay", True)

        if auto_play:
            resolved = await resolve_queue_item_for_playback(tracks[0])
            if resolved:
                return await start_playback(handler_input, resolved, "", 0)

        update_store(handler_input, {
            "listModeActive": True,
            "listPosition": 0,
            "listQueue": queue[:50],
        })
        first = tracks[0]
        list_text = ASK_LISTEN_FIRST(
            first.get("title", "this track"),
            first.get("creator", "unknown"),
            first.get("category", "general"),
            first.get("organisation", "Hear"),
        )
        return handler_input.response_builder \
            .speak(ssml(list_text)) \
            .reprompt(ssml("Would you like to listen, or say next to skip?")) \
            .set_should_end_session(False) \
            .response

    async def _handle_still_listening_yes(self, handler_input, store):
        """Continue playing after the still-listening prompt."""
        update_store(handler_input, {
            "awaitingStillListening": False,
            "awaitingContinueAfterFlag": False,
        })
        reset_queue_items_completed(handler_input)

        queue = store.get("upcomingQueue") or []
        idx = store.get("queueIndex", 0)
        next_idx = idx + 1

        if next_idx >= len(queue):
            clear_queue(handler_input)
            return handler_input.response_builder \
                .speak(ssml(QUEUE_FINISHED)) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response

        raw = queue[next_idx]
        update_store(handler_input, {"queueIndex": next_idx})

        content = await resolve_queue_item_for_playback(raw)
        if not content:
            clear_queue(handler_input)
            return handler_input.response_builder \
                .speak(ssml(NO_CONTENT_AVAILABLE)) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response

        total = len(queue)
        intro = QUEUE_NEXT_ANNOUNCE(
            content.get("title"),
            content.get("creator"),
            next_idx + 1,
            total,
        )
        return await start_playback(handler_input, content, intro, 0, {"preserveSessionQueue": True})

    async def _handle_notification_opt_in(self, handler_input):
        """Complete the notification opt-in flow."""
        if not has_notification_permission(handler_input):
            return build_notification_permission_response(handler_input)

        result = await complete_notification_opt_in(handler_input)
        if not result.get("ok"):
            return handler_input.response_builder \
                .speak(ssml(NOTIFICATIONS_ENABLE_FAILED)) \
                .reprompt(ssml(IDLE_DO_NEXT_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        return handler_input.response_builder \
            .speak(ssml(NOTIFICATIONS_ENABLED())) \
            .reprompt(ssml(IDLE_DO_NEXT_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    async def _confirm_nlp_suggestion(self, handler_input, store):
        """Confirm and execute a pending NLP suggestion."""
        suggestions = store.get("pendingNlpSuggestion") or []
        top = suggestions[0] if suggestions else None

        if not top:
            return handler_input.response_builder \
                .speak(ssml("Sorry, I lost track. What would you like to listen to?")) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        update_store(handler_input, {"pendingNlpSuggestion": None})
        logger.info("Hear: NLP suggestion confirmed intent=%s query=%s", top.get("intent"), top.get("query"))

        intent = top.get("intent")
        query = top.get("query", "")

        if intent == "creator":
            return await self._execute_creator_query(handler_input, query)
        if intent == "organization":
            return await self._execute_organization_query(handler_input, query)
        if intent == "category":
            return await self._execute_category_query(handler_input, query)
        if intent == "trending":
            return await WhatsTrendingHandler().handle(handler_input)
        if intent == "local":
            attrs = handler_input.attributes_manager.get_request_attributes()
            attrs["_nlp"] = {"intent": "local", "slots": {}}
            handler_input.attributes_manager.set_request_attributes(attrs)
            return await PlayContentHandler().handle(handler_input)
        if intent == "following":
            attrs = handler_input.attributes_manager.get_request_attributes()
            attrs["_nlp"] = {"intent": "following", "slots": {}}
            handler_input.attributes_manager.set_request_attributes(attrs)
            return await PlayContentHandler().handle(handler_input)
        if intent == "browse":
            return await BrowseContentHandler().handle(handler_input)
        if intent == "show_more":
            return await ShowMoreBrowseHandler().handle(handler_input)
        if intent == "general":
            return await self._execute_general_query(handler_input, query)

        store2 = get_store(handler_input)
        if not store2.get("awaitingFeedback"):
            return handler_input.response_builder \
                .speak(ssml(WELCOME_REPROMPT)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        if intent == "feedback_enjoyed":
            return await FeedbackEnjoyedHandler().handle(handler_input)
        if intent == "feedback_not_enjoyed":
            return await FeedbackNotEnjoyedHandler().handle(handler_input)

        return handler_input.response_builder \
            .speak(ssml("What would you like to listen to?")) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    async def _execute_creator_query(self, handler_input, creator_name):
        attrs = handler_input.attributes_manager.get_request_attributes()
        attrs["_nlp"] = {"intent": "creator", "slots": {"creatorQuery": creator_name}}
        handler_input.attributes_manager.set_request_attributes(attrs)
        return await PlayByCreatorHandler().handle(handler_input)

    async def _execute_organization_query(self, handler_input, org_name):
        attrs = handler_input.attributes_manager.get_request_attributes()
        attrs["_nlp"] = {"intent": "organization", "slots": {"organizationQuery": org_name}}
        handler_input.attributes_manager.set_request_attributes(attrs)
        return await PlayByOrganizationHandler().handle(handler_input)

    async def _execute_category_query(self, handler_input, category):
        attrs = handler_input.attributes_manager.get_request_attributes()
        attrs["_nlp"] = {"intent": "category", "slots": {"category": category}}
        handler_input.attributes_manager.set_request_attributes(attrs)
        return await PlayContentHandler().handle(handler_input)

    async def _execute_general_query(self, handler_input, topic):
        attrs = handler_input.attributes_manager.get_request_attributes()
        attrs["_nlp"] = {"intent": "general", "slots": {"topic": topic}}
        handler_input.attributes_manager.set_request_attributes(attrs)
        return await PlayContentHandler().handle(handler_input)


# ---------------------------------------------------------------------------
# NoIntentHandler
# ---------------------------------------------------------------------------


class NoIntentHandler(AbstractRequestHandler):
    """State-machine based No handler.

    Routes No based on state:
    1. awaitingSearchConfirmation  -> cycle to next suggestion or give up
    2. listModeActive              -> advance list position
    3. awaitingNotificationChoice  -> clear pending notifications
    4. awaitingStillListening      -> stop and goodbye
    5. awaitingContinueAfterFlag   -> skip to next
    6. awaitingFeedback            -> delegate to FeedbackNotEnjoyed
    7. awaitingFollow              -> clear feedback
    8. awaitingNotificationOptIn   -> decline opt-in
    9. awaitingReportDecision      -> delegate to SkipFeedback
    10. pendingNlpSuggestion       -> reject NLP suggestion
    Fallback                       -> generic welcome reprompt
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.NoIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        store = get_store(handler_input)
        session_attrs = handler_input.attributes_manager.get_session_attributes() or {}

        # 0a. Location onboarding choice declined
        if store.get("awaitingLocationChoice"):
            update_store(handler_input, {
                "awaitingLocationChoice": False,
                "onboardingStage": None,
            })
            return handler_input.response_builder \
                .speak(ssml(LOCATION_DECLINED)) \
                .reprompt(ssml(IDLE_DO_NEXT_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        # 0b. Location confirmation rejected — ask for a different town
        if store.get("awaitingLocationConfirm"):
            update_store(handler_input, {
                "awaitingLocationConfirm": False,
                "pendingLocationConfirm": None,
                "onboardingStage": None,
            })
            return handler_input.response_builder \
                .speak(ssml(LOCATION_RETRY)) \
                .reprompt(ssml("Which town or city should I set?")) \
                .set_should_end_session(False) \
                .response

        # 1. Search confirmation
        if store.get("awaitingSearchConfirmation") or session_attrs.get("awaitingSearchConfirmation"):
            return self._handle_search_no(handler_input, store, session_attrs)

        # 2. List mode active
        if store.get("listModeActive"):
            return self._handle_list_mode_no(handler_input, store)

        # 3. Notification choice
        if store.get("awaitingNotificationChoice"):
            return self._handle_notification_no(handler_input, store)

        # 4. Still listening
        if store.get("awaitingStillListening"):
            return self._handle_still_listening_no(handler_input)

        # 5. Awaiting continue after flag
        if store.get("awaitingContinueAfterFlag"):
            update_store(handler_input, {"awaitingContinueAfterFlag": False})
            return await NextIntentHandler().handle(handler_input)

        # 6. Awaiting feedback
        if store.get("awaitingFeedback"):
            return await FeedbackNotEnjoyedHandler().handle(handler_input)

        # 7. Awaiting follow
        if store.get("awaitingFollow"):
            await clear_feedback(handler_input)
            return idle_next_response(handler_input, FEEDBACK_FOLLOW_DECLINED)

        # 8. Awaiting notification opt-in
        if store.get("awaitingNotificationOptIn"):
            return self._handle_notification_opt_in_no(handler_input, store)

        # 9. Awaiting report decision
        if store.get("awaitingReportDecision"):
            return await SkipFeedbackHandler().handle(handler_input)

        # 10. Pending NLP suggestion
        if store.get("pendingNlpSuggestion") and store["pendingNlpSuggestion"]:
            return self._reject_nlp_suggestion(handler_input, store)

        # Fallback
        return handler_input.response_builder \
            .speak(WELCOME_REPROMPT) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response

    def _handle_search_no(self, handler_input, store, session_attrs):
        """Cycle through search suggestions or give up."""
        attrs = handler_input.attributes_manager.get_request_attributes()
        attrs.pop("_pendingConfirmation", None)
        handler_input.attributes_manager.set_request_attributes(attrs)

        suggestions = (
            session_attrs.get("pendingSuggestions") if session_attrs.get("pendingSuggestions")
            else store.get("pendingSuggestions", [])
        )
        idx = (session_attrs.get("suggestionIndex") or store.get("suggestionIndex") or 0) + 1

        if idx < len(suggestions):
            next_sug = suggestions[idx]
            handler_input.attributes_manager.set_session_attributes({
                "awaitingSearchConfirmation": True,
                "pendingSearchIntent": session_attrs.get("pendingSearchIntent"),
                "pendingSearchQuery": session_attrs.get("pendingSearchQuery"),
                "pendingSuggestions": suggestions,
                "suggestionIndex": idx,
            })
            next_name = next_sug.get("display") or next_sug.get("query") or next_sug.get("intent")
            return handler_input.response_builder \
                .speak(ssml(f"Maybe {escape_ssml_lite(str(next_name))}?")) \
                .set_should_end_session(False) \
                .response

        update_store(handler_input, {
            "awaitingSearchConfirmation": False,
            "pendingSearchIntent": None,
            "pendingSearchQuery": None,
            "pendingSearchSlots": {},
            "pendingSuggestions": [],
            "suggestionIndex": 0,
            "excludedSuggestions": [],
        })
        return handler_input.response_builder \
            .speak(ssml("No problem. What would you like to listen to instead?")) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    def _handle_list_mode_no(self, handler_input, store):
        """Advance to next item in list mode."""
        queue = store.get("listQueue") or store.get("upcomingQueue") or []
        pos = (store.get("listPosition") or 0) + 1

        if pos >= len(queue):
            update_store(handler_input, {"listModeActive": False})
            return handler_input.response_builder \
                .speak(ssml(END_OF_LIST)) \
                .response

        next_item = queue[pos]
        update_store(handler_input, {"listPosition": pos, "listModeActive": True})
        list_text = ASK_LISTEN_NEXT(
            next_item.get("title", "this track"),
            next_item.get("creator", "unknown"),
            next_item.get("category", "general"),
        )
        return handler_input.response_builder \
            .speak(ssml(list_text)) \
            .reprompt(ssml("Would you like to listen, or say next to skip?")) \
            .set_should_end_session(False) \
            .response

    def _handle_notification_no(self, handler_input, store):
        """Clear pending notification queue."""

        tracks = store.get("pendingNotificationQueue") or []
        track_ids = [t.get("trackId") for t in tracks if t.get("trackId")]
        update_store(handler_input, {
            "awaitingNotificationChoice": False,
            "pendingNotificationQueue": None,
        })
        mark_all_tracks_announced(track_ids, get_alexa_user_id(handler_input))
        return handler_input.response_builder \
            .speak(ssml(NOTIFICATIONS_DECLINED)) \
            .reprompt(ssml("What would you like to listen to?")) \
            .set_should_end_session(False) \
            .response

    def _handle_still_listening_no(self, handler_input):
        """Stop after still-listening prompt declined."""
        update_store(handler_input, {
            "awaitingStillListening": False,
            "awaitingContinueAfterFlag": False,
        })
        clear_queue(handler_input)
        return handler_input.response_builder \
            .speak(GOODBYE) \
            .add_directive(build_stop_directive()) \
            .response

    def _handle_notification_opt_in_no(self, handler_input, store):
        """Decline notification opt-in."""
        update_store(handler_input, {"awaitingNotificationOptIn": False})
        creator_name = store.get("currentCreator") or store.get("feedbackCreator")
        if creator_name and not is_bad_credit(creator_name):
            msg = FOLLOW_CREATOR_NOTIFICATION_DECLINED(creator_name)
        else:
            msg = FOLLOW_NOTIFICATION_DECLINED_GENERIC
        return idle_next_response(handler_input, msg)

    def _reject_nlp_suggestion(self, handler_input, store):
        """Reject the current NLP suggestion; offer the next if available."""
        suggestions = store.get("pendingNlpSuggestion") or []
        if len(suggestions) > 1:
            remaining = suggestions[1:]
            update_store(handler_input, {"pendingNlpSuggestion": remaining})
            next_sug = remaining[0]
            display_text = next_sug.get("displayText") or f"{next_sug.get('intent')} {next_sug.get('query', '')}".strip()
            return handler_input.response_builder \
                .speak(ssml(f"How about {escape_ssml_lite(display_text)}? Say yes to try that.")) \
                .reprompt(ssml("Say yes to confirm, or no for other options.")) \
                .set_should_end_session(False) \
                .response

        update_store(handler_input, {"pendingNlpSuggestion": None})
        return handler_input.response_builder \
            .speak(ssml("No problem. You can say what's trending, play followed by a topic, or play from a creator.")) \
            .reprompt(ssml("Try saying what's trending, or play news.")) \
            .set_should_end_session(False) \
            .response


# ---------------------------------------------------------------------------
# NavigateHome, Unsupported, SessionEnded, Fallback, Unmatched, Unknown
# ---------------------------------------------------------------------------


class NavigateHomeHandler(AbstractRequestHandler):
    """Routes NavigateHome to browse content."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.NavigateHomeIntent"
        )

    def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated
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


class FallbackHandler(AbstractRequestHandler):
    """Handles AMAZON.FallbackIntent — generic fallback speech."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "AMAZON.FallbackIntent"
        )

    def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated
        return handler_input.response_builder \
            .speak(FALLBACK_SPEECH) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response


class UnmatchedIntentHandler(AbstractRequestHandler):
    """Catch-all for unmatched IntentRequests."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "IntentRequest"

    def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated
        intent_name = get_intent_name(handler_input)
        dialog_state = None
        try:
            dialog_state = handler_input.request_envelope.request.dialogState
        except Exception:
            pass
        logger.info("Hear: unmatched IntentRequest intentName=%s dialogState=%s",
                     intent_name, dialog_state)
        return handler_input.response_builder \
            .speak(FALLBACK_SPEECH) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response


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
        return handler_input.response_builder \
            .speak(ssml(ERROR_GENERIC)) \
            .reprompt(WELCOME_REPROMPT) \
            .set_should_end_session(False) \
            .response


# ---------------------------------------------------------------------------
# ErrorHandler (AbstractExceptionHandler)
# ---------------------------------------------------------------------------


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
