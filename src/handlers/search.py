from __future__ import annotations
import json
import logging
import time
from typing import Any, Dict, List, Optional
from ask_sdk_core.handler_input import HandlerInput
from config import settings
from src.dependencies import Dependencies
from src.services.browse import set_browse_catalog
from src.services.queue import init_queue, recent_exclude_filters
from src.services.store import get_store, update_store
from src.services.dialog_state import activate_dialog
from src.utils.skill_request import get_intent_name, get_user_id as _get_user_id
from src.utils.speech import (
    ssml,
    escape_ssml_lite,
    NO_CONTENT_AVAILABLE,
    SEARCH_UNAVAILABLE,
    SEARCH_NO_MATCH,
    WELCOME_REPROMPT,
    CONTENT_NOT_READY,
    REPROMPT_NO_CITY,
    LOCAL_CONTENT_FALLBACK,
    NO_FOLLOWED_CREATORS_TO_PLAY,
    unresolved_reference_message,
    ambiguous_reference_message,
    ambiguity_retry_message,
)
from src.utils.normalize_content_item import (
    content_title_for_speech,
    pick_content_credit,
    normalize_content_items,
)
from src.utils.normalize_content_item import is_playable_content_item
from src.utils.browse_catalog import build_catalog_from_search_result
from src.utils.search_filters import SearchPayload
from src.utils.search_query import normalize_search_query
from src.utils.dynamic_entities import build_ambiguity_dynamic_entities_directive
from src.utils.lambda_deadline import compute_search_timeout_ms, get_lambda_remaining_ms
from src.utils.search_filters import wants_latest_playback
from src.services.playback import start_playback
from src.services.search_queue import prefetch_search_queue_items
_DEFAULT_SEARCH_PAGE_LIMIT = settings.search_page_limit
logger = logging.getLogger(__name__)


def _unique_ambiguity_choices(candidates: list[dict]) -> list[dict]:
    seen: set[str] = set()
    choices = []
    for candidate in candidates:
        name = str(candidate.get("name") or "").strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            choices.append(candidate)
    return choices


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
    *, deps: Dependencies | None = None,
) -> Dict[str, Any]:
    d = deps or Dependencies()
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
        existing_ambiguity = store.get("pendingAmbiguity") or {}
        candidates = list(
            existing_ambiguity.get("candidates")
            or reference.get("candidates")
            or []
        )
        choices = _unique_ambiguity_choices(candidates)
        displayed = choices[:3]
        pending_ambiguity = {
            **existing_ambiguity,
            "requestId": nlp.get("requestId") or existing_ambiguity.get("requestId"),
            "intent": nlp.get("intent") or "general",
            "originalUtterance": (
                nlp.get("originalUtterance")
                or existing_ambiguity.get("originalUtterance")
                or ""
            ),
            "searchPayload": dict(
                nlp.get("searchPayload")
                or nlp_slots.get("searchPlan")
                or existing_ambiguity.get("searchPayload")
                or {}
            ),
            "slots": {
                **dict(existing_ambiguity.get("slots") or {}),
                **dict(nlp_slots),
            },
            "candidates": candidates,
            "choiceCandidates": choices,
            "displayedCandidates": displayed,
            "spokenCandidateOffset": (
                existing_ambiguity.get("spokenCandidateOffset")
                or min(3, len(choices))
            ),
            "createdAt": existing_ambiguity.get("createdAt") or int(time.time()),
            "expiresAt": int(time.time()) + 300,
        }
        update_store(handler_input, {
            "pendingAmbiguity": pending_ambiguity,
            "awaitingLocationConfirm": False,
            "pendingLocationConfirm": None,
            "_requiresReliableSave": True,
        })
        activate_dialog(handler_input, "ambiguity", context=pending_ambiguity)
        message_candidates = list(
            pending_ambiguity.get("displayedCandidates") or candidates[:3]
        )
        directive = build_ambiguity_dynamic_entities_directive(choices)
        if directive:
            handler_input.response_builder.add_directive(directive)
        return {
            "results": [],
            "total_hits": 0,
            "failed": False,
            "client_message": (
                ambiguity_retry_message(message_candidates)
                if nlp.get("ambiguityRetry")
                else ambiguous_reference_message(
                    str(reference.get("phrase") or ""), message_candidates,
                )
            ),
        }
    unresolved = nlp_slots.get("unresolvedReferences") or []
    if unresolved:
        reference = unresolved[0]
        return {
            "results": [],
            "total_hits": 0,
            "failed": False,
            "client_message": unresolved_reference_message(
                str(reference.get("phrase") or ""),
                list(reference.get("expectedTypes") or []),
            ),
        }

    query = normalize_search_query(opts.get("q"))
    page = opts.get("page", 0)
    intent_override = opts.get("intent")
    limit = opts.get("limit")

    nlp_filter = {}
    option_filter = opts.get("filter") or {}
    if isinstance(option_filter, dict):
        nlp_filter.update(option_filter)
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
    for key in ("latitude", "longitude"):
        if nlp_slots.get(key) is not None:
            nlp_filter[key] = nlp_slots[key]
    nlp_tags = nlp_slots.get("tags")
    if isinstance(nlp_tags, list) and nlp_tags:
        nlp_filter["tags"] = list(nlp_tags)
    nlp_filter["isLocal"] = bool(nlp_slots.get("isLocal"))
    nlp_filter["isRecommended"] = bool(nlp_slots.get("isRecommended"))
    search_plan_payload = nlp_slots.get("searchPlan") or {}
    search_plan_filter = search_plan_payload.get("filter") or {}
    if (
        nlp_slots.get("isPublication")
        or search_plan_filter.get("isPublication")
        or get_intent_name(handler_input) == "PlayPublicationIntent"
    ):
        nlp_filter["isPublication"] = True
    for key in ("publishedFrom", "publishedTo"):
        value = search_plan_filter.get(key, search_plan_payload.get(key))
        if value is not None:
            nlp_filter[key] = value

    residual = nlp_slots.get("residualQuery")
    if isinstance(residual, str) and (not query or query == _raw_search_phrase(handler_input)):
        query = residual

    intent = intent_override or nlp_intent or "general"

    nlp_latest = nlp_slots.get("latest") if nlp_slots else None
    try:
        raw_latest = not nlp_latest and wants_latest_playback(_raw_search_phrase(handler_input) or "")
    except Exception:
        raw_latest = False
    sort = (
        "latest" if (nlp_latest or raw_latest)
        else "trending" if nlp_filter.get("isPublication")
        else None
    )

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

    result = await d.heara.search(payload, timeout_ms=timeout_ms)
    logger.info(
        "Hear: search response intent=%s failed=%s total=%s returned=%s",
        intent,
        bool(result.get("failed")),
        result.get("total_hits", 0),
        len(result.get("results") or []),
    )
    result["_search_payload"] = dict(payload)
    category_name = str(nlp_slots.get("category") or "").strip()
    tag_names = [
        str(value).strip().replace("-", " ")
        for value in nlp_slots.get("tags") or []
        if str(value).strip()
    ]
    facet_name = category_name.replace("-", " ") or " and ".join(tag_names)
    source_name = str(
        nlp_slots.get("organizationName")
        or nlp_slots.get("creatorName")
        or nlp_slots.get("publicationName")
        or ""
    ).strip()
    if facet_name and source_name:
        result["_request_label"] = f"{facet_name} from {source_name}"
    elif facet_name or source_name:
        result["_request_label"] = facet_name or source_name
    elif query:
        result["_request_label"] = query
    if result and isinstance(result.get("results"), list):
        result["results"] = normalize_content_items(result["results"])
    return result


