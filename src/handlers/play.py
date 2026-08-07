from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from src.dependencies import Dependencies
from src.services.store import get_store, update_store
from src.services.resolution import build_pending_resolution
from src.utils.skill_request import (
    get_request_type,
    get_intent_name,
    get_user_id as _get_user_id,
)
from src.utils.speech import (
    ssml,
    escape_ssml_lite,
    SEARCH_NO_MATCH,
    WELCOME_REPROMPT,
    ERROR_GENERIC,
    PLAY_COMMUNITY_INTRO,
    COMMUNITY_NEEDS_TOWN,
    REPROMPT_ASK_TOWN,
    ASK_TALKING_NEWSPAPER,
    ASK_TALKING_NEWSPAPER_REPROMPT,
    TALKING_NEWSPAPER_NOT_RECOGNIZED,
    CONFIRM_RESOLVED_SEARCH,
    resolved_search_request_label,
    unresolved_reference_message,
)
from src.utils.search_filters import (
    wants_latest_playback,
    wants_play_from_followed_creators,
    wants_local_community_content,
)
from src.handlers.search import (
    auto_play_first_from_search,
    discover_content_via_search,
    play_from_followed_creators,
    _build_no_content_response,
    _build_search_outcome_response,
    _discover_content_avoiding_recent,
    _extract_slot_value,
    _play_first_search_result,
    _raw_search_phrase,
)
from src.handlers.browse import (
    ShowMoreBrowseHandler,
    _has_active_browse_catalog,
    _is_misrouted_browse_pagination,
)

class PlayContentHandler(AbstractRequestHandler):

    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        name = get_intent_name(handler_input)
        return (
            get_request_type(handler_input) == "IntentRequest"
            and name in {"PlayContentIntent", "PlayPublicationIntent"}
        )

    async def handle(self, handler_input: HandlerInput):
        try:

            if not _get_user_id(handler_input):
                return handler_input.response_builder \
                    .speak(ssml(ERROR_GENERIC)) \
                    .reprompt(WELCOME_REPROMPT) \
                    .set_should_end_session(False) \
                    .response

            active_store = get_store(handler_input)

            raw_phrase = _raw_search_phrase(handler_input)
            search_q = None

            if not search_q:
                search_q = _extract_slot_value(handler_input, "query")
            if not search_q:
                search_q = _raw_search_phrase(handler_input)

            try:
                if wants_play_from_followed_creators(handler_input, search_q or raw_phrase or ""):
                    return await play_from_followed_creators(handler_input, deps=self._deps)
            except Exception:
                pass

            if (
                (_is_misrouted_browse_pagination(search_q or "") or _is_misrouted_browse_pagination(raw_phrase or ""))
                and _has_active_browse_catalog(active_store)
            ):
                return await ShowMoreBrowseHandler().handle(handler_input)

            try:
                is_community = wants_local_community_content(handler_input, search_q)
            except Exception:
                is_community = False

            if is_community:
                has_location = active_store.get("locality") or active_store.get("userCity") \
                    or active_store.get("latitude") or active_store.get("devicePostalCode")
                if not has_location:
                    update_store(handler_input, {"onboardingStage": "confirm_town_for_community"})
                    return handler_input.response_builder \
                        .speak(ssml(COMMUNITY_NEEDS_TOWN)) \
                        .reprompt(ssml(REPROMPT_ASK_TOWN)) \
                        .set_should_end_session(False) \
                        .response

            search_result = await discover_content_via_search(handler_input, {"q": search_q or ""}, deps=self._deps) \
                if search_q \
                else await _discover_content_avoiding_recent(handler_input, {"q": ""}, deps=self._deps)

            logger.info(
                "Hear: PlayContentHandler search done q=%s hitCount=%s",
                search_q, len(search_result.get("results", [])),
            )

            if not search_result.get("results"):
                if search_q:
                    return handler_input.response_builder \
                        .speak(ssml(SEARCH_NO_MATCH(search_q))) \
                        .reprompt(ssml(WELCOME_REPROMPT)) \
                        .set_should_end_session(False) \
                        .response
                return _build_search_outcome_response(handler_input, search_result)

            try:
                if search_q and wants_latest_playback(raw_phrase or ""):
                    return await _play_first_search_result(
                        handler_input, search_result["results"], label=search_q,
                        deps=self._deps,
                    )
            except Exception:
                pass

            was_relaxed = bool(search_q and search_result.get("search_relaxation"))
            discover_intro = None
            if not was_relaxed and is_community:
                resolve_loc = active_store.get("locality")
                discover_intro = PLAY_COMMUNITY_INTRO(resolve_loc, search_result.get("total_hits", 0))

            response = await auto_play_first_from_search(handler_input, search_result, {
                "discoveryIntent": get_intent_name(handler_input) or "PlayContentIntent",
                "q": search_q,
                "locality": active_store.get("locality"),
                "introOverride": discover_intro,
            }, deps=self._deps)
            return response or _build_no_content_response(handler_input)

        except Exception as err:
            logger.error("Hear: PlayContentHandler failed %s", err)
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response


