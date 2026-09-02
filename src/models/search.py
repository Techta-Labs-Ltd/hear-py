from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from ask_sdk_core.handler_input import HandlerInput

from config import settings
from src.alexa.context import RequestContext
from src.alexa.entities import AlexaEntities
from src.alexa.request import AlexaRequest
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.dialog import DialogStateManager
from src.models.playback_state import PlaybackQueue
from src.models.user import User
from src.utils.browse import BrowseUtils
from src.utils.content import ContentUtils
from src.utils.content_normalizer import ContentNormalizer
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilters, SearchFilterUtils
from src.utils.search_payload import SearchPayload


class Search:
    logger = logging.getLogger(__name__)

    @staticmethod
    def initial_search_queue_items(
        search_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return only the API page already loaded for immediate playback."""
        return [item for item in search_result.get("results") or [] if isinstance(item, dict)]

    @staticmethod
    def search_queue_pagination(search_result: dict[str, Any]) -> dict[str, Any]:
        """Build persisted lazy-pagination arguments for ``init_queue``."""
        payload = search_result.get("_search_payload")
        return {
            "search_payload": dict(payload) if isinstance(payload, dict) else None,
            "current_page": int(search_result.get("page") or 0),
            "total_pages": search_result.get("total_pages"),
            "page_limit": payload.get("limit") if isinstance(payload, dict) else None,
        }

    @staticmethod
    def _dependencies(deps: object | None):
        if deps is None:
            raise RuntimeError("Search requires injected dependencies")
        return deps

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def _extract_slot_value(handler_input: HandlerInput, slot_name: str) -> Optional[str]:
        return AlexaRequest.get_slot_value(handler_input, slot_name)

    @staticmethod
    def _raw_search_phrase(handler_input: HandlerInput) -> Optional[str]:
        """Get the raw query slot value from the intent."""
        try:
            return (
                handler_input.request_envelope.request.intent.get("slots", {})
                .get("query", None)
                .value
            )
        except Exception:
            pass
        return None

    @staticmethod
    def _resolve_content_for_playback(
        item: Dict[str, Any], handler_input: HandlerInput
    ) -> Optional[Dict[str, Any]]:
        """Check whether an item has playable audio, return it if so."""
        del handler_input
        return item if ContentNormalizer.is_playable_content_item(item) else None

    @staticmethod
    def _build_no_content_response(handler_input: HandlerInput):
        """Return a standard no-content-available response."""
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.NO_CONTENT_AVAILABLE))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def _build_search_outcome_response(
        handler_input: HandlerInput, search_result: Optional[Dict[str, Any]]
    ):
        """Build an error response from a failed or empty search result."""
        if search_result and search_result.get("failed"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.SEARCH_UNAVAILABLE))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if search_result and search_result.get("client_message"):
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.escape_ssml_lite(str(search_result["client_message"])))
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        search_payload = (search_result or {}).get("_search_payload") or {}
        if search_payload.get("query") or search_payload.get("q") or search_payload.get("filter"):
            requested = (
                (search_result or {}).get("_request_label")
                or search_payload.get("query")
                or search_payload.get("q")
                or "that request"
            )
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(SearchSpeech.search_no_match(requested))
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        return Search._build_no_content_response(handler_input)

    @staticmethod
    def _ambiguity_response(
        handler_input: HandlerInput,
        store: dict,
        nlp: dict,
        slots: dict,
    ) -> dict | None:
        ambiguous = slots.get("ambiguousReferences") or []
        if not ambiguous:
            return None
        reference = ambiguous[0]
        existing = store.get("pendingAmbiguity") or {}
        candidates = list(existing.get("candidates") or reference.get("candidates") or [])
        choices = Search._unique_ambiguity_choices(candidates)
        displayed = choices[:3]
        ambiguity_context = nlp.get("ambiguityContext")
        ambiguity_context = ambiguity_context if isinstance(ambiguity_context, dict) else {}
        pending = {
            **existing,
            **ambiguity_context,
            "requestId": nlp.get("requestId") or existing.get("requestId"),
            "intent": nlp.get("intent") or "general",
            "originalUtterance": nlp.get("originalUtterance")
            or existing.get("originalUtterance")
            or "",
            "searchPayload": dict(
                nlp.get("searchPayload")
                or slots.get("searchPlan")
                or existing.get("searchPayload")
                or {}
            ),
            "slots": {**dict(existing.get("slots") or {}), **dict(slots)},
            "candidates": candidates,
            "choiceCandidates": choices,
            "displayedCandidates": displayed,
            "spokenCandidateOffset": existing.get("spokenCandidateOffset") or min(3, len(choices)),
            "createdAt": existing.get("createdAt") or int(time.time()),
            "expiresAt": int(time.time()) + 300,
        }
        User.update(
            handler_input,
            {
                "pendingAmbiguity": pending,
                "awaitingLocationConfirm": False,
                "pendingLocationConfirm": None,
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.activate(handler_input, "ambiguity", context=pending)
        message_candidates = list(pending.get("displayedCandidates") or candidates[:3])
        directive = AlexaEntities.build_ambiguity_dynamic_entities_directive(choices)
        if directive:
            handler_input.response_builder.add_directive(directive)
        message = (
            SearchSpeech.ambiguity_retry_message(message_candidates)
            if nlp.get("ambiguityRetry")
            else SearchSpeech.ambiguous_reference_message(
                str(reference.get("phrase") or ""), message_candidates
            )
        )
        return {"results": [], "total_hits": 0, "failed": False, "client_message": message}

    @staticmethod
    def apply_publication_result_ambiguity(
        handler_input: HandlerInput,
        search_result: dict,
        *,
        intent: str,
        request_label: str | None = None,
    ) -> dict:
        choices = Search._unique_ambiguity_choices(
            list(search_result.get("_publication_choices") or [])
        )
        payload = dict(search_result.get("_search_payload") or {})
        filters = payload.get("filter") if isinstance(payload.get("filter"), dict) else {}
        query = str(payload.get("query") or "").strip()
        should_ask = bool(
            len(choices) > 1
            and (
                filters.get("isPublication")
                or intent == "publication"
                or (intent == "organization" and not query)
            )
        )
        if not should_ask:
            return search_result
        store = User.snapshot(handler_input)
        nlp = dict(RequestContext.request(handler_input).get("_nlp") or {})
        slots = dict(nlp.get("slots") or {})
        phrase = (
            request_label
            or SearchPayload.request_label(slots, query)
            or nlp.get("originalUtterance")
            or "that source"
        )
        limit = max(1, int(payload.get("limit") or len(choices) or 1))
        total_hits = max(0, int(search_result.get("total_hits") or len(choices)))
        total_pages = BrowseUtils.resolve_total_pages(
            total_hits,
            limit,
            search_result.get("total_pages"),
            len(choices),
        )
        candidate_pagination = {
            "kind": "publication",
            "currentPage": max(0, int(search_result.get("page") or payload.get("page") or 0)),
            "totalPages": total_pages,
            "totalHits": total_hits,
            "limit": limit,
        }
        slots["ambiguousReferences"] = [{"phrase": phrase, "candidates": choices}]
        special = Search._ambiguity_response(
            handler_input,
            store,
            {
                **nlp,
                "intent": intent,
                "searchPayload": payload,
                "slots": slots,
                "ambiguityContext": {"candidatePagination": candidate_pagination},
            },
            slots,
        )
        if not special:
            return search_result
        special.update(
            {
                "_search_payload": payload,
                "_request_label": phrase,
                "client_message": SearchSpeech.publication_ambiguity_message(choices[:3]),
            }
        )
        return special

    @staticmethod
    def _unresolved_response(slots: dict) -> dict | None:
        unresolved = slots.get("unresolvedReferences") or []
        if not unresolved:
            return None
        reference = unresolved[0]
        message = SearchSpeech.unresolved_reference_message(
            str(reference.get("phrase") or ""),
            list(reference.get("expectedTypes") or []),
        )
        return {"results": [], "total_hits": 0, "failed": False, "client_message": message}

    @staticmethod
    def _search_sort(handler_input, slots: dict, filters: dict) -> str | None:
        latest = bool(slots.get("latest"))
        if not latest:
            try:
                latest = SearchFilterUtils.wants_latest_playback(
                    Search._raw_search_phrase(handler_input) or ""
                )
            except Exception:
                latest = False
        if latest:
            return "latest"
        return "trending" if filters.get("isPublication") else None

    @staticmethod
    async def discover_content_via_search(
        handler_input: HandlerInput,
        options: Optional[Dict[str, Any]] = None,
        *,
        deps: object | None = None,
    ) -> Dict[str, Any]:
        d = Search._dependencies(deps)
        user_id = AlexaRequest.get_user_id(handler_input)
        if not user_id:
            return {"results": [], "total_hits": 0, "failed": True}
        opts = options or {}
        store = User.snapshot(handler_input)
        nlp = RequestContext.request(handler_input).get("_nlp", {})
        slots = nlp.get("slots") or {}
        special = Search._ambiguity_response(handler_input, store, nlp, slots)
        special = special or Search._unresolved_response(slots)
        if special:
            return special
        resolved_payload = SearchPayload.selected_resolution(nlp)
        query = SearchFilterUtils.normalize_search_query(
            resolved_payload.get("query") if resolved_payload else opts.get("q")
        )
        residual = slots.get("residualQuery")
        if not resolved_payload and isinstance(residual, str) and (
            not query or query == Search._raw_search_phrase(handler_input)
        ):
            query = residual
        filters = (
            SearchFilters.clean(resolved_payload.get("filter"))
            if resolved_payload
            else SearchPayload.resolution_filter(
                slots,
                opts.get("filter"),
                AlexaRequest.get_intent_name(handler_input) == "PlayPublicationIntent",
            )
        )
        intent = opts.get("intent") or nlp.get("intent") or "general"
        payload = SearchPayload.build(
            user_id,
            store,
            q=query,
            limit=resolved_payload.get("limit")
            or opts.get("limit")
            or settings.search_page_limit,
            page=resolved_payload.get("page", opts.get("page", 0)),
            sort=resolved_payload.get("sort")
            or Search._search_sort(handler_input, slots, filters),
            nlp_filter=filters,
        )
        logged_payload = {key: value for key, value in payload.items() if key != "alexaUserId"}
        Search.logger.info(
            "Hear: search request intent=%s payload=%s",
            intent,
            json.dumps(logged_payload, sort_keys=True, separators=(",", ":")),
        )
        await d.progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
        result = await d.heara.search(
            payload, timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input)
        )
        Search.logger.info(
            "Hear: search response intent=%s failed=%s total=%s returned=%s",
            intent,
            bool(result.get("failed")),
            result.get("total_hits", 0),
            len(result.get("results") or []),
        )
        result.setdefault("_search_payload", dict(payload))
        label = SearchPayload.request_label(slots, query)
        if label:
            result["_request_label"] = label
        result = Search.apply_publication_result_ambiguity(
            handler_input,
            result,
            intent=str(intent),
            request_label=label,
        )
        if isinstance(result.get("results"), list):
            result["results"] = ContentNormalizer.normalize_content_items(result["results"])
        return result

    @staticmethod
    async def _discover_content_avoiding_recent(
        handler_input: HandlerInput,
        search_options: Optional[Dict[str, Any]] = None,
        *,
        deps: object | None = None,
    ) -> Dict[str, Any]:
        """Search across multiple pages, skipping empty pages, to find fresh content."""
        opts = search_options or {}
        start_page = opts.get("page", 0)
        remaining = DeadlineBudget.get_lambda_remaining_ms(handler_input)
        max_pages = opts.get("maxPages") or (
            1 if isinstance(remaining, (int, float)) and remaining < 5500 else 3
        )
        last_result = None
        for page in range(start_page, start_page + max_pages):
            result = await Search.discover_content_via_search(
                handler_input, {**opts, "page": page}, deps=deps
            )
            last_result = result
            if result.get("failed"):
                return result
            if result.get("results"):
                return result
            total_pages = result.get("total_pages", 0)
            if total_pages > 0 and page + 1 >= total_pages:
                break
        return last_result or {"results": [], "total_hits": 0, "failed": False}

    @staticmethod
    async def auto_play_first_from_search(
        handler_input: HandlerInput,
        search_result: Dict[str, Any],
        options: Optional[Dict[str, Any]] = None,
        *,
        deps: object | None = None,
    ):
        """Take a search result, cache it as a browse catalog, and start playback of the first item."""
        d = Search._dependencies(deps)
        opts = options or {}
        if not search_result.get("results"):
            return Search._build_search_outcome_response(handler_input, search_result)
        store = User.snapshot(handler_input)
        intent = opts.get("discoveryIntent", "PlayContentIntent")
        q = opts.get("q", "")
        intro_override = opts.get("introOverride")
        catalog = BrowseUtils.build_catalog_from_search_result(
            search_result,
            intent=intent,
            q=q,
            search_payload=search_result.get("_search_payload"),
            page=0,
            limit=settings.search_page_limit,
            exclude_recent=PlaybackQueue.recent_exclude_filters(store),
        )
        d.browse.set_catalog(handler_input, catalog, intent=intent)
        first = search_result["results"][0]
        content = Search._resolve_content_for_playback(first, handler_input)
        if not content:
            return Search._build_next_playable_response(
                handler_input, store, search_result["results"], intent, deps=d
            )
        if not ContentNormalizer.is_playable_content_item(content):
            return Search._build_next_playable_response(
                handler_input, store, search_result["results"], intent, deps=d
            )
        title = ContentUtils.content_title_for_speech(content)
        credit = ContentUtils.pick_content_credit(content)
        total = search_result.get("total_hits") or len(search_result["results"])
        if intro_override:
            intro = intro_override
        elif title and credit:
            intro = f"I found {total} stories. Now playing {Speech.escape_ssml_lite(title)}, by {Speech.escape_ssml_lite(credit)}."
        elif title:
            intro = f"I found {total} stories. Now playing {Speech.escape_ssml_lite(title)}."
        else:
            intro = f"I found {total} stories. Now playing the first one."
        queue_items = Search.initial_search_queue_items(search_result)
        d.playback.queue.initialize(
            handler_input,
            queue_items,
            source=intent or "search",
            locality=store.get("locality"),
            start_index=0,
            **Search.search_queue_pagination(search_result),
        )
        return await d.playback.start(
            handler_input, content, intro, 0, {"preserveSessionQueue": True}
        )

    @staticmethod
    def _build_next_playable_response(
        handler_input: HandlerInput,
        store: Dict[str, Any],
        items: List[Dict[str, Any]],
        discovery_intent: str,
        *,
        deps: object | None = None,
    ):
        """Fallback: try subsequent items in the result set until a playable one is found."""
        d = Search._dependencies(deps)
        for i in range(1, len(items)):
            item = items[i]
            if not ContentNormalizer.is_playable_content_item(item):
                continue
            content = items[i]
            title = ContentUtils.content_title_for_speech(content)
            credit = ContentUtils.pick_content_credit(content)
            intro = (
                f"Now playing {Speech.escape_ssml_lite(title)}, by {Speech.escape_ssml_lite(credit)}."
                if title and credit
                else "Now playing the next story."
            )
            d.playback.queue.initialize(
                handler_input,
                items,
                source=discovery_intent or "search",
                locality=store.get("locality"),
                start_index=i,
            )
            return d.playback.start(
                handler_input, content, intro, 0, {"preserveSessionQueue": True}
            )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.CONTENT_NOT_READY))
            .reprompt(Ssml.ssml(Speech.REPROMPT_NO_CITY))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    async def play_from_followed_creators(
        handler_input: HandlerInput, *, deps: object | None = None
    ):
        """Play content from creators the user is following."""
        store = User.snapshot(handler_input)
        if store.get("awaitingFollow"):
            User.update(handler_input, {"awaitingFollow": False})
        followed = store.get("followedCreators") or []
        if not followed:
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.NO_FOLLOWED_CREATORS_TO_PLAY))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        creator_ids = [
            str(item["id"])
            for item in followed
            if isinstance(item, dict)
            and item.get("id")
            and (item.get("type", "creator") == "creator")
        ]
        organization_ids = [
            str(item["id"])
            for item in followed
            if isinstance(item, dict) and item.get("id") and (item.get("type") == "organization")
        ]
        follow_filter = {}
        if creator_ids:
            follow_filter["creatorIds"] = list(dict.fromkeys(creator_ids))
        if organization_ids:
            follow_filter["organizationIds"] = list(dict.fromkeys(organization_ids))
        search_result = await Search._discover_content_avoiding_recent(
            handler_input,
            {"q": "", "intent": "following", "filter": follow_filter},
            deps=deps,
        )
        if not search_result.get("results"):
            return Search._build_search_outcome_response(handler_input, search_result)
        response = await Search.auto_play_first_from_search(
            handler_input,
            search_result,
            {
                "discoveryIntent": "PlayContentIntent",
                "q": "",
                "introOverride": "Here is something from a source you follow.",
            },
            deps=deps,
        )
        return response or Search._build_no_content_response(handler_input)

    @staticmethod
    async def _play_first_search_result(
        handler_input: HandlerInput,
        search_result: Dict[str, Any],
        label: Optional[str] = None,
        *,
        deps: object | None = None,
    ):
        """Play the first result while retaining every server page for navigation."""
        d = Search._dependencies(deps)
        items = list(search_result.get("results") or [])
        if not items:
            return Search._build_no_content_response(handler_input)
        content = Search._resolve_content_for_playback(items[0], handler_input)
        if not content:
            return Search._build_no_content_response(handler_input)
        if not ContentNormalizer.is_playable_content_item(content):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.CONTENT_NOT_READY))
                .reprompt(Ssml.ssml(Speech.REPROMPT_NO_CITY))
                .set_should_end_session(False)
                .response
            )
        store = User.snapshot(handler_input)
        title = ContentUtils.content_title_for_speech(content)
        credit = ContentUtils.pick_content_credit(content) or label
        intro = Speech.LOCAL_CONTENT_FALLBACK(title, credit)
        payload = search_result.get("_search_payload") or {}
        intent = AlexaRequest.get_intent_name(handler_input) or "search"
        catalog = BrowseUtils.build_catalog_from_search_result(
            search_result,
            intent=intent,
            q=payload.get("query") or "",
            search_payload=payload,
            page=search_result.get("page", 0),
            limit=payload.get("limit") or settings.search_page_limit,
            exclude_recent=PlaybackQueue.recent_exclude_filters(store),
        )
        d.browse.set_catalog(handler_input, catalog, intent=intent)
        queue_items = Search.initial_search_queue_items(search_result)
        d.playback.queue.initialize(
            handler_input,
            queue_items,
            source=intent,
            locality=store.get("locality"),
            start_index=0,
            **Search.search_queue_pagination(search_result),
        )
        return await d.playback.start(
            handler_input, content, intro, 0, {"preserveSessionQueue": True}
        )

    @staticmethod
    def _has_active_browse_catalog(store: dict) -> bool:
        return BrowseUtils.has_active_browse_catalog(store)

    @staticmethod
    def _is_misrouted_browse_pagination(query: str) -> bool:
        return BrowseUtils.is_browse_pagination_query(query)

    @staticmethod
    async def _show_more_browse(handler_input, deps):
        return await deps.browse.more(handler_input)
