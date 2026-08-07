from __future__ import annotations
from typing import Any, Dict
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from src.dependencies import Dependencies
from src.services.browse import set_browse_catalog, get_browse_catalog
from src.services.store import get_store, update_store
from src.services.dialog_state import activate_dialog
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
    PLAY_NO_PENDING_LIST,
    BROWSE_EXHAUSTED,
    CONTENT_NOT_READY,
    REPROMPT_NO_CITY,
    ERROR_GENERIC,
    TRENDING_INTRO,
    PLAY_COMMUNITY_INTRO,
    COMMUNITY_NEEDS_TOWN,
    REPROMPT_ASK_TOWN,
    ambiguous_reference_message,
    ambiguity_exhausted_message,
)
from src.utils.normalize_content_item import (
    content_title_for_speech,
    pick_content_credit,
)
from src.utils.normalize_content_item import is_playable_content_item
from src.utils.browse_catalog import (
    build_catalog_from_search_result,
    has_more_server_pages,
    catalog_search_context,
)
from src.utils.search_filters import wants_local_community_content
from src.services.playback import start_playback
from src.handlers.search import (
    auto_play_first_from_search,
    discover_content_via_search,
    _build_no_content_response,
    _build_search_outcome_response,
    _extract_slot_value,
    _raw_search_phrase,
    _resolve_content_for_playback,
)

def _has_active_browse_catalog(store: Dict[str, Any]) -> bool:
    """Check if there is an active browse catalog in the store."""
    catalog = get_browse_catalog(store)
    if catalog and catalog.get("items"):
        return True
    pending = store.get("pendingBrowseItems")
    return isinstance(pending, list) and len(pending) > 0


def _is_misrouted_browse_pagination(query: str) -> bool:
    """Detect whether a query is actually a browse-pagination phrase."""
    if not query:
        return False
    key = str(query).lower().strip()
    return key in (
        "show me more", "what are the next ones", "more", "more recordings",
        "more content", "next ones", "what else did you find", "keep going",
        "what comes next", "what are the next content found",
    )


async def _fetch_next_catalog_page(handler_input: HandlerInput, catalog: Dict[str, Any], *, deps: Dependencies | None = None):
    next_page = (catalog.get("currentPage") or 0) + 1
    ctx = catalog_search_context(catalog)
    search_result = await discover_content_via_search(handler_input, {
        "intent": ctx.get("intent"),
        "q": ctx.get("q"),
        "page": next_page,
        "limit": catalog.get("limit"),
    }, deps=deps)
    if search_result.get("failed") or not search_result.get("results"):
        return {"catalog": catalog, "failed": True}
    merged = build_catalog_from_search_result(
        search_result,
        **ctx,
        page=next_page,
        limit=catalog.get("limit"),
        existing_catalog=catalog,
        append=True,
    )
    set_browse_catalog(
        handler_input,
        merged,
        intent=catalog.get("intent"),
    )
    return {"catalog": merged, "failed": False}


class WhatsTrendingHandler(AbstractRequestHandler):

    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) in {
                "WhatsTrendingIntent",
                "PlayRecommendationIntent",
            }
        )

    async def handle(self, handler_input: HandlerInput):

        if not _get_user_id(handler_input):
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        active_store = get_store(handler_input)

        search_result = await discover_content_via_search(handler_input, deps=self._deps)
        if not search_result.get("results"):
            return _build_search_outcome_response(handler_input, search_result)

        first = search_result["results"][0]
        creator = first.get("creator")
        nested_creator_name = (
            creator.get("name") if isinstance(creator, dict) else None
        )
        response = await auto_play_first_from_search(handler_input, search_result, {
            "discoveryIntent": "WhatsTrendingIntent",
            "locality": active_store.get("locality"),
            "introOverride": TRENDING_INTRO(
                search_result.get("total_hits") or len(search_result["results"]),
                content_title_for_speech(first),
                pick_content_credit(first)
                or first.get("creatorName")
                or nested_creator_name,
            ),
        }, deps=self._deps)
        return response or _build_no_content_response(handler_input)


