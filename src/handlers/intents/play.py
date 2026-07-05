from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.utils.request_util import get_slot_value

from config import settings
from config.permission_scopes import DEVICE_ADDRESS, GEOLOCATION_READ

from src.services.persistence import (
    get_store, update_store, set_browse_catalog, get_browse_catalog,
    init_queue, clear_queue, recent_exclude_filters,
)
from src.services.api import search
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml, escape_ssml_lite, NO_CONTENT_AVAILABLE, SEARCH_UNAVAILABLE,
    SEARCH_NO_MATCH, WELCOME_REPROMPT, PLAY_NO_PENDING_LIST, BROWSE_EXHAUSTED,
    CONTENT_NOT_READY, REPROMPT_NO_CITY, ERROR_GENERIC, LOCAL_CONTENT_FALLBACK,
    TRENDING_INTRO, PLAY_COMMUNITY_INTRO, COMMUNITY_NEEDS_TOWN, REPROMPT_ASK_TOWN,
    CONTENT_ABOUT_PHRASE, LAUNCH_CHOICE_OUTRO, PLAY_CHOICE_INVALID,
    NO_FOLLOWED_CREATORS_TO_PLAY,
)
from src.utils.normalize_content_item import (
    content_title_for_speech, pick_content_credit, normalize_content_items,
    pick_summary,
)
from src.utils.audio import resolve_track_audio
from src.utils.feedback_gate import enforce_interaction_gate
from src.utils.browse_catalog import (
    build_catalog_from_search_result, slice_speak_window,
    has_more_server_pages, catalog_search_context, merge_spoken_menu_entries,
)
from src.utils.search_filters import SearchPayload, to_slug
from src.utils.lambda_deadline import (
    compute_search_timeout_ms, get_lambda_remaining_ms,
    api_options, has_budget_for_api,
)
from src.utils.playback_context import (
    read_audio_player_context, is_audio_player_active, resolve_active_playback_token,
)
from src.utils.search_filters import (
    wants_latest_playback,
    wants_play_from_followed_creators, wants_local_community_content,
)
from src.utils.playback_start import start_playback

logger = logging.getLogger(__name__)
PERMISSIONS = {"DEVICE_ADDRESS": DEVICE_ADDRESS, "GEOLOCATION": GEOLOCATION_READ}

_DEFAULT_SEARCH_PAGE_LIMIT = settings.search_page_limit


def _get_user_id(handler_input: HandlerInput) -> Optional[str]:
    """Extract Alexa user ID from the request context."""
    ctx = handler_input.request_envelope.context
    if ctx and hasattr(ctx, "system") and ctx.system and ctx.system.user:
        return ctx.system.user.user_id
    return None


def _summarize_intent_slots(handler_input: HandlerInput) -> Dict[str, Any]:
    """Extract slot values from the Alexa intent."""
    slots = None
    try:
        slots = handler_input.request_envelope.request.intent.slots
    except Exception:
        pass
    if not slots or not isinstance(slots, dict):
        return {}
    out = {}
    for name, slot in slots.items():
        if not slot:
            continue
        val = getattr(slot, "value", None)
        if val:
            out[name] = val
        elif hasattr(slot, "resolutions"):
            try:
                out[name] = slot.resolutions.resolutionsPerAuthority[0].values[0].value.name
            except Exception:
                out[name] = None
    return out


def _extract_slot_value(handler_input: HandlerInput, slot_name: str) -> Optional[str]:
    """Extract a single slot value by name."""
    try:
        return get_slot_value(handler_input, slot_name)
    except Exception:
        slots = _summarize_intent_slots(handler_input)
        return slots.get(slot_name)


def _raw_search_phrase(handler_input: HandlerInput) -> Optional[str]:
    """Get the raw query slot value from the intent."""
    try:
        return handler_input.request_envelope.request.intent.slots.get("query", None).value
    except Exception:
        pass
    return None


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


