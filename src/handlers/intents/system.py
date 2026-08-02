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

from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractExceptionHandler
from ask_sdk_core.handler_input import HandlerInput


from src.services.storage.persistence import (
    get_store, update_store, clear_queue, clear_feedback, reset_queue_items_completed,
)
from src.utils.skill_request import get_user_id as get_alexa_user_id
from src.services.playback import flush_previous_track
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml, escape_ssml_lite, is_bad_credit, HELP, GOODBYE, IDLE_DO_NEXT_REPROMPT,
    WELCOME_REPROMPT, ERROR_GENERIC, FALLBACK_SPEECH, LOOP_SHUFFLE_UNAVAILABLE,
    FLAGGED_CONTINUE_YES_ACK, NO_CONTENT_AVAILABLE, NOTIFICATIONS_ENABLE_FAILED, NOTIFICATIONS_ENABLED, NOTIFICATIONS_DECLINED,
    FEEDBACK_FOLLOW_DECLINED, FOLLOW_CREATOR_NOTIFICATION_DECLINED,
    FOLLOW_NOTIFICATION_DECLINED_GENERIC, ASK_LISTEN_FIRST, ASK_LISTEN_NEXT,
    END_OF_LIST, NO_TRACKS_AVAILABLE, QUEUE_FINISHED, QUEUE_NEXT_ANNOUNCE,
    LOCATION_CONFIRMED, LOCATION_DECLINED, LOCATION_RETRY,
    COMMUNITY_PLAYBACK_OFFER,
    RESUME_DECLINED_NEXT_OPTIONS, RESUME_DECLINED_NEXT_OPTIONS_REPROMPT,
    ASK_TALKING_NEWSPAPER_REPROMPT, ambiguous_reference_message,
    LATEST_SOURCE_DECLINED,
)
from src.services.api import sync_listener
from src.utils.audio import build_stop_directive
from src.services.playback.events import emit_user_playback_event, USER_PLAYBACK_EVENT_TYPES
from src.utils.feedback_flow import idle_next_response
from src.handlers.intents.onboarding import onboarding_pending_redirect
from src.handlers.notifications import (
    has_notification_permission, complete_notification_opt_in,
    build_notification_permission_response,
)
from src.services.playback.start import resume_playback, start_playback
from src.services.notifications import (
    resolve_notification_queue,
    update_notification_status,
)
from src.services.api import search
from src.services.playback.session import (
    read_playback_session,
    write_playback_session,
)
from src.services.queue.state import (
    move_queue,
    queue_content_id,
    read_playback_queue,
)
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
from src.services.observability import capture_skill_exception, flush_sentry, last_resort_skill_response
from src.services.dialog_state import activate_dialog, get_active_dialog, clear_active_dialog
from src.utils.normalize_content_item import pick_content_source
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
        dialog_type = (get_active_dialog(handler_input) or {}).get("type")

        if dialog_type == "ambiguity":
            return handler_input.response_builder \
                .speak(ssml("Please say one of the names I offered, or say show more.")) \
                .reprompt(ssml("Say one of the names, or say show more.")) \
                .set_should_end_session(False) \
                .response

        if dialog_type == "latest_source":
            return await self._handle_latest_source_yes(handler_input, store)

        # 0. Location confirmation — user confirms the town to save
        # 1. Search confirmation. This must win over stale launch-time resume
        # state because it is the question Alexa most recently asked.
        if dialog_type == "search_confirmation" or (
            not dialog_type and (
                store.get("awaitingSearchConfirmation")
                or session_attrs.get("awaitingSearchConfirmation")
            )
        ):
            return await self._handle_search_confirmation(handler_input, store, session_attrs)

        if store.get("awaitingLocationConfirm"):
            return await self._confirm_location(handler_input, store)

        if store.get("awaitingCommunityPlayback"):
            return await self._handle_community_play_yes(handler_input, store)

        # 2. Resume
        if dialog_type == "resume" or (not dialog_type and store.get("awaitingResume")):
            return await self._handle_resume_yes(handler_input, store)

        # 3. List mode active
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
        final_city = city
        update_store(handler_input, {
            "userCity": final_city,
            "locality": pending.get("locality") or final_city,
            "deviceCountryCode": pending.get("countryCode"),
            "devicePostalCode": pending.get("postalCode") or store.get("devicePostalCode"),
            "latitude": pending.get("latitude"),
            "longitude": pending.get("longitude"),
            "onboardingComplete": True,
            "onboardingStage": None,
            "locationSource": pending.get("source") or "manual",
            "localityResolvedAt": _current_timestamp_ms(),
            "awaitingLocationConfirm": False,
            "pendingLocationConfirm": None,
            "awaitingCommunityPlayback": True,
        })
        confirmed = get_store(handler_input)
        if user_id:
            try:
                await sync_listener({
                    "alexaUserId": user_id,
                    "deviceId": confirmed.get("deviceId"),
                    "locale": getattr(handler_input.request_envelope.request, "locale", None),
                    "userName": confirmed.get("userName"),
                    "userEmail": confirmed.get("userEmail"),
                    "city": final_city,
                    "locality": confirmed.get("locality"),
                    "countryCode": confirmed.get("deviceCountryCode"),
                    "latitude": confirmed.get("latitude"),
                    "longitude": confirmed.get("longitude"),
                    "clientVersion": "alexa-skill",
                })
            except Exception as err:
                logger.warning("Hear: listener sync failed error=%s", type(err).__name__)
        return handler_input.response_builder \
            .speak(ssml(f"{LOCATION_CONFIRMED(final_city)} {COMMUNITY_PLAYBACK_OFFER(final_city)}")) \
            .reprompt(ssml(COMMUNITY_PLAYBACK_OFFER(final_city))) \
            .set_should_end_session(False) \
            .response

    async def _handle_latest_source_yes(self, handler_input, store):
        source = store.get("pendingLatestSource") or {}
        selected_source = pick_content_source(source) or {}
        source_kind = source.get("sourceKind") or selected_source.get("kind")
        source_id = source.get("sourceId") or selected_source.get("id")
        source_name = source.get("sourceName") or selected_source.get("name") or "that source"
        update_store(handler_input, {"pendingLatestSource": None})
        clear_active_dialog(handler_input, "latest_source")
        if not source_id or source_kind not in {"organization", "creator"}:
            return handler_input.response_builder \
                .speak(ssml(LATEST_SOURCE_DECLINED)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response
        filter_key = "organizationIds" if source_kind == "organization" else "creatorIds"
        filters = {filter_key: [source_id]}
        payload = {"query": "", "filter": filters, "sort": "latest", "page": 0, "limit": 3}
        user_id = get_alexa_user_id(handler_input)
        if user_id:
            payload["alexaUserId"] = user_id
        result = await search(payload)
        previous_id = source.get("contentId")
        result["results"] = [item for item in result.get("results", []) if item.get("contentId") != previous_id]
        result["_search_payload"] = payload
        if result["results"]:
            return await auto_play_first_from_search(handler_input, result, {
                "discoveryIntent": "latest_source",
                "q": "",
                "introOverride": f"Here is the latest from {escape_ssml_lite(source_name)}.",
            })
        speech = f"There is nothing newer from {escape_ssml_lite(source_name)} right now. What would you like to listen to?"
        return handler_input.response_builder \
            .speak(ssml(speech)) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    async def _handle_community_play_yes(self, handler_input, store):
        """Play local content after the user accepts the location follow-up."""
        city = store.get("userCity") or store.get("locality")
        update_store(handler_input, {
            "awaitingCommunityPlayback": False,
            "awaitingSearchConfirmation": False,
            "pendingResolution": None,
        })
        clear_active_dialog(handler_input, "search_confirmation")
        attrs = handler_input.attributes_manager.get_request_attributes()
        attrs["_nlp"] = {
            "intent": "local",
            "alexaIntent": "local",
            "confidence": "high",
            "nlpMatchesAlexa": True,
            "needsRedirect": False,
            "slots": {
                "city": city,
                "isLocal": True,
                "residualQuery": "",
            },
        }
        handler_input.attributes_manager.set_request_attributes(attrs)
        result = await discover_content_via_search(
            handler_input,
            {"q": "", "intent": "local"},
        )
        if result.get("results"):
            return await auto_play_first_from_search(
                handler_input,
                result,
                {
                    "discoveryIntent": "local",
                    "q": "",
                    "introOverride": f"Here is the latest from {escape_ssml_lite(city)}.",
                },
            )
        if result.get("client_message"):
            speech = escape_ssml_lite(str(result["client_message"]))
        elif result.get("failed"):
            speech = "I cannot reach the Hear catalogue right now. Please try again shortly."
        else:
            speech = f"I couldn't find anything available from {escape_ssml_lite(city)} right now."
        return handler_input.response_builder \
            .speak(ssml(speech)) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    async def _handle_search_confirmation(self, handler_input, store, session_attrs):
        """Execute exactly the immutable payload the user confirmed."""
        resolution = store.get("pendingResolution") or session_attrs.get("pendingResolution")
        if isinstance(resolution, dict) and resolution.get("searchPayload"):
            if int(resolution.get("expiresAt") or 0) < int(time.time()):
                update_store(handler_input, {
                    "awaitingSearchConfirmation": False,
                    "pendingResolution": None,
                })
                return handler_input.response_builder \
                    .speak(ssml("That request has expired. Please say what you'd like to hear again.")) \
                    .reprompt(WELCOME_REPROMPT) \
                    .set_should_end_session(False) \
                    .response

            payload = dict(resolution["searchPayload"])
            label = str(resolution.get("confirmationLabel") or "that request")
            update_store(handler_input, {
                "awaitingSearchConfirmation": False,
                "pendingResolution": None,
                "awaitingLocationConfirm": False,
                "pendingLocationConfirm": None,
                "lastExecutedResolutionId": resolution.get("requestId"),
                "_requiresReliableSave": True,
            })
            clear_active_dialog(handler_input, "search_confirmation")
            handler_input.attributes_manager.set_session_attributes({})
            logger.info(
                "Hear: confirmed resolver search START id=%s label=%s",
                resolution.get("requestId"), label,
            )
            search_result = await search(payload)
            search_result["_search_payload"] = payload
            if search_result.get("results"):
                response = await auto_play_first_from_search(handler_input, search_result, {
                    "discoveryIntent": resolution.get("intent") or "search",
                    "q": payload.get("query") or "",
                })
                if response:
                    return response

            if search_result.get("failed"):
                return handler_input.response_builder \
                    .speak(ssml(
                        "I couldn't reach the Hear catalogue to search for "
                        f"{escape_ssml_lite(label)}. Please try again shortly."
                    )) \
                    .reprompt(WELCOME_REPROMPT) \
                    .set_should_end_session(False) \
                    .response

            relaxed = self._source_only_relaxation(resolution)
            if relaxed:
                update_store(handler_input, {
                    "awaitingSearchConfirmation": True,
                    "pendingResolution": relaxed,
                    "_requiresReliableSave": True,
                })
                activate_dialog(
                    handler_input,
                    "search_confirmation",
                    context=relaxed,
                )
                source = relaxed["confirmationLabel"].removeprefix("the latest recordings from ")
                failed_label = label.removeprefix("the latest ")
                speech = (
                    f"I couldn't find any {escape_ssml_lite(failed_label)}. "
                    f"Would you like to hear the latest recordings from {escape_ssml_lite(source)} instead?"
                )
                return handler_input.response_builder \
                    .speak(ssml(speech)) \
                    .reprompt(ssml("Say yes to hear their latest recordings, or no to try something else.")) \
                    .set_should_end_session(False) \
                    .response

            return handler_input.response_builder \
                .speak(ssml(f"I couldn't find anything for {escape_ssml_lite(label)} right now. What would you like to try instead?")) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response

        # Never reconstruct a search from legacy intent/slot fragments. They
        # cannot prove which filters the user confirmed.
        update_store(handler_input, {
            "awaitingSearchConfirmation": False,
            "pendingOrganizationConfirmation": False,
            "pendingSearchIntent": None,
            "pendingSearchQuery": None,
            "pendingSearchSlots": {},
            "pendingSuggestions": [],
            "suggestionIndex": 0,
            "excludedSuggestions": [],
        })
        handler_input.attributes_manager.set_session_attributes({})
        return handler_input.response_builder \
            .speak(ssml("That earlier request has expired. Please tell me what you'd like to hear again.")) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    @staticmethod
    def _source_only_relaxation(resolution: dict) -> dict | None:
        payload = dict(resolution.get("searchPayload") or {})
        filters = dict(payload.get("filter") or {})
        source_keys = ("organizationIds", "creatorIds", "publicationIds")
        if not any(filters.get(key) for key in source_keys):
            return None
        constrained = bool(
            filters.get("categorySlugs")
            or filters.get("tags")
            or str(payload.get("query") or "").strip()
        )
        if not constrained:
            return None
        for key in ("categorySlugs", "tags"):
            filters.pop(key, None)
        payload["filter"] = filters
        payload["query"] = ""
        payload["sort"] = "latest"
        source_name = next((
            str(entity.get("canonicalValue") or "")
            for entity in resolution.get("resolvedEntities") or []
            if entity.get("type") in {"organization", "creator", "publication"}
            and entity.get("canonicalValue")
        ), "that source")
        now = int(time.time())
        return {
            **resolution,
            "requestId": f"{resolution.get('requestId')}:source-only",
            "confirmationLabel": f"the latest recordings from {source_name}",
            "searchPayload": payload,
            "createdAt": now,
            "expiresAt": now + 300,
            "alternatives": [],
        }

    async def _handle_list_mode_yes(self, handler_input, store):
        """Play the current item in list mode."""
        content_id = queue_content_id(store)
        if not content_id:
            update_store(handler_input, {"listModeActive": False})
            return handler_input.response_builder \
                .speak(ssml(NO_TRACKS_AVAILABLE)) \
                .response

        update_store(handler_input, {"listModeActive": False})
        await clear_feedback(handler_input)
        result = await search({
            "query": "",
            "filter": {"contentIds": [content_id]},
            "page": 0,
            "limit": 1,
        })
        if not result.get("results"):
            return handler_input.response_builder.speak(ssml(NO_CONTENT_AVAILABLE)).response
        return await start_playback(handler_input, result["results"][0], "")

    async def _handle_notification_choice(self, handler_input, store):
        """Resolve pending references through search and start the first result."""
        notifications = store.get("pendingNotificationQueue") or []
        update_store(handler_input, {
            "awaitingNotificationChoice": False,
            "pendingNotificationQueue": None,
        })
        result = await resolve_notification_queue(handler_input, notifications)
        if result.get("results"):
            return await start_playback(
                handler_input,
                result["results"][0],
                "Here are your new updates.",
            )
        return handler_input.response_builder \
            .speak(ssml(NO_CONTENT_AVAILABLE)) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    async def _handle_resume_yes(self, handler_input, store):
        state = read_playback_session(store)
        update_store(handler_input, {"awaitingResume": False})
        clear_active_dialog(handler_input, "resume")
        if not state or not state.get("contentId"):
            return handler_input.response_builder.speak(ssml(NO_CONTENT_AVAILABLE)).response
        return await resume_playback(
            handler_input,
            state,
            "Continuing where you stopped.",
        )

    async def _handle_still_listening_yes(self, handler_input, store):
        """Continue playing after the still-listening prompt."""
        update_store(handler_input, {
            "awaitingStillListening": False,
            "awaitingContinueAfterFlag": False,
        })
        reset_queue_items_completed(handler_input)

        queue = read_playback_queue(store)
        next_id = move_queue(handler_input, 1)
        if not queue or not next_id:
            clear_queue(handler_input)
            return handler_input.response_builder \
                .speak(ssml(QUEUE_FINISHED)) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response

        result = await search({
            "query": "",
            "filter": {"contentIds": [next_id]},
            "page": 0,
            "limit": 1,
        })
        if not result.get("results"):
            clear_queue(handler_input)
            return handler_input.response_builder \
                .speak(ssml(NO_CONTENT_AVAILABLE)) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response

        content = result["results"][0]
        current_index = int(read_playback_queue(get_store(handler_input)).get("currentIndex") or 0)
        total = len(queue["orderedContentIds"])
        intro = QUEUE_NEXT_ANNOUNCE(
            content.get("title"),
            content.get("creator"),
            current_index + 1,
            total,
        )
        return await start_playback(handler_input, content, intro)

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
        if intent == "publication":
            attrs = handler_input.attributes_manager.get_request_attributes()
            attrs["_nlp"] = {
                "intent": "publication",
                "slots": {
                    "isPublication": True,
                    "residualQuery": query or "",
                    "searchPlan": {
                        "query": query or "",
                        "filter": {"isPublication": True},
                        "sort": "trending",
                    },
                },
            }
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
        dialog_type = (get_active_dialog(handler_input) or {}).get("type")

        if dialog_type == "ambiguity":
            update_store(handler_input, {
                "pendingAmbiguity": None,
                "awaitingLocationConfirm": False,
                "pendingLocationConfirm": None,
                "_requiresReliableSave": True,
            })
            clear_active_dialog(handler_input, "ambiguity")
            return handler_input.response_builder \
                .speak(ssml("No problem. You can ask for news or sport, play from a talking newspaper, or say what's trending. What would you like to listen to?")) \
                .reprompt(ssml("You can ask for news or sport, a talking newspaper, or what's trending.")) \
                .set_should_end_session(False) \
                .response

        if dialog_type == "latest_source":
            update_store(handler_input, {"pendingLatestSource": None})
            clear_active_dialog(handler_input, "latest_source")
            return handler_input.response_builder \
                .speak(ssml(LATEST_SOURCE_DECLINED)) \
                .reprompt(ssml(LATEST_SOURCE_DECLINED)) \
                .set_should_end_session(False) \
                .response

        # 0. Location confirmation rejected — ask for a different town
        # The active dialog is the question Alexa most recently asked.
        if dialog_type == "search_confirmation" or (
            not dialog_type and (
                store.get("awaitingSearchConfirmation")
                or session_attrs.get("awaitingSearchConfirmation")
            )
        ):
            return self._handle_search_no(handler_input, store, session_attrs)

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

        if store.get("awaitingCommunityPlayback"):
            update_store(handler_input, {"awaitingCommunityPlayback": False})
            return handler_input.response_builder \
                .speak(ssml("No problem. What would you like to listen to?")) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        if dialog_type == "report_decision" or (
            not dialog_type and store.get("awaitingReportDecision")
        ):
            return await SkipFeedbackHandler().handle(handler_input)

        if dialog_type == "feedback" or (not dialog_type and store.get("awaitingFeedback")):
            return await SkipFeedbackHandler().handle(handler_input)

        if dialog_type == "resume" or (not dialog_type and store.get("awaitingResume")):
            return self._handle_resume_no(handler_input, store)

        # 2. List mode active
        if store.get("listModeActive"):
            return self._handle_list_mode_no(handler_input, store)

        # 3. Notification choice
        if store.get("awaitingNotificationChoice"):
            return await self._handle_notification_no(handler_input, store)

        # 4. Still listening
        if store.get("awaitingStillListening"):
            return self._handle_still_listening_no(handler_input)

        # 5. Awaiting continue after flag
        if store.get("awaitingContinueAfterFlag"):
            update_store(handler_input, {"awaitingContinueAfterFlag": False})
            return await NextIntentHandler().handle(handler_input)

        # 6. Awaiting feedback
        if store.get("awaitingFeedback"):
            return await SkipFeedbackHandler().handle(handler_input)

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
        if store.get("pendingResolution") or session_attrs.get("pendingResolution"):
            update_store(handler_input, {
                "awaitingSearchConfirmation": False,
                "pendingResolution": None,
                "pendingAmbiguity": None,
                "awaitingLocationConfirm": False,
                "pendingLocationConfirm": None,
                "_requiresReliableSave": True,
            })
            clear_active_dialog(handler_input, "search_confirmation")
            return handler_input.response_builder \
                .speak(ssml("No problem. You can ask for news or sport, play from a talking newspaper, or say what's trending. What would you like to listen to?")) \
                .reprompt(ssml("You can ask for news or sport, a talking newspaper, or what's trending.")) \
                .set_should_end_session(False) \
                .response
        if store.get("pendingOrganizationConfirmation"):
            update_store(handler_input, {
                "awaitingSearchConfirmation": False,
                "pendingOrganizationConfirmation": False,
                "pendingSearchIntent": None,
                "pendingSearchQuery": None,
                "pendingSearchSlots": {},
                "pendingSuggestions": [],
                "suggestionIndex": 0,
                "awaitingOrganizationName": True,
            })
            return handler_input.response_builder \
                .speak(ssml("Okay. Which talking newspaper did you mean?")) \
                .reprompt(ssml(ASK_TALKING_NEWSPAPER_REPROMPT)) \
                .set_should_end_session(False) \
                .response

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
        """Decline the offered queue item without creating another queue."""
        del store
        update_store(handler_input, {"listModeActive": False})
        return handler_input.response_builder \
            .speak(ssml("No problem. What would you like to listen to?")) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    async def _handle_notification_no(self, handler_input, store):
        """Dismiss the notifications explicitly declined by the user."""
        notifications = store.get("pendingNotificationQueue") or []
        update_store(handler_input, {
            "awaitingNotificationChoice": False,
            "pendingNotificationQueue": None,
        })
        for item in notifications:
            await update_notification_status(
                get_alexa_user_id(handler_input),
                item.get("notificationId"),
                "dismissed",
            )
        return handler_input.response_builder \
            .speak(ssml(NOTIFICATIONS_DECLINED)) \
            .reprompt(ssml("What would you like to listen to?")) \
            .set_should_end_session(False) \
            .response

    def _handle_resume_no(self, handler_input, store):
        state = read_playback_session(store)
        if state:
            write_playback_session(handler_input, {"status": "abandoned"})
        update_store(handler_input, {"awaitingResume": False})
        clear_active_dialog(handler_input, "resume")
        return handler_input.response_builder \
            .speak(ssml(RESUME_DECLINED_NEXT_OPTIONS)) \
            .reprompt(ssml(RESUME_DECLINED_NEXT_OPTIONS_REPROMPT)) \
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
        store = get_store(handler_input)
        pending = store.get("pendingAmbiguity")
        if isinstance(pending, dict) and pending.get("candidates"):
            slots = pending.get("slots") or {}
            references = slots.get("ambiguousReferences") or []
            phrase = (
                references[0].get("phrase")
                if references and isinstance(references[0], dict)
                else "that name"
            )
            message = ambiguous_reference_message(
                str(phrase or "that name"),
                list(pending.get("candidates") or [])[:3],
            )
            return handler_input.response_builder \
                .speak(ssml(message)) \
                .reprompt(ssml("Please say one of the names I just offered.")) \
                .set_should_end_session(False) \
                .response
        redirect = onboarding_pending_redirect(handler_input, store)
        if redirect is not None:
            return redirect
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
        intent_name = get_intent_name(handler_input)
        dialog_state = None
        try:
            dialog_state = handler_input.request_envelope.request.dialogState
        except Exception:
            pass
        logger.info("Hear: unmatched IntentRequest intentName=%s dialogState=%s",
                     intent_name, dialog_state)
        redirect = onboarding_pending_redirect(handler_input, get_store(handler_input))
        if redirect is not None:
            return redirect
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
