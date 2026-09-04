from __future__ import annotations

from typing import Any, Dict

from ask_sdk_core.handler_input import HandlerInput

from config import settings
from src.alexa.entities import AlexaEntities
from src.alexa.request import AlexaRequest
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.discovery import DiscoveryConstants
from src.models.dialog import DialogSelection, DialogStateManager
from src.models.user import User
from src.utils.browse import BrowseUtils
from src.utils.content import ContentUtils
from src.utils.content_normalizer import ContentNormalizer
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilterUtils
from src.utils.search_payload import SearchPayload


class Browse:
    def __init__(self, *, deps=None, store=None):
        self._deps = deps
        self._store = store or User()

    @property
    def dependencies(self):
        if self._deps is None:
            raise RuntimeError("Browse requires injected dependencies")
        return self._deps

    def snapshot(self, handler_input) -> dict:
        return self._store.snapshot(handler_input)

    def save_catalog(self, handler_input, fields: dict) -> dict:
        return self._store.update(handler_input, fields)

    def has_active_ambiguity(self, handler_input: HandlerInput) -> bool:
        pending = self.snapshot(handler_input).get("pendingAmbiguity")
        return isinstance(pending, dict) and bool(pending.get("candidates"))

    def dismiss_choices(self, handler_input: HandlerInput):
        DialogStateManager.dismiss_ambiguity(handler_input)
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(Speech.CHOICES_DISMISSED)
            )
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def _merge_ambiguity_candidates(existing: list[dict], incoming: list[dict]) -> list[dict]:
        merged = []
        seen: set[tuple[str, str]] = set()
        for candidate in [*existing, *incoming]:
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("id") or "").strip()
            name = str(candidate.get("name") or "").strip()
            key = (str(candidate.get("type") or "").casefold(), candidate_id.casefold())
            if not candidate_id or not name or key in seen:
                continue
            seen.add(key)
            merged.append(candidate)
        return merged

    @staticmethod
    def _choice_navigation_response(
        handler_input: HandlerInput,
        candidates: list[dict],
        message: str,
        reprompt: str,
    ):
        builder = (
            handler_input.response_builder.speak(Ssml.ssml(message))
            .reprompt(Ssml.ssml(reprompt))
            .set_should_end_session(False)
        )
        directive = AlexaEntities.build_ambiguity_dynamic_entities_directive(candidates)
        if directive:
            builder.add_directive(directive)
        return builder.response

    async def _fetch_next_ambiguity_page(
        self, handler_input: HandlerInput, pending: dict
    ) -> tuple[dict, bool]:
        pagination = dict(pending.get("candidatePagination") or {})
        limit = DiscoveryConstants.CHOICE_PAGE_SIZE
        next_page = max(0, int(pagination.get("currentPage") or 0)) + 1
        payload = SearchPayload.with_pagination(pending.get("searchPayload"), limit)
        payload["page"] = next_page
        payload = SearchPayload.with_identity(
            payload,
            alexa_user_id=AlexaRequest.get_user_id(handler_input),
            listener_id=User.snapshot(handler_input).get("listenerId"),
        )
        await self.dependencies.progressive.send(
            handler_input,
            Speech.SEARCH_MORE_PROGRESSIVE,
        )
        result = await self.dependencies.heara.search(
            payload,
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )
        if result.get("failed"):
            return pending, True
        existing = list(pending.get("choiceCandidates") or pending.get("candidates") or [])
        incoming = list(result.get("_publication_choices") or [])
        candidates = Browse._merge_ambiguity_candidates(existing, incoming)
        actual_payload = dict(result.get("_search_payload") or payload)
        current_page = max(0, int(result.get("page") or next_page))
        total_hits = max(
            len(candidates),
            int(result.get("total_hits") or pagination.get("totalHits") or len(candidates)),
        )
        total_pages = BrowseUtils.resolve_total_pages(
            total_hits,
            limit,
            result.get("total_pages") or pagination.get("totalPages"),
            len(candidates),
        )
        updated = {
            **pending,
            "searchPayload": actual_payload,
            "candidates": candidates,
            "choiceCandidates": candidates,
            "candidatePagination": {
                "kind": "publication",
                "currentPage": current_page,
                "totalPages": total_pages,
                "totalHits": total_hits,
                "limit": limit,
            },
        }
        return updated, False

    @staticmethod
    def _item_snapshot(item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        credit = ContentUtils.pick_content_credit(item)
        spoken = ContentUtils.content_title_for_speech(item)
        content_id = item.get("contentId") or item.get("id")
        return {
            "id": content_id,
            "contentId": content_id,
            "title": item.get("title"),
            "displayTitle": spoken or item.get("displayTitle"),
            "spokenTitle": spoken,
            "creator": credit or item.get("creator") or item.get("creatorName"),
            "creatorName": item.get("creatorName") or item.get("creator") or credit,
            "creatorId": item.get("creatorId"),
            "organizationId": item.get("organizationId"),
            "organizationName": item.get("organizationName"),
            "publicationId": item.get("publicationId"),
            "publicationTitle": item.get("publicationTitle"),
            "type": item.get("type"),
            "isPublication": bool(item.get("isPublication")),
            "trackIndex": item.get("trackIndex"),
            "trackCount": item.get("trackCount"),
            "summary": item.get("summary") or None,
            "category": item.get("category") or None,
            "audioUrl": item.get("audioUrl"),
            "playbackSpeeds": item.get("playbackSpeeds") or [],
            "durationMs": item.get("durationMs"),
        }

    def set_catalog(
        self,
        handler_input,
        catalog: dict | None,
        *,
        intent: str | None = None,
        category: str | None = None,
    ) -> dict:
        store = self.snapshot(handler_input)
        raw_items = catalog.get("items", []) if catalog else []
        prev = store.get("browseCatalog")
        same_session = BrowseUtils.is_same_browse_session(prev, catalog, intent) if prev else False
        has_fresh_spoken_menu = (
            isinstance(catalog.get("spokenMenu"), list) and len(catalog.get("spokenMenu") or []) > 0
            if catalog
            else False
        )
        if same_session:
            sorted_items = (
                BrowseUtils.merge_browse_items_preserve_order(prev.get("items", []), raw_items)
                if prev
                else raw_items
            )
        else:
            sorted_items = (
                raw_items
                if has_fresh_spoken_menu
                else BrowseUtils.sort_queue_items_by_listening_preferences(
                    raw_items, store.get("listeningPattern"), store.get("locality")
                )
            )
        browse_ids = [
            i.get("contentId") or i.get("id")
            for i in sorted_items
            if i.get("contentId") or i.get("id")
        ]
        cap = min(len(sorted_items), settings.HEAR_BROWSE_MAX_CATALOG or 50)
        capped = sorted_items[:cap]
        snapshot = [s for s in (self._item_snapshot(i) for i in capped) if s is not None]
        queue_cap = min(len(capped), settings.HEAR_QUEUE_PREFETCH_LIMIT or 20)
        browse_queue_items = (
            [BrowseUtils.clone_browse_menu_item(i) for i in capped[:queue_cap]]
            if queue_cap
            else None
        )
        clean = {
            "intent": (catalog.get("intent") if catalog else None) or intent or "general",
            "q": SearchFilterUtils.normalize_search_query(catalog.get("q")) if catalog else "",
            "categorySlug": catalog.get("categorySlug") or None if catalog else None,
            "tags": catalog.get("tags") or None if catalog else None,
            "limit": (catalog.get("limit") if catalog else None) or settings.search_page_limit,
            "currentPage": (catalog.get("currentPage") if catalog else None) or 0,
            "totalHits": (catalog.get("totalHits") if catalog else None) or len(capped),
            "totalPages": (catalog.get("totalPages") if catalog else None) or 0,
            "spokenOffset": (catalog.get("spokenOffset") if catalog else None) or 0,
            "items": capped,
            "spokenMenu": (catalog.get("spokenMenu") if catalog else None) or [],
        }
        return self.save_catalog(
            handler_input,
            {
                "browseCatalog": clean,
                "launchBrowseIds": browse_ids or None,
                "pendingDiscoveryIntent": intent or clean.get("intent") or None,
                "pendingDiscoveryCategory": category or None,
                "pendingBrowseItems": snapshot or None,
                "browseQueueItems": browse_queue_items,
            },
        )

    @staticmethod
    def get_catalog(store: dict) -> dict | None:
        if isinstance(store, dict):
            bc = store.get("browseCatalog")
            if bc and isinstance(bc.get("items"), list) and bc["items"]:
                return bc
            pbi = store.get("pendingBrowseItems")
            if isinstance(pbi, list) and pbi:
                return {
                    "intent": store.get("pendingDiscoveryIntent") or "general",
                    "q": "",
                    "categorySlug": None,
                    "tags": None,
                    "limit": settings.search_page_limit,
                    "currentPage": 0,
                    "totalHits": len(pbi),
                    "totalPages": 1,
                    "spokenOffset": 0,
                    "items": pbi,
                }
        return None

    @staticmethod
    def has_active_catalog(store: Dict[str, Any]) -> bool:
        return BrowseUtils.has_active_browse_catalog(store)

    @staticmethod
    def is_pagination_query(query: str) -> bool:
        return BrowseUtils.is_browse_pagination_query(query)

    @staticmethod
    async def _fetch_next_catalog_page(
        handler_input: HandlerInput,
        catalog: Dict[str, Any],
        *,
        deps: object | None = None,
    ):
        if deps is None:
            raise RuntimeError("Browse requires injected dependencies")
        d = deps
        next_page = (catalog.get("currentPage") or 0) + 1
        ctx = BrowseUtils.catalog_search_context(catalog)
        search_result = await d.search.discover_content_via_search(
            handler_input,
            {
                "intent": ctx.get("intent"),
                "q": ctx.get("q"),
                "page": next_page,
                "limit": catalog.get("limit"),
            },
            deps=d,
        )
        if search_result.get("failed") or not search_result.get("results"):
            return {"catalog": catalog, "failed": True}
        merged = BrowseUtils.build_catalog_from_search_result(
            search_result,
            **ctx,
            page=next_page,
            limit=catalog.get("limit"),
            existing_catalog=catalog,
            append=True,
        )
        d.browse.set_catalog(handler_input, merged, intent=catalog.get("intent"))
        return {"catalog": merged, "failed": False}

    async def trending(self, handler_input: HandlerInput):
        if not AlexaRequest.get_user_id(handler_input):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.ERROR_GENERIC))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        active_store = User.snapshot(handler_input)
        search_result = await self.dependencies.search.discover_content_via_search(
            handler_input, deps=self.dependencies
        )
        if not search_result.get("results"):
            return self.dependencies.search._build_search_outcome_response(
                handler_input, search_result
            )
        response = await self.dependencies.search.auto_play_first_from_search(
            handler_input,
            search_result,
            {
                "discoveryIntent": "WhatsTrendingIntent",
                "locality": active_store.get("locality"),
                "introOverride": SearchSpeech.trending_intro(
                    search_result.get("total_hits") or len(search_result["results"])
                ),
            },
            deps=self.dependencies,
        )
        return response or self.dependencies.search._build_no_content_response(handler_input)

    async def content(self, handler_input: HandlerInput):
        if not AlexaRequest.get_user_id(handler_input):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.ERROR_GENERIC))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        active_store = User.snapshot(handler_input)
        browse_q = (
            self.dependencies.search._extract_slot_value(handler_input, "query")
            or self.dependencies.search._raw_search_phrase(handler_input)
            or ""
        )
        try:
            is_community = AlexaRequest.wants_local_community_content(handler_input, browse_q)
        except Exception:
            is_community = False
        if is_community:
            has_location = (
                active_store.get("locality")
                or active_store.get("userCity")
                or active_store.get("latitude")
                or active_store.get("devicePostalCode")
            )
            if not has_location:
                User.update(handler_input, {"onboardingStage": "confirm_town_for_community"})
                return (
                    handler_input.response_builder.speak(Ssml.ssml(Speech.COMMUNITY_NEEDS_TOWN))
                    .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
                    .set_should_end_session(False)
                    .response
                )
        search_result = await self.dependencies.search.discover_content_via_search(
            handler_input, {"q": browse_q}, deps=self.dependencies
        )
        if not search_result.get("results"):
            if search_result.get("client_message"):
                return self.dependencies.search._build_search_outcome_response(
                    handler_input, search_result
                )
            if browse_q:
                return (
                    handler_input.response_builder.speak(
                        Ssml.ssml(SearchSpeech.search_no_match(browse_q))
                    )
                    .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                    .set_should_end_session(False)
                    .response
                )
            return self.dependencies.search._build_search_outcome_response(
                handler_input, search_result
            )
        resolved_locality = active_store.get("locality")
        intent_name = AlexaRequest.get_intent_name(handler_input)
        was_relaxed = bool(browse_q and search_result.get("search_relaxation"))
        response = await self.dependencies.search.auto_play_first_from_search(
            handler_input,
            search_result,
            {
                "discoveryIntent": "browse_category"
                if intent_name == "BrowseByCategoryIntent"
                else "BrowseContentIntent",
                "q": browse_q,
                "locality": resolved_locality,
                "introOverride": Speech.PLAY_COMMUNITY_INTRO(
                    resolved_locality, search_result.get("total_hits", 0)
                )
                if is_community and (not was_relaxed)
                else None,
            },
            deps=self.dependencies,
        )
        return response or self.dependencies.search._build_no_content_response(handler_input)

    async def _more_ambiguity(self, handler_input: HandlerInput, pending: dict):
        candidates = list(pending.get("choiceCandidates") or pending["candidates"])
        page_size = DiscoveryConstants.CHOICE_PAGE_SIZE
        offset = DialogSelection.current_choice_end(pending)
        next_candidates = candidates[offset : offset + page_size]
        load_failed = False
        if not next_candidates and DialogSelection.has_more_pages(pending):
            pending, load_failed = await self._fetch_next_ambiguity_page(handler_input, pending)
            candidates = list(
                pending.get("choiceCandidates") or pending.get("candidates") or []
            )
            next_candidates = candidates[offset : offset + page_size]
            if not load_failed:
                User.update(handler_input, {"pendingAmbiguity": pending})
                DialogStateManager.activate(handler_input, "ambiguity", context=pending)
        if load_failed:
            message = SearchSpeech.publication_choices_unavailable_message()
            return (
                handler_input.response_builder.speak(Ssml.ssml(message))
                .reprompt(Ssml.ssml("Say one of the earlier names, or say show more."))
                .set_should_end_session(False)
                .response
            )
        if not next_candidates:
            next_candidates = DialogSelection.displayed_choices(pending)
            publication_picker = (pending.get("candidatePagination") or {}).get(
                "kind"
            ) == "publication"
            message = (
                SearchSpeech.publication_choices_exhausted_message(
                    next_candidates,
                    has_previous=DialogSelection.displayed_has_previous(pending),
                )
                if publication_picker
                else SearchSpeech.ambiguity_exhausted_message(
                    next_candidates,
                    has_previous=DialogSelection.displayed_has_previous(pending),
                )
            )
        else:
            pagination = pending.get("candidatePagination") or {}
            next_offset = offset + len(next_candidates)
            has_more = DialogSelection.has_more_choices(pending, candidates, next_offset)
            has_previous = offset > 0
            message = (
                SearchSpeech.more_publication_choices_message(
                    next_candidates,
                    has_more=has_more,
                    has_previous=has_previous,
                )
                if pagination.get("kind") == "publication"
                else SearchSpeech.ambiguous_reference_message(
                    "that name",
                    next_candidates,
                    has_more=has_more,
                    has_previous=has_previous,
                )
            )
            pending = {
                **pending,
                "displayedCandidates": next_candidates,
                "spokenCandidateOffset": next_offset,
            }
            User.update(handler_input, {"pendingAmbiguity": pending})
            DialogStateManager.activate(handler_input, "ambiguity", context=pending)
        publication_picker = (pending.get("candidatePagination") or {}).get(
            "kind"
        ) == "publication"
        has_more = bool(next_candidates) and DialogSelection.has_more_choices(
            pending,
            candidates,
            int(pending.get("spokenCandidateOffset") or len(next_candidates)),
        )
        has_previous = DialogSelection.displayed_has_previous(pending)
        reprompt = SearchSpeech.choice_reprompt(
            next_candidates,
            publication_picker=publication_picker,
            has_more=has_more,
            has_previous=has_previous,
        )
        return Browse._choice_navigation_response(
            handler_input, next_candidates, message, reprompt
        )

    async def more(self, handler_input: HandlerInput):
        store = User.snapshot(handler_input)
        pending = store.get("pendingAmbiguity")
        if isinstance(pending, dict) and pending.get("candidates"):
            return await self._more_ambiguity(handler_input, pending)
        catalog = self.dependencies.browse.get_catalog(store)
        if not catalog or not catalog.get("items"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.PLAY_NO_PENDING_LIST))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        offset = catalog.get("spokenOffset", 0)
        if offset >= len(catalog["items"]) and BrowseUtils.has_more_server_pages(catalog):
            prev_len = len(catalog["items"])
            result = await Browse._fetch_next_catalog_page(
                handler_input, catalog, deps=self.dependencies
            )
            catalog = result["catalog"]
            if result["failed"] or len(catalog["items"]) == prev_len:
                return (
                    handler_input.response_builder.speak(Ssml.ssml(Speech.BROWSE_EXHAUSTED))
                    .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                    .set_should_end_session(False)
                    .response
                )
        if offset >= len(catalog["items"]):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.BROWSE_EXHAUSTED))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        next_item = catalog["items"][offset]
        content = self.dependencies.search._resolve_content_for_playback(next_item, handler_input)
        if content:
            if ContentNormalizer.is_playable_content_item(content):
                title = ContentUtils.content_title_for_speech(content)
                credit = ContentUtils.pick_content_credit(content)
                intro = (
                    f"Next up: {Speech.escape_ssml_lite(title)}, by {Speech.escape_ssml_lite(credit)}."
                    if title and credit
                    else "Next story."
                )
                catalog["spokenOffset"] = offset + 1
                self.dependencies.browse.set_catalog(
                    handler_input, catalog, intent=catalog.get("intent", "general")
                )
                return await self.dependencies.playback.start(
                    handler_input, content, intro, 0, {"preserveSessionQueue": True}
                )
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.CONTENT_NOT_READY))
            .reprompt(Ssml.ssml(Speech.REPROMPT_NO_CITY))
            .set_should_end_session(False)
            .response
        )

    async def previous(self, handler_input: HandlerInput):
        pending = self.snapshot(handler_input).get("pendingAmbiguity")
        if not isinstance(pending, dict) or not pending.get("candidates"):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.PLAY_NO_PENDING_LIST))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        candidates = list(pending.get("choiceCandidates") or pending["candidates"])
        current_start = DialogSelection.current_choice_start(pending)
        previous_start = max(0, current_start - DiscoveryConstants.CHOICE_PAGE_SIZE)
        previous_candidates = candidates[
            previous_start : previous_start + DiscoveryConstants.CHOICE_PAGE_SIZE
        ]
        has_more = DialogSelection.has_more_choices(
            pending,
            candidates,
            previous_start + len(previous_candidates),
        )
        publication_picker = (pending.get("candidatePagination") or {}).get(
            "kind"
        ) == "publication"
        if current_start == 0:
            message = (
                SearchSpeech.first_publication_choices_message(
                    previous_candidates,
                    has_more=has_more,
                    has_previous=False,
                )
                if publication_picker
                else SearchSpeech.ambiguous_reference_message(
                    "that name",
                    previous_candidates,
                    has_more=has_more,
                    has_previous=False,
                )
            )
        else:
            pending = {
                **pending,
                "displayedCandidates": previous_candidates,
                "spokenCandidateOffset": previous_start + len(previous_candidates),
            }
            User.update(handler_input, {"pendingAmbiguity": pending})
            DialogStateManager.activate(handler_input, "ambiguity", context=pending)
            message = (
                SearchSpeech.previous_publication_choices_message(
                    previous_candidates,
                    has_more=has_more,
                    has_previous=previous_start > 0,
                )
                if publication_picker
                else SearchSpeech.ambiguous_reference_message(
                    "that name",
                    previous_candidates,
                    has_more=has_more,
                    has_previous=previous_start > 0,
                )
            )
        has_previous = DialogSelection.displayed_has_previous(pending)
        reprompt = SearchSpeech.choice_reprompt(
            previous_candidates,
            publication_picker=publication_picker,
            has_more=has_more,
            has_previous=has_previous,
        )
        return Browse._choice_navigation_response(
            handler_input, previous_candidates, message, reprompt
        )
