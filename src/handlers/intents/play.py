from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from config import settings
from config.permission_scopes import DEVICE_ADDRESS, GEOLOCATION_READ

from src.services.storage.persistence import (
    get_store, update_store, set_browse_catalog, get_browse_catalog,
    init_queue, recent_exclude_filters,
)
from src.services.api import search
from src.utils.skill_request import get_request_type, get_intent_name, get_user_id as _get_user_id
from src.utils.speech import (
    ssml, escape_ssml_lite, NO_CONTENT_AVAILABLE, SEARCH_UNAVAILABLE,
    SEARCH_NO_MATCH, WELCOME_REPROMPT, PLAY_NO_PENDING_LIST, BROWSE_EXHAUSTED,
    CONTENT_NOT_READY, REPROMPT_NO_CITY, ERROR_GENERIC, LOCAL_CONTENT_FALLBACK,
    TRENDING_INTRO, PLAY_COMMUNITY_INTRO, COMMUNITY_NEEDS_TOWN, REPROMPT_ASK_TOWN,
    NO_FOLLOWED_CREATORS_TO_PLAY,
    ASK_TALKING_NEWSPAPER, ASK_TALKING_NEWSPAPER_REPROMPT,
    TALKING_NEWSPAPER_NOT_RECOGNIZED,
    unresolved_reference_message,
    ambiguous_reference_message,
)
from src.utils.normalize_content_item import (
    content_title_for_speech, pick_content_credit, normalize_content_items,
)
from src.utils.normalize_content_item import is_playable_content_item
from src.utils.browse_catalog import (
    build_catalog_from_search_result, has_more_server_pages, catalog_search_context,
)
from src.utils.search_filters import SearchPayload
from src.utils.lambda_deadline import (
    compute_search_timeout_ms, get_lambda_remaining_ms,
)
from src.utils.search_filters import (
    wants_latest_playback,
    wants_play_from_followed_creators, wants_local_community_content,
)
from src.services.playback.start import start_playback
from src.resolver.normalize import is_generic_organization_request

logger = logging.getLogger(__name__)
PERMISSIONS = {"DEVICE_ADDRESS": DEVICE_ADDRESS, "GEOLOCATION": GEOLOCATION_READ}

_DEFAULT_SEARCH_PAGE_LIMIT = settings.search_page_limit


def _summarize_intent_slots(handler_input: HandlerInput) -> Dict[str, Any]:
    """Extract slot values from the Alexa intent."""
    slots = None
    try:
        slots = handler_input.request_envelope.request.intent.get("slots")
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
    slots = _summarize_intent_slots(handler_input)
    value = slots.get(slot_name)
    return str(value).strip() if value is not None and str(value).strip() else None


def _raw_search_phrase(handler_input: HandlerInput) -> Optional[str]:
    """Get the raw query slot value from the intent."""
    try:
        return handler_input.request_envelope.request.intent.get("slots", {}).get("query", None).value
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
    del handler_input
    return item if is_playable_content_item(item) else None


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
    search_payload = (search_result or {}).get("_search_payload") or {}
    if search_payload.get("query") or search_payload.get("q") or search_payload.get("filter"):
        requested = (
            (search_result or {}).get("_request_label")
            or search_payload.get("query")
            or search_payload.get("q")
            or "that request"
        )
        return handler_input.response_builder \
            .speak(ssml(SEARCH_NO_MATCH(requested))) \
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
    ambiguous = nlp_slots.get("ambiguousReferences") or []
    if ambiguous:
        reference = ambiguous[0]
        return {
            "results": [],
            "total_hits": 0,
            "failed": False,
            "client_message": ambiguous_reference_message(
                str(reference.get("phrase") or ""),
                list(reference.get("candidates") or []),
            ),
        }
    unresolved = nlp_slots.get("unresolvedReferences") or []

    query = str(opts.get("q", ""))
    page = opts.get("page", 0)
    intent_override = opts.get("intent")
    limit = opts.get("limit")

    nlp_filter = {}
    if nlp_slots.get("creatorIds"):
        nlp_filter["creatorIds"] = list(nlp_slots["creatorIds"])
    if nlp_slots.get("organizationIds"):
        nlp_filter["organizationIds"] = list(nlp_slots["organizationIds"])
    if nlp_slots.get("publicationIds"):
        nlp_filter["publicationIds"] = list(nlp_slots["publicationIds"])
    if nlp_slots.get("category"):
        nlp_filter["categorySlugs"] = [str(nlp_slots["category"]).strip()]
    city_val = nlp_slots.get("city") or nlp_slots.get("placeName")
    if city_val:
        nlp_filter["city"] = str(city_val).strip()
    nlp_tags = nlp_slots.get("tags")
    if isinstance(nlp_tags, list) and nlp_tags:
        nlp_filter["tags"] = list(nlp_tags)
    nlp_filter["isLocal"] = bool(nlp_slots.get("isLocal"))
    nlp_filter["isRecommended"] = bool(nlp_slots.get("isRecommended"))
    search_plan_payload = nlp_slots.get("searchPlan") or {}
    for key in ("publishedFrom", "publishedTo"):
        if search_plan_payload.get(key) is not None:
            nlp_filter[key] = search_plan_payload[key]

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

    logged_payload = {
        key: value
        for key, value in payload.items()
        if key != "alexaUserId"
    }
    logger.info(
        "Hear: search request intent=%s payload=%s",
        intent,
        json.dumps(logged_payload, sort_keys=True, separators=(",", ":")),
    )

    result = await search(payload, timeout_ms=timeout_ms)
    logger.info(
        "Hear: search response intent=%s failed=%s total=%s returned=%s",
        intent,
        bool(result.get("failed")),
        result.get("total_hits", 0),
        len(result.get("results") or []),
    )
    result["_search_payload"] = dict(payload)
    category_name = str(nlp_slots.get("category") or "").strip()
    source_name = str(
        nlp_slots.get("organizationName")
        or nlp_slots.get("creatorName")
        or nlp_slots.get("publicationName")
        or ""
    ).strip()
    if category_name and source_name:
        result["_request_label"] = f"{category_name} from {source_name}"
    elif category_name or source_name:
        result["_request_label"] = category_name or source_name
    elif query:
        result["_request_label"] = query
    if result and isinstance(result.get("results"), list):
        result["results"] = normalize_content_items(result["results"])
    return result