async def _discover_content_avoiding_recent(
    handler_input: HandlerInput, search_options: Optional[Dict[str, Any]] = None,
    *, deps: Dependencies | None = None,
) -> Dict[str, Any]:
    """Search across multiple pages, skipping empty pages, to find fresh content."""
    opts = search_options or {}
    start_page = opts.get("page", 0)
    remaining = get_lambda_remaining_ms(handler_input)
    max_pages = opts.get("maxPages") or (1 if isinstance(remaining, (int, float)) and remaining < 5500 else 3)
    last_result = None

    for page in range(start_page, start_page + max_pages):
        result = await discover_content_via_search(handler_input, {**opts, "page": page}, deps=deps)
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
    *, deps: Dependencies | None = None,
):
    """Take a search result, cache it as a browse catalog, and start playback of the first item."""
    d = deps or Dependencies()
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

    queue_items = await prefetch_search_queue_items(
        search_result,
        d.heara,
        timeout_ms=compute_search_timeout_ms(handler_input),
    )
    init_queue(
        handler_input,
        queue_items,
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
            items,
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


async def play_from_followed_creators(handler_input: HandlerInput, *, deps: Dependencies | None = None):
    """Play content from creators the user is following."""
    store = get_store(handler_input)
    if store.get("awaitingFollow"):
        update_store(handler_input, {"awaitingFollow": False})

    followed = store.get("followedCreators") or []
    if not followed:
        return handler_input.response_builder \
            .speak(ssml(NO_FOLLOWED_CREATORS_TO_PLAY)) \
            .reprompt(ssml(WELCOME_REPROMPT)) \
            .set_should_end_session(False) \
            .response

    creator_ids = [
        str(item["id"]) for item in followed
        if isinstance(item, dict) and item.get("id") and item.get("type", "creator") == "creator"
    ]
    organization_ids = [
        str(item["id"]) for item in followed
        if isinstance(item, dict) and item.get("id") and item.get("type") == "organization"
    ]
    follow_filter = {}
    if creator_ids:
        follow_filter["creatorIds"] = list(dict.fromkeys(creator_ids))
    if organization_ids:
        follow_filter["organizationIds"] = list(dict.fromkeys(organization_ids))
    search_result = await _discover_content_avoiding_recent(
        handler_input,
        {"q": "", "intent": "following", "filter": follow_filter},
        deps=deps,
    )
    if not search_result.get("results"):
        return _build_search_outcome_response(handler_input, search_result)

    response = await auto_play_first_from_search(handler_input, search_result, {
        "discoveryIntent": "PlayContentIntent",
        "q": "",
        "introOverride": "Here is something from a source you follow.",
    }, deps=deps)
    return response or _build_no_content_response(handler_input)


async def _play_first_search_result(handler_input: HandlerInput, items: List[Dict[str, Any]], label: Optional[str] = None, *, deps: Dependencies | None = None):
    """Play the first item from a list of search results directly."""
    del deps
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