def _resolve_content_for_playback(item: Dict[str, Any], handler_input: HandlerInput) -> Optional[Dict[str, Any]]:
    """Check whether an item has playable audio, return it if so."""
    if not item or not item.get("id"):
        return None
    has_playable = item.get("audioUrl") or (
        isinstance(item.get("tracks"), list)
        and any(t and t.get("audioUrl") for t in item["tracks"])
    )
    if has_playable:
        return item
    return None


def _build_no_content_response(handler_input: HandlerInput):
    """Return a standard no-content-available response."""
    return handler_input.response_builder \
        .speak(ssml(NO_CONTENT_AVAILABLE)) \
        .reprompt(ssml(WELCOME_REPROMPT)) \
        .set_should_end_session(False) \
        .response


def _build_search_outcome_response(handler_input: HandlerInput, search_result: Optional[Dict[str, Any]]):
    """Build an error response from a failed or empty search result."""
    if search_result and search_result.get("failed"):
        return handler_input.response_builder \
            .speak(ssml(SEARCH_UNAVAILABLE)) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response
    if search_result and search_result.get("client_message"):
        return handler_input.response_builder \
            .speak(ssml(escape_ssml_lite(str(search_result["client_message"])))) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response
    return _build_no_content_response(handler_input)


async def discover_content_via_search(
    handler_input: HandlerInput, options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run a search against the Hear API and return normalized results."""
    opts = options or {}
    user_id = _get_user_id(handler_input)
    if not user_id:
        return {"results": [], "total_hits": 0, "failed": True}

    store = get_store(handler_input)
    attrs = handler_input.attributes_manager.get_request_attributes()
    nlp = attrs.get("_nlp", {}) if attrs else {}
    nlp_slots = nlp.get("slots") or {}
    nlp_intent = nlp.get("intent")

    query = str(opts.get("q", ""))
    page = opts.get("page", 0)
    intent_override = opts.get("intent")
    limit = opts.get("limit")

    nlp_filter = {}
    if nlp_slots.get("creatorQuery"):
        nlp_filter["creator"] = str(nlp_slots["creatorQuery"]).strip()
    if nlp_slots.get("organizationQuery"):
        nlp_filter["organization"] = str(nlp_slots["organizationQuery"]).strip()
    if nlp_slots.get("category"):
        nlp_filter["category"] = str(nlp_slots["category"]).strip()
    city_val = nlp_slots.get("city") or nlp_slots.get("placeName")
    if city_val:
        nlp_filter["location"] = str(city_val).strip()
    nlp_tags = nlp_slots.get("tags")
    if isinstance(nlp_tags, list) and nlp_tags:
        nlp_filter["tags"] = list(nlp_tags)

    residual = nlp_slots.get("residualQuery")
    if isinstance(residual, str) and (not query or query == _raw_search_phrase(handler_input)):
        query = residual

    intent = intent_override or nlp_intent or "general"

    nlp_latest = nlp_slots.get("latest") if nlp_slots else None
    try:
        raw_latest = not nlp_latest and wants_latest_playback(_raw_search_phrase(handler_input) or "")
    except Exception:
        raw_latest = False
    sort = "latest" if (nlp_latest or raw_latest) else None

    page_limit = limit or _DEFAULT_SEARCH_PAGE_LIMIT

    payload = SearchPayload.build(
        handler_input, store,
        q=query,
        limit=page_limit,
        page=page,
        sort=sort,
        nlp_filter=nlp_filter,
    )

    timeout_ms = compute_search_timeout_ms(handler_input)

    logger.info(
        "Hear: search intent=%s q=%s page=%s limit=%s",
        intent, payload.get("q"), page, page_limit,
    )

    result = await search(payload, timeout_ms=timeout_ms)
    if result and isinstance(result.get("results"), list):
        result["results"] = normalize_content_items(result["results"])
    return result


async def _discover_content_avoiding_recent(
    handler_input: HandlerInput, search_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Search across multiple pages, skipping empty pages, to find fresh content."""
    opts = search_options or {}
    store = get_store(handler_input)
    start_page = opts.get("page", 0)
    remaining = get_lambda_remaining_ms(handler_input)
    max_pages = opts.get("maxPages") or (1 if isinstance(remaining, (int, float)) and remaining < 5500 else 3)
    last_result = None

    for page in range(start_page, start_page + max_pages):
        result = await discover_content_via_search(handler_input, {**opts, "page": page})
        last_result = result
        if result.get("failed"):
            return result
        if result.get("results"):
            return result
        total_pages = result.get("total_pages", 0)
        if total_pages > 0 and page + 1 >= total_pages:
            break

    return last_result or {"results": [], "total_hits": 0, "failed": False}


async def auto_play_first_from_search(
    handler_input: HandlerInput, search_result: Dict[str, Any],
    options: Optional[Dict[str, Any]] = None,
):
    """Take a search result, cache it as a browse catalog, and start playback of the first item."""
    opts = options or {}
    if not search_result.get("results"):
        return _build_search_outcome_response(handler_input, search_result)

    store = get_store(handler_input)
    intent = opts.get("discoveryIntent", "PlayContentIntent")
    q = opts.get("q", "")
    intro_override = opts.get("introOverride")

    catalog = build_catalog_from_search_result(search_result, {
        "intent": intent,
        "q": q,
        "page": 0,
        "limit": _DEFAULT_SEARCH_PAGE_LIMIT,
        "excludeRecent": recent_exclude_filters(store),
    })
    set_browse_catalog(handler_input, catalog, {"intent": intent})

    first = search_result["results"][0]
    content = _resolve_content_for_playback(first, handler_input)
    if not content:
        return _build_next_playable_response(handler_input, store, search_result["results"], intent)

    track_info = resolve_track_audio(content, 0)
    if not track_info.get("audioUrl"):
        return _build_next_playable_response(handler_input, store, search_result["results"], intent)

    title = content_title_for_speech(content)
    credit = pick_content_credit(content)
    total = search_result.get("total_hits") or len(search_result["results"])

    if intro_override:
        intro = intro_override
    elif title and credit:
        intro = f"I found {total} stories. Now playing {escape_ssml_lite(title)}, by {escape_ssml_lite(credit)}."
    elif title:
        intro = f"I found {total} stories. Now playing {escape_ssml_lite(title)}."
    else:
        intro = f"I found {total} stories. Now playing the first one."

    init_queue(handler_input, [{"id": i.get("id")} for i in search_result["results"]], {
        "source": intent or "search",
        "locality": store.get("locality"),
        "startIndex": 0,
    })

    return await start_playback(handler_input, content, intro, 0, {"preserveSessionQueue": True})


def _build_next_playable_response(
    handler_input: HandlerInput, store: Dict[str, Any],
    items: List[Dict[str, Any]], discovery_intent: str,
):
    """Fallback: try subsequent items in the result set until a playable one is found."""
    for i in range(1, len(items)):
        item = items[i]
        has_audio = item.get("audioUrl") or (
            isinstance(item.get("tracks"), list)
            and any(t and t.get("audioUrl") for t in item["tracks"])
        )
        if not has_audio:
            continue
        content = items[i]
        track_info = resolve_track_audio(content, 0)
        if not track_info or not track_info.get("audioUrl"):
            continue
        title = content_title_for_speech(content)
        credit = pick_content_credit(content)
        intro = (
            f"Now playing {escape_ssml_lite(title)}, by {escape_ssml_lite(credit)}."
            if title and credit else "Now playing the next story."
        )
        init_queue(handler_input, [{"id": it.get("id")} for it in items], {
            "source": discovery_intent or "search",
            "locality": store.get("locality"),
            "startIndex": i,
        })
        return start_playback(handler_input, content, intro, 0, {"preserveSessionQueue": True})

    return handler_input.response_builder \
        .speak(ssml(CONTENT_NOT_READY)) \
        .reprompt(ssml(REPROMPT_NO_CITY)) \
        .set_should_end_session(False) \
        .response


async def play_from_followed_creators(handler_input: HandlerInput):
    """Play content from creators the user is following."""
    store = get_store(handler_input)
    if store.get("awaitingFollow") or store.get("awaitingNotificationOptIn"):
        update_store(handler_input, {
            "awaitingFollow": False,
            "awaitingNotificationOptIn": False,
        })

    followed = store.get("followedCreators") or []
    if not followed:
        return handler_input.response_builder \
            .speak(ssml(NO_FOLLOWED_CREATORS_TO_PLAY)) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    search_result = await _discover_content_avoiding_recent(handler_input, {"q": "", "intent": "following"})
    if not search_result.get("results"):
        return _build_search_outcome_response(handler_input, search_result)

    response = await auto_play_first_from_search(handler_input, search_result, {
        "discoveryIntent": "PlayContentIntent",
        "q": "",
        "introOverride": "Here is something from creators you follow.",
    })
    return response or _build_no_content_response(handler_input)


async def _play_first_search_result(handler_input: HandlerInput, items: List[Dict[str, Any]], label: Optional[str] = None):
    """Play the first item from a list of search results directly."""
    content = _resolve_content_for_playback(items[0], handler_input)
    if not content:
        return _build_no_content_response(handler_input)

    track_info = resolve_track_audio(content, 0)
    if not track_info.get("audioUrl"):
        return handler_input.response_builder \
            .speak(ssml(CONTENT_NOT_READY)) \
            .reprompt(ssml(REPROMPT_NO_CITY)) \
            .set_should_end_session(False) \
            .response

    store = get_store(handler_input)
    title = content_title_for_speech(content)
    credit = pick_content_credit(content) or label
    intro = LOCAL_CONTENT_FALLBACK(title, credit)

    init_queue(handler_input, [{"id": i.get("id")} for i in items], {
        "source": get_intent_name(handler_input) or "search",
        "locality": store.get("locality"),
        "startIndex": 0,
    })

    return await start_playback(handler_input, content, intro, 0, {"preserveSessionQueue": True})


async def _fetch_next_catalog_page(handler_input: HandlerInput, catalog: Dict[str, Any]):
    """Fetch the next page of catalog content from the API and merge it."""
    next_page = (catalog.get("currentPage") or 0) + 1
    ctx = catalog_search_context(catalog)
    search_result = await discover_content_via_search(handler_input, {
        "intent": ctx.get("intent"),
        "q": ctx.get("q"),
        "page": next_page,
        "limit": catalog.get("limit"),
    })
    if search_result.get("failed") or not search_result.get("results"):
        return {"catalog": catalog, "failed": True}
    merged = build_catalog_from_search_result(search_result, {
        **ctx,
        "page": next_page,
        "limit": catalog.get("limit"),
        "existingCatalog": catalog,
        "append": True,
    })
    set_browse_catalog(handler_input, merged, {"intent": catalog.get("intent")})
    return {"catalog": merged, "failed": False}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


class WhatsTrendingHandler(AbstractRequestHandler):
    """Handles the What's Trending intent — plays trending content."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "WhatsTrendingIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated

        if not _get_user_id(handler_input):
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        active_store = get_store(handler_input)
        pass

        search_result = await discover_content_via_search(handler_input)
        if not search_result.get("results"):
            return _build_search_outcome_response(handler_input, search_result)

        response = await auto_play_first_from_search(handler_input, search_result, {
            "discoveryIntent": "WhatsTrendingIntent",
            "locality": active_store.get("locality"),
            "introOverride": TRENDING_INTRO(),
        })
        return response or _build_no_content_response(handler_input)


class PlayContentHandler(AbstractRequestHandler):
    """Handles the PlayContent intent — general content play."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        name = get_intent_name(handler_input)
        return (
            get_request_type(handler_input) == "IntentRequest"
            and name == "PlayContentIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        try:
            gated = enforce_interaction_gate(handler_input)
            if gated:
                return gated

            if not _get_user_id(handler_input):
                return handler_input.response_builder \
                    .speak(ssml(ERROR_GENERIC)) \
                    .reprompt(WELCOME_REPROMPT) \
                    .set_should_end_session(False) \
                    .response

            active_store = get_store(handler_input)
            pass

            raw_phrase = _raw_search_phrase(handler_input)
            search_q = None

            if not search_q:
                search_q = _extract_slot_value(handler_input, "query")
            if not search_q:
                search_q = _raw_search_phrase(handler_input)

            try:
                if wants_play_from_followed_creators(handler_input, search_q or raw_phrase or ""):
                    return await play_from_followed_creators(handler_input)
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

            search_result = await discover_content_via_search(handler_input, {"q": search_q or ""}) \
                if search_q \
                else await _discover_content_avoiding_recent(handler_input, {"q": ""})

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
                    )
            except Exception:
                pass

            was_relaxed = bool(search_q and search_result.get("search_relaxation"))
            discover_intro = None
            if not was_relaxed and is_community:
                resolve_loc = active_store.get("locality")
                discover_intro = PLAY_COMMUNITY_INTRO(resolve_loc, search_result.get("total_hits", 0))

            response = await auto_play_first_from_search(handler_input, search_result, {
                "discoveryIntent": "PlayContentIntent",
                "q": search_q,
                "locality": active_store.get("locality"),
                "introOverride": discover_intro,
            })
            return response or _build_no_content_response(handler_input)

        except Exception as err:
            logger.error("Hear: PlayContentHandler failed %s", err)
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response


class PlayByCreatorHandler(AbstractRequestHandler):
    """Handles the PlayByCreator intent — plays content by a specific creator."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "PlayByCreatorIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated

        if not _get_user_id(handler_input):
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        active_store = get_store(handler_input)
        pass

        attrs = handler_input.attributes_manager.get_request_attributes()
        nlp = attrs.get("_nlp", {}) if attrs else {}
        creator_query = (nlp.get("slots", {}).get("creatorQuery") if nlp else None) or \
            _extract_slot_value(handler_input, "query") or _raw_search_phrase(handler_input)
        raw_phrase = _raw_search_phrase(handler_input)

        if creator_query and _is_misrouted_browse_pagination(creator_query) \
                and _has_active_browse_catalog(active_store):
            return await ShowMoreBrowseHandler().handle(handler_input)

        if not creator_query:
            search_result = await discover_content_via_search(handler_input, {"q": "", "intent": "general"})
            if not search_result.get("results"):
                return _build_search_outcome_response(handler_input, search_result)
            response = await auto_play_first_from_search(handler_input, search_result, {
                "discoveryIntent": "PlayContentIntent", "q": "",
            })
            return response or _build_no_content_response(handler_input)

        search_result = await discover_content_via_search(handler_input, {
            "q": creator_query, "intent": "creator",
        })

        if not search_result.get("results"):
            fallback = await _discover_content_avoiding_recent(handler_input, {"q": ""})
            if fallback.get("results"):
                response = await auto_play_first_from_search(handler_input, fallback, {
                    "discoveryIntent": "PlayContentIntent", "q": "",
                    "locality": get_store(handler_input).get("locality"),
                    "introOverride": f"{SEARCH_NO_MATCH(creator_query)} Here are some other picks for you.",
                })
                return response or _build_no_content_response(handler_input)
            return handler_input.response_builder \
                .speak(ssml(SEARCH_NO_MATCH(creator_query))) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        try:
            if wants_latest_playback(raw_phrase or ""):
                return await _play_first_search_result(
                    handler_input, search_result["results"], label=creator_query,
                )
        except Exception:
            pass

        was_relaxed = bool(search_result.get("search_relaxation"))
        response = await auto_play_first_from_search(handler_input, search_result, {
            "discoveryIntent": "PlayByCreatorIntent",
            "q": creator_query,
            "locality": get_store(handler_input).get("locality"),
            "introOverride": None if was_relaxed
            else f"Here is what I found for {escape_ssml_lite(creator_query)}.",
        })
        return response or _build_no_content_response(handler_input)


class PlayByOrganizationHandler(AbstractRequestHandler):
    """Handles the PlayByOrganization intent — plays content by an organization."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "PlayByOrganizationIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated

        if not _get_user_id(handler_input):
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        active_store = get_store(handler_input)
        pass

        attrs = handler_input.attributes_manager.get_request_attributes()
        nlp = attrs.get("_nlp", {}) if attrs else {}
        org_query = (nlp.get("slots", {}).get("organizationQuery") if nlp else None) or \
            _extract_slot_value(handler_input, "query") or _raw_search_phrase(handler_input)

        if org_query and _is_misrouted_browse_pagination(org_query) \
                and _has_active_browse_catalog(active_store):
            return await ShowMoreBrowseHandler().handle(handler_input)

        if not org_query:
            search_result = await discover_content_via_search(handler_input, {"q": "", "intent": "general"})
            if not search_result.get("results"):
                return _build_search_outcome_response(handler_input, search_result)
            response = await auto_play_first_from_search(handler_input, search_result, {
                "discoveryIntent": "PlayContentIntent", "q": "",
            })
            return response or _build_no_content_response(handler_input)

        search_result = await discover_content_via_search(handler_input, {
            "q": org_query, "intent": "organization",
        })

        if not search_result.get("results"):
            fallback = await _discover_content_avoiding_recent(handler_input, {"q": ""})
            if fallback.get("results"):
                response = await auto_play_first_from_search(handler_input, fallback, {
                    "discoveryIntent": "PlayContentIntent", "q": "",
                    "locality": active_store.get("locality"),
                    "introOverride": f"{SEARCH_NO_MATCH(org_query)} Here are some other picks for you.",
                })
                return response or _build_no_content_response(handler_input)
            return handler_input.response_builder \
                .speak(ssml(SEARCH_NO_MATCH(org_query))) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        raw_phrase = _raw_search_phrase(handler_input)
        try:
            if wants_latest_playback(raw_phrase or ""):
                return await _play_first_search_result(
                    handler_input, search_result["results"], label=org_query,
                )
        except Exception:
            pass

        was_relaxed = bool(search_result.get("search_relaxation"))
        response = await auto_play_first_from_search(handler_input, search_result, {
            "discoveryIntent": "PlayByOrganizationIntent",
            "q": "",
            "locality": active_store.get("locality"),
            "introOverride": None if was_relaxed
            else f"Here is what I found from {escape_ssml_lite(org_query)}.",
        })
        return response or _build_no_content_response(handler_input)


class BrowseContentHandler(AbstractRequestHandler):
    """Handles BrowseContent and BrowseByCategory intents."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        name = get_intent_name(handler_input)
        return (
            get_request_type(handler_input) == "IntentRequest"
            and name in ("BrowseContentIntent", "BrowseByCategoryIntent")
        )

    async def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated

        if not _get_user_id(handler_input):
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        active_store = get_store(handler_input)
        pass

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

        search_result = await discover_content_via_search(handler_input, {"q": browse_q})
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
        })
        return response or _build_no_content_response(handler_input)


class ShowMoreBrowseHandler(AbstractRequestHandler):
    """Handles the ShowMoreBrowse intent — paginates browse catalogs."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "ShowMoreBrowseIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated

        store = get_store(handler_input)
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
            result = await _fetch_next_catalog_page(handler_input, catalog)
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
            track_info = resolve_track_audio(content, 0)
            if track_info and track_info.get("audioUrl"):
                title = content_title_for_speech(content)
                credit = pick_content_credit(content)
                intro = f"Next up: {escape_ssml_lite(title)}, by {escape_ssml_lite(credit)}." \
                    if title and credit else "Next story."
                catalog["spokenOffset"] = offset + 1
                set_browse_catalog(handler_input, catalog, {"intent": catalog.get("intent", "general")})
                return await start_playback(
                    handler_input, content, intro, 0, {"preserveSessionQueue": True},
                )

        return handler_input.response_builder \
            .speak(ssml(CONTENT_NOT_READY)) \
            .reprompt(ssml(REPROMPT_NO_CITY)) \
            .set_should_end_session(False) \
            .response