async def _discover_content_avoiding_recent(
    handler_input: HandlerInput, search_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Search across multiple pages, skipping empty pages, to find fresh content."""
    opts = search_options or {}
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

    catalog = build_catalog_from_search_result(
        search_result,
        intent=intent,
        q=q,
        search_payload=search_result.get("_search_payload"),
        page=0,
        limit=_DEFAULT_SEARCH_PAGE_LIMIT,
        exclude_recent=recent_exclude_filters(store),
    )
    set_browse_catalog(handler_input, catalog, intent=intent)

    first = search_result["results"][0]
    content = _resolve_content_for_playback(first, handler_input)
    if not content:
        return _build_next_playable_response(handler_input, store, search_result["results"], intent)

    if not is_playable_content_item(content):
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

    init_queue(
        handler_input,
        [{"contentId": i.get("contentId")} for i in search_result["results"]],
        source=intent or "search",
        locality=store.get("locality"),
        start_index=0,
    )

    return await start_playback(handler_input, content, intro, 0, {"preserveSessionQueue": True})


def _build_next_playable_response(
    handler_input: HandlerInput, store: Dict[str, Any],
    items: List[Dict[str, Any]], discovery_intent: str,
):
    """Fallback: try subsequent items in the result set until a playable one is found."""
    for i in range(1, len(items)):
        item = items[i]
        if not is_playable_content_item(item):
            continue
        content = items[i]
        title = content_title_for_speech(content)
        credit = pick_content_credit(content)
        intro = (
            f"Now playing {escape_ssml_lite(title)}, by {escape_ssml_lite(credit)}."
            if title and credit else "Now playing the next story."
        )
        init_queue(
            handler_input,
            [{"contentId": it.get("contentId")} for it in items],
            source=discovery_intent or "search",
            locality=store.get("locality"),
            start_index=i,
        )
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

    if not is_playable_content_item(content):
        return handler_input.response_builder \
            .speak(ssml(CONTENT_NOT_READY)) \
            .reprompt(ssml(REPROMPT_NO_CITY)) \
            .set_should_end_session(False) \
            .response

    store = get_store(handler_input)
    title = content_title_for_speech(content)
    credit = pick_content_credit(content) or label
    intro = LOCAL_CONTENT_FALLBACK(title, credit)

    init_queue(
        handler_input,
        [{"contentId": i.get("contentId")} for i in items],
        source=get_intent_name(handler_input) or "search",
        locality=store.get("locality"),
        start_index=0,
    )

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


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


class WhatsTrendingHandler(AbstractRequestHandler):
    """Handles the What's Trending intent — plays trending content."""

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

        search_result = await discover_content_via_search(handler_input)
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
        })

        if not search_result.get("results"):
            fallback = await _discover_content_avoiding_recent(handler_input, {"q": ""})
            if fallback.get("results"):
                response = await auto_play_first_from_search(handler_input, fallback, {
                    "discoveryIntent": "PlayContentIntent", "q": "",
                    "locality": get_store(handler_input).get("locality"),
                    "introOverride": f"{SEARCH_NO_MATCH(creator_label)} Here are some other picks for you.",
                })
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

        generic_request = (
            bool(nlp_slots.get("genericOrganizationRequest"))
            or is_generic_organization_request(raw_phrase)
            or is_generic_organization_request(org_query)
        )
        if generic_request or (not org_query and not resolved_org):
            update_store(handler_input, {"awaitingOrganizationName": True})
            return handler_input.response_builder \
                .speak(ssml(ASK_TALKING_NEWSPAPER)) \
                .reprompt(ssml(ASK_TALKING_NEWSPAPER_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        if nlp_slots.get("organizationFollowUp") and not resolved_org:
            update_store(handler_input, {"awaitingOrganizationName": True})
            return handler_input.response_builder \
                .speak(ssml(TALKING_NEWSPAPER_NOT_RECOGNIZED(org_query))) \
                .reprompt(ssml(ASK_TALKING_NEWSPAPER_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        if resolved_org:
            update_store(handler_input, {"awaitingOrganizationName": False})

        search_result = await discover_content_via_search(handler_input, {
            "q": nlp_slots.get("residualQuery", "") if resolved_org else org_query,
            "intent": "organization",
        })

        if not search_result.get("results"):
            fallback = await _discover_content_avoiding_recent(handler_input, {"q": ""})
            if fallback.get("results"):
                response = await auto_play_first_from_search(handler_input, fallback, {
                    "discoveryIntent": "PlayContentIntent", "q": "",
                    "locality": active_store.get("locality"),
                    "introOverride": f"{SEARCH_NO_MATCH(org_label)} Here are some other picks for you.",
                })
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