class PlayByCreatorHandler(AbstractRequestHandler):

    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "PlayByCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):

        if not _get_user_id(handler_input):
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        active_store = get_store(handler_input)

        attrs = handler_input.attributes_manager.get_request_attributes()
        nlp = attrs.get("_nlp", {}) if attrs else {}
        nlp_slots = nlp.get("slots", {}) if nlp else {}
        creator_query = nlp_slots.get("creatorQuery") or \
            _extract_slot_value(handler_input, "creatorQuery") or \
            _extract_slot_value(handler_input, "query") or _raw_search_phrase(handler_input)
        resolved_creator = bool(nlp_slots.get("creatorIds"))
        creator_label = nlp_slots.get("creatorName") or creator_query
        raw_phrase = _raw_search_phrase(handler_input)

        if creator_query and _is_misrouted_browse_pagination(creator_query) \
                and _has_active_browse_catalog(active_store):
            return await ShowMoreBrowseHandler().handle(handler_input)

        if not creator_query and not resolved_creator:
            return handler_input.response_builder \
                .speak(ssml("Which creator would you like to hear?")) \
                .reprompt(ssml("Just say their name.")) \
                .set_should_end_session(False) \
                .response

        search_result = await discover_content_via_search(handler_input, {
            "q": nlp_slots.get("residualQuery", "") if resolved_creator else creator_query,
            "intent": "creator",
        }, deps=self._deps)

        if not search_result.get("results"):
            fallback = await _discover_content_avoiding_recent(handler_input, {"q": ""}, deps=self._deps)
            if fallback.get("results"):
                response = await auto_play_first_from_search(handler_input, fallback, {
                    "discoveryIntent": "PlayContentIntent", "q": "",
                    "locality": get_store(handler_input).get("locality"),
                    "introOverride": f"{SEARCH_NO_MATCH(creator_label)} Here are some other picks for you.",
                }, deps=self._deps)
                return response or _build_no_content_response(handler_input)
            return handler_input.response_builder \
                .speak(ssml(SEARCH_NO_MATCH(creator_label))) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        try:
            if wants_latest_playback(raw_phrase or ""):
                return await _play_first_search_result(
                    handler_input, search_result["results"], label=creator_label,
                    deps=self._deps,
                )
        except Exception:
            pass

        was_relaxed = bool(search_result.get("search_relaxation"))
        response = await auto_play_first_from_search(handler_input, search_result, {
            "discoveryIntent": "PlayByCreatorIntent",
            "q": creator_query,
            "locality": get_store(handler_input).get("locality"),
            "introOverride": None if was_relaxed
            else f"Here is what I found for {escape_ssml_lite(creator_label)}.",
        }, deps=self._deps)
        return response or _build_no_content_response(handler_input)