class BrowseContentHandler(AbstractRequestHandler):

    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        name = get_intent_name(handler_input)
        return (
            get_request_type(handler_input) == "IntentRequest"
            and name in ("BrowseContentIntent", "BrowseByCategoryIntent")
        )

    async def handle(self, handler_input: HandlerInput):

        if not _get_user_id(handler_input):
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        active_store = get_store(handler_input)

        browse_q = _extract_slot_value(handler_input, "query") or _raw_search_phrase(handler_input) or ""

        try:
            is_community = wants_local_community_content(handler_input, browse_q)
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

        search_result = await discover_content_via_search(handler_input, {"q": browse_q}, deps=self._deps)
        if not search_result.get("results"):
            if browse_q:
                return handler_input.response_builder \
                    .speak(ssml(SEARCH_NO_MATCH(browse_q))) \
                    .reprompt(ssml(WELCOME_REPROMPT)) \
                    .set_should_end_session(False) \
                    .response
            return _build_search_outcome_response(handler_input, search_result)

        resolved_locality = active_store.get("locality")
        intent_name = get_intent_name(handler_input)
        was_relaxed = bool(browse_q and search_result.get("search_relaxation"))

        response = await auto_play_first_from_search(handler_input, search_result, {
            "discoveryIntent": "browse_category" if intent_name == "BrowseByCategoryIntent" else "BrowseContentIntent",
            "q": browse_q,
            "locality": resolved_locality,
            "introOverride": PLAY_COMMUNITY_INTRO(resolved_locality, search_result.get("total_hits", 0))
            if is_community and not was_relaxed else None,
        }, deps=self._deps)
        return response or _build_no_content_response(handler_input)


class ShowMoreBrowseHandler(AbstractRequestHandler):

    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        if get_request_type(handler_input) != "IntentRequest":
            return False
        return get_intent_name(handler_input) == "ShowMoreBrowseIntent"

    async def handle(self, handler_input: HandlerInput):

        store = get_store(handler_input)
        pending = store.get("pendingAmbiguity")
        if isinstance(pending, dict) and pending.get("candidates"):
            candidates = list(pending["candidates"])
            offset = max(3, int(pending.get("spokenCandidateOffset") or 3))
            next_candidates = candidates[offset:offset + 3]
            if not next_candidates:
                next_candidates = list(pending.get("displayedCandidates") or candidates[:3])
                message = ambiguity_exhausted_message(next_candidates)
            else:
                message = ambiguous_reference_message("that name", next_candidates)
                pending = {
                    **pending,
                    "displayedCandidates": next_candidates,
                    "spokenCandidateOffset": offset + len(next_candidates),
                }
                update_store(handler_input, {"pendingAmbiguity": pending})
                activate_dialog(handler_input, "ambiguity", context=pending)
            return handler_input.response_builder \
                .speak(ssml(message)) \
                .reprompt(ssml("Please say one of the names I just offered.")) \
                .set_should_end_session(False) \
                .response

        catalog = get_browse_catalog(store)
        if not catalog or not catalog.get("items"):
            return handler_input.response_builder \
                .speak(ssml(PLAY_NO_PENDING_LIST)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        offset = catalog.get("spokenOffset", 0)
        if offset >= len(catalog["items"]) and has_more_server_pages(catalog):
            prev_len = len(catalog["items"])
            result = await _fetch_next_catalog_page(handler_input, catalog, deps=self._deps)
            catalog = result["catalog"]
            if result["failed"] or len(catalog["items"]) == prev_len:
                return handler_input.response_builder \
                    .speak(ssml(BROWSE_EXHAUSTED)) \
                    .reprompt(ssml(WELCOME_REPROMPT)) \
                    .set_should_end_session(False) \
                    .response

        if offset >= len(catalog["items"]):
            return handler_input.response_builder \
                .speak(ssml(BROWSE_EXHAUSTED)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        next_item = catalog["items"][offset]
        content = _resolve_content_for_playback(next_item, handler_input)
        if content:
            if is_playable_content_item(content):
                title = content_title_for_speech(content)
                credit = pick_content_credit(content)
                intro = f"Next up: {escape_ssml_lite(title)}, by {escape_ssml_lite(credit)}." \
                    if title and credit else "Next story."
                catalog["spokenOffset"] = offset + 1
                set_browse_catalog(
                    handler_input,
                    catalog,
                    intent=catalog.get("intent", "general"),
                )
                return await start_playback(
                    handler_input, content, intro, 0, {"preserveSessionQueue": True},
                )

        return handler_input.response_builder \
            .speak(ssml(CONTENT_NOT_READY)) \
            .reprompt(ssml(REPROMPT_NO_CITY)) \
            .set_should_end_session(False) \
            .response