class PlayByOrganizationHandler(AbstractRequestHandler):

    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "PlayByOrganizationIntent"
        )

    async def handle(self, handler_input: HandlerInput):

        if not _get_user_id(handler_input):
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        active_store = get_store(handler_input)

        attrs = handler_input.attributes_manager.get_request_attributes()
        nlp = attrs.get("_nlp", {}) if attrs else {}
        nlp_slots = nlp.get("slots", {}) if nlp else {}
        raw_phrase = _raw_search_phrase(handler_input)
        org_query = nlp_slots.get("organizationQuery") or \
            _extract_slot_value(handler_input, "organizationQuery") or \
            _extract_slot_value(handler_input, "query") or _raw_search_phrase(handler_input)
        resolved_org = bool(nlp_slots.get("organizationIds"))

        org_label = nlp_slots.get("organizationName") or org_query

        if org_query and _is_misrouted_browse_pagination(org_query) \
                and _has_active_browse_catalog(active_store):
            return await ShowMoreBrowseHandler().handle(handler_input)

        if nlp_slots.get("ambiguousReferences"):
            result = await discover_content_via_search(handler_input, {
                "q": "",
                "intent": "organization",
            }, deps=self._deps)
            message = result.get("client_message") or TALKING_NEWSPAPER_NOT_RECOGNIZED(org_query)
            return handler_input.response_builder \
                .speak(ssml(message)) \
                .reprompt(ssml("Please say the full talking newspaper name.")) \
                .set_should_end_session(False) \
                .response

        generic_request = (
            bool(nlp_slots.get("genericOrganizationRequest"))
            or bool(nlp_slots.get("unresolvedGenericOrganization"))
        )
        if generic_request or (not org_query and not resolved_org):
            update_store(handler_input, {"awaitingOrganizationName": True})
            return handler_input.response_builder \
                .speak(ssml(ASK_TALKING_NEWSPAPER)) \
                .reprompt(ssml(ASK_TALKING_NEWSPAPER_REPROMPT)) \
                .add_directive({
                    "type": "Dialog.ElicitSlot",
                    "slotToElicit": "organizationQuery",
                }) \
                .set_should_end_session(False) \
                .response

        unresolved = nlp_slots.get("unresolvedReferences") or []
        if unresolved:
            reference = unresolved[0]
            message = unresolved_reference_message(
                str(reference.get("phrase") or org_query or ""),
                list(reference.get("expectedTypes") or []),
            )
            update_store(handler_input, {"awaitingOrganizationName": False})
            return handler_input.response_builder \
                .speak(ssml(message)) \
                .reprompt(ssml("Please say the creator, organisation, or publication's full name.")) \
                .set_should_end_session(False) \
                .response

        if not resolved_org:
            update_store(handler_input, {"awaitingOrganizationName": True})
            return handler_input.response_builder \
                .speak(ssml(TALKING_NEWSPAPER_NOT_RECOGNIZED(org_query))) \
                .reprompt(ssml(ASK_TALKING_NEWSPAPER_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        if resolved_org:
            label = resolved_search_request_label(nlp_slots, org_label)
            update_store(handler_input, {
                "awaitingOrganizationName": False,
                "awaitingSearchConfirmation": True,
                "pendingResolution": build_pending_resolution(nlp, label),
                "_requiresReliableSave": True,
            })
            return handler_input.response_builder \
                .speak(ssml(CONFIRM_RESOLVED_SEARCH(label))) \
                .reprompt(ssml("Say yes to play it, or no to try another name.")) \
                .set_should_end_session(False) \
                .response

        search_result = await discover_content_via_search(handler_input, {
            "q": nlp_slots.get("residualQuery", "") if resolved_org else org_query,
            "intent": "organization",
        }, deps=self._deps)

        if not search_result.get("results"):
            fallback = await _discover_content_avoiding_recent(handler_input, {"q": ""}, deps=self._deps)
            if fallback.get("results"):
                response = await auto_play_first_from_search(handler_input, fallback, {
                    "discoveryIntent": "PlayContentIntent", "q": "",
                    "locality": active_store.get("locality"),
                    "introOverride": f"{SEARCH_NO_MATCH(org_label)} Here are some other picks for you.",
                }, deps=self._deps)
                return response or _build_no_content_response(handler_input)
            return handler_input.response_builder \
                .speak(ssml(SEARCH_NO_MATCH(org_label))) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        try:
            if wants_latest_playback(raw_phrase or ""):
                return await _play_first_search_result(
                    handler_input, search_result["results"], label=org_label,
                    deps=self._deps,
                )
        except Exception:
            pass

        was_relaxed = bool(search_result.get("search_relaxation"))
        response = await auto_play_first_from_search(handler_input, search_result, {
            "discoveryIntent": "PlayByOrganizationIntent",
            "q": "",
            "locality": active_store.get("locality"),
            "introOverride": None if was_relaxed
            else f"Here is what I found from {escape_ssml_lite(org_label)}.",
        }, deps=self._deps)
        return response or _build_no_content_response(handler_input)
