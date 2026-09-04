from __future__ import annotations

import logging

from src.alexa.availability_speech import AvailabilitySpeech
from src.alexa.context import RequestContext
from src.alexa.entities import AlexaEntities
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.availability import AvailabilityConstants
from src.constants.dialog import DialogConstants
from src.constants.discovery import DiscoveryConstants
from src.models.availability_data import AvailabilityData
from src.models.dialog import DialogSelection, DialogStateManager
from src.models.search import Search
from src.models.user import User
from src.utils.content import ContentUtils
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilters
from src.utils.search_payload import SearchPayload


class Availability:
    logger = logging.getLogger(__name__)
    __slots__ = ("_deps",)

    def __init__(self, *, deps: object | None = None) -> None:
        if deps is None:
            raise RuntimeError("Availability requires injected dependencies")
        self._deps = deps

    @staticmethod
    def _response(handler_input, speech: str, reprompt: str, candidates=None):
        builder = (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(reprompt))
            .set_should_end_session(False)
        )
        directive = AlexaEntities.build_ambiguity_dynamic_entities_directive(list(candidates or []))
        if directive:
            builder.add_directive(directive)
        return builder.response

    @staticmethod
    def _local_payload(handler_input, nlp: dict) -> dict:
        store = User.snapshot(handler_input)
        slots = nlp.get("slots") if isinstance(nlp.get("slots"), dict) else {}
        existing = nlp.get("searchPayload") or slots.get("searchPlan") or {}
        if existing:
            payload = SearchPayload.with_pagination(existing, DiscoveryConstants.CHOICE_PAGE_SIZE)
            payload["limit"] = DiscoveryConstants.CHOICE_PAGE_SIZE
            filters = SearchPayload.resolution_filter(slots, payload.get("filter"))
            payload["filter"] = SearchFilters.clean(filters)
            payload["isLocal"] = True
        else:
            filters = SearchPayload.resolution_filter(slots, {"isLocal": True})
            payload = SearchPayload.build(
                AlexaRequest.get_user_id(handler_input),
                store,
                q=str(slots.get("residualQuery") or ""),
                limit=DiscoveryConstants.CHOICE_PAGE_SIZE,
                page=0,
                sort="nearest",
                nlp_filter=filters,
            )
        return SearchPayload.with_identity(
            payload,
            alexa_user_id=AlexaRequest.get_user_id(handler_input),
            listener_id=store.get("listenerId"),
        )

    async def _availability(self, handler_input, availability_filter: dict, page: int) -> dict:
        return await self._deps.heara.availability(
            {
                "filter": availability_filter,
                "page": max(0, int(page or 0)),
                "limit": DiscoveryConstants.CHOICE_PAGE_SIZE,
            },
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )

    def _activate(self, handler_input, context: dict) -> None:
        context["displayedCandidates"] = AvailabilityData.displayed(context)
        context["choiceCandidates"] = list(context.get("candidates") or [])
        DialogStateManager.activate(
            handler_input,
            AvailabilityConstants.DIALOG_TYPE,
            context=context,
        )

    def _choice_response(self, handler_input, context: dict, position: str = "initial"):
        displayed = AvailabilityData.displayed(context)
        has_more = AvailabilityData.has_more(context)
        has_previous = max(0, int(context.get("offset") or 0)) > 0
        kind = str(context.get("kind") or "")
        if kind == AvailabilityConstants.SOURCE_KIND:
            speech = AvailabilitySpeech.local_source_choices(
                displayed,
                position=position,
                has_more=has_more,
                has_previous=has_previous,
                requested_city=context.get("requestedCity"),
            )
        elif kind == AvailabilityConstants.PUBLICATION_KIND:
            speech = AvailabilitySpeech.publication_choices(
                displayed,
                source_name=context.get("source", {}).get("name")
                if position == "initial"
                else None,
                publication_count=context.get("publicationCount")
                if position == "initial"
                else None,
                position=position,
                has_more=has_more,
                has_previous=has_previous,
            )
        else:
            speech = AvailabilitySpeech.track_choices(
                displayed,
                position=position,
                has_more=has_more,
                has_previous=has_previous,
            )
        reprompt = AvailabilitySpeech.choice_reprompt(
            kind, len(displayed), has_more, has_previous
        )
        self._activate(handler_input, context)
        return self._response(handler_input, speech, reprompt, displayed)

    async def begin_local(self, handler_input, nlp: dict | None = None):
        resolved = dict(nlp or RequestContext.request(handler_input).get("_nlp") or {})
        payload = self._local_payload(handler_input, resolved)
        if AvailabilityData.request_scope(payload) != AvailabilityConstants.LOCATION_KIND:
            return await self._fallback_local_search(handler_input)
        location = AvailabilityData.location_from_payload(payload, User.snapshot(handler_input))
        requested_city = AvailabilityData.requested_city(resolved, payload)
        if not location:
            User.update(handler_input, {"onboardingStage": "confirm_town_for_community"})
            return self._response(
                handler_input,
                Speech.COMMUNITY_NEEDS_TOWN,
                Speech.REPROMPT_ASK_TOWN,
            )
        await self._deps.progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
        result = await self._availability(handler_input, {"location": location}, 0)
        candidates = AvailabilityData.source_candidates(result)
        if result.get("failed") or not candidates:
            return await self._fallback_local_search(handler_input)
        context = {
            "kind": AvailabilityConstants.SOURCE_KIND,
            "candidates": candidates,
            "offset": 0,
            "apiPage": int(result.get("page") or 0),
            "totalPages": int(result.get("total_pages") or 0),
            "hasMore": bool(result.get("has_more")),
            "availabilityFilter": {"location": location},
            "baseSearchPayload": payload,
            "requestedCity": requested_city,
        }
        if len(candidates) == 1 and not AvailabilityData.remote_more(context):
            context["singleChoice"] = True
            self._activate(handler_input, context)
            return self._response(
                handler_input,
                AvailabilitySpeech.one_local_source(
                    candidates[0]["name"], requested_city=requested_city
                ),
                "Say yes to hear it, or no to choose something else.",
                candidates,
            )
        return self._choice_response(handler_input, context)

    async def handle_resolution(self, handler_input, resolution: dict, payload: dict, label: str):
        scope = AvailabilityData.request_scope(payload)
        source = AvailabilityData.source_from_resolution(resolution) if scope else None
        if scope == AvailabilityConstants.SOURCE_KIND and source:
            await self._deps.progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
            return await self._begin_source(handler_input, source, payload)
        if scope == AvailabilityConstants.LOCATION_KIND and (
            resolution.get("intent") == "local" or AvailabilityData.has_location_payload(payload)
        ):
            resolution_slots = (
                resolution.get("slots") if isinstance(resolution.get("slots"), dict) else {}
            )
            nlp = {
                "intent": "local",
                "searchPayload": payload,
                "requestedLocation": bool(
                    resolution_slots.get("city") or resolution_slots.get("placeName")
                ),
                "slots": {"isLocal": True, **resolution_slots},
            }
            return await self.begin_local(handler_input, nlp)
        return None

    @staticmethod
    def _source_availability_filter(source: dict) -> dict:
        key = "organizationId" if source.get("type") == "organization" else "creatorId"
        return {key: source.get("id")}

    async def _begin_source(self, handler_input, source: dict, base_payload: dict):
        result = await self._availability(
            handler_input, self._source_availability_filter(source), 0
        )
        if result.get("failed"):
            return await self._fallback_search(
                handler_input,
                base_payload,
                source.get("type") or "search",
                source.get("name"),
            )
        publication_count = int(result.get("publication_count") or 0)
        track_count = int(result.get("standalone_track_count") or 0)
        publications = AvailabilityData.publication_candidates(result)
        if publication_count <= 0:
            return await self._play_source_directly(handler_input, source, base_payload)
        publication_context = {
            "kind": AvailabilityConstants.PUBLICATION_KIND,
            "source": source,
            "candidates": publications,
            "offset": 0,
            "apiPage": int(result.get("page") or 0),
            "totalPages": int(result.get("total_pages") or 0),
            "hasMore": bool(result.get("has_more")),
            "availabilityFilter": self._source_availability_filter(source),
            "baseSearchPayload": base_payload,
            "publicationCount": publication_count,
            "trackCount": track_count,
        }
        if track_count <= 0:
            if not publications:
                return await self._play_source_directly(handler_input, source, base_payload)
            return self._choice_response(handler_input, publication_context)
        format_candidates = [
            {
                "type": "format",
                "id": "publication",
                "name": "publications",
                "synonyms": ["publication", "a publication", "the publications"],
            },
            {
                "type": "format",
                "id": "track",
                "name": "tracks",
                "synonyms": ["track", "a track", "individual tracks"],
            },
        ]
        context = {
            **publication_context,
            "kind": AvailabilityConstants.FORMAT_KIND,
            "candidates": format_candidates,
            "publicationCandidates": publications,
        }
        self._activate(handler_input, context)
        publication_name = (
            publications[0]["name"] if publication_count == 1 and publications else None
        )
        return self._response(
            handler_input,
            AvailabilitySpeech.source_content_question(
                source["name"], publication_count, track_count, publication_name
            ),
            AvailabilitySpeech.content_type_reprompt(publication_count, track_count),
            format_candidates,
        )

    @staticmethod
    def _source_search_payload(handler_input, source: dict, base_payload: dict, page: int = 0):
        store = User.snapshot(handler_input)
        payload = SearchPayload.with_pagination(base_payload, DiscoveryConstants.CHOICE_PAGE_SIZE)
        filters = SearchFilters.replace_source(payload.get("filter"), source["type"], source["id"])
        filters = SearchFilters.without(
            filters,
            "city",
            "countryCode",
            "latitude",
            "longitude",
            "publicationIds",
        )
        filters["isPublication"] = False
        payload.update(
            {
                "query": str(payload.get("query") or ""),
                "filter": filters,
                "page": max(0, int(page or 0)),
                "limit": DiscoveryConstants.CHOICE_PAGE_SIZE,
                "isLocal": False,
            }
        )
        return SearchPayload.with_identity(
            payload,
            alexa_user_id=AlexaRequest.get_user_id(handler_input),
            listener_id=store.get("listenerId"),
        )

    async def _search_source(self, handler_input, source: dict, base_payload: dict, page: int = 0):
        payload = self._source_search_payload(handler_input, source, base_payload, page)
        result = await self._deps.heara.search(
            payload,
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )
        result.setdefault("_search_payload", payload)
        result.setdefault("_request_label", source.get("name"))
        return result

    async def _play_source_directly(self, handler_input, source: dict, base_payload: dict):
        result = await self._search_source(handler_input, source, base_payload)
        if not result.get("results"):
            return Search._build_search_outcome_response(handler_input, result)
        first = result["results"][0]
        intro = AvailabilitySpeech.playing_choice(
            ContentUtils.content_title_for_speech(first), source.get("name")
        )
        DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
        return await Search.auto_play_first_from_search(
            handler_input,
            result,
            {
                "discoveryIntent": source.get("type") or "search",
                "q": result.get("_search_payload", {}).get("query") or "",
                "introOverride": intro,
            },
            deps=self._deps,
        )

    async def _fallback_search(
        self,
        handler_input,
        payload: dict,
        intent: str,
        request_label: str | None = None,
    ):
        result = await self._deps.heara.search(
            payload,
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )
        result.setdefault("_search_payload", payload)
        if request_label:
            result.setdefault("_request_label", request_label)
        result = Search.apply_publication_result_ambiguity(
            handler_input,
            result,
            intent=intent,
            request_label=request_label,
        )
        if not result.get("results"):
            return Search._build_search_outcome_response(handler_input, result)
        return await Search.auto_play_first_from_search(
            handler_input,
            result,
            {
                "discoveryIntent": intent,
                "q": payload.get("query") or "",
            },
            deps=self._deps,
        )

    async def _fallback_local_search(self, handler_input):
        result = await Search.discover_content_via_search(
            handler_input,
            {"q": "", "intent": "local"},
            deps=self._deps,
        )
        if not result.get("results"):
            return Search._build_search_outcome_response(handler_input, result)
        return await Search.auto_play_first_from_search(
            handler_input,
            result,
            {
                "discoveryIntent": "local",
                "q": "",
            },
            deps=self._deps,
        )

    async def _begin_tracks(self, handler_input, context: dict):
        source = dict(context.get("source") or {})
        base_payload = dict(context.get("baseSearchPayload") or {})
        await self._deps.progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
        result = await self._search_source(handler_input, source, base_payload)
        if not result.get("results"):
            return Search._build_search_outcome_response(handler_input, result)
        first = result["results"][0]
        DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
        return await Search.auto_play_first_from_search(
            handler_input,
            result,
            {
                "discoveryIntent": source.get("type") or "search",
                "q": result.get("_search_payload", {}).get("query") or "",
                "introOverride": AvailabilitySpeech.playing_choice(
                    ContentUtils.content_title_for_speech(first), source.get("name")
                ),
            },
            deps=self._deps,
        )

    async def _play_selected(self, handler_input, candidate: dict, source: dict):
        store = User.snapshot(handler_input)
        if candidate.get("type") == "publication":
            payload = SearchPayload.for_publication(
                {}, [candidate.get("id")], DiscoveryConstants.CHOICE_PAGE_SIZE
            )
        else:
            payload = {
                "query": "",
                "filter": SearchFilters.content(candidate.get("id")),
                "page": 0,
                "limit": 1,
            }
        payload = SearchPayload.with_identity(
            payload,
            alexa_user_id=AlexaRequest.get_user_id(handler_input),
            listener_id=store.get("listenerId"),
        )
        await self._deps.progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
        result = await self._deps.heara.search(
            payload,
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )
        result.setdefault("_search_payload", payload)
        if not result.get("results"):
            return Search._build_search_outcome_response(handler_input, result)
        DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
        return await Search.auto_play_first_from_search(
            handler_input,
            result,
            {
                "discoveryIntent": candidate.get("type") or "search",
                "q": "",
                "introOverride": AvailabilitySpeech.playing_choice(
                    candidate.get("name")
                    or ContentUtils.content_title_for_speech(result["results"][0]),
                    source.get("name"),
                ),
            },
            deps=self._deps,
        )

    @staticmethod
    def _request_text(handler_input) -> str:
        values = []
        for slot in DialogSelection.request_slots(handler_input).values():
            value = AlexaRequest.get_resolved_slot_value(slot)
            if value:
                values.append(value)
        raw = " ".join(values).strip()
        if raw:
            return raw
        if AlexaRequest.get_intent_name(handler_input) == "PlayPublicationIntent":
            return "publication"
        return ""

    async def _select_source(self, handler_input, context: dict, candidate: dict):
        DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
        await self._deps.progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
        return await self._begin_source(
            handler_input,
            candidate,
            dict(context.get("baseSearchPayload") or {}),
        )

    async def _select_format(self, handler_input, context: dict, candidate: dict):
        if candidate.get("id") == "track":
            return await self._begin_tracks(handler_input, context)
        publications = list(context.get("publicationCandidates") or [])
        publication_context = {
            **context,
            "kind": AvailabilityConstants.PUBLICATION_KIND,
            "candidates": publications,
            "offset": 0,
        }
        if len(publications) == 1 and int(context.get("publicationCount") or 0) == 1:
            return await self._play_selected(
                handler_input, publications[0], dict(context.get("source") or {})
            )
        return self._choice_response(handler_input, publication_context)

    async def _select(self, handler_input, context: dict, candidate: dict):
        kind = context.get("kind")
        if kind == AvailabilityConstants.SOURCE_KIND:
            return await self._select_source(handler_input, context, candidate)
        if kind == AvailabilityConstants.FORMAT_KIND:
            return await self._select_format(handler_input, context, candidate)
        return await self._play_selected(
            handler_input, candidate, dict(context.get("source") or {})
        )

    async def _load_remote_page(self, handler_input, context: dict) -> dict:
        next_page = max(0, int(context.get("apiPage") or 0)) + 1
        if context.get("kind") == AvailabilityConstants.TRACK_KIND:
            result = await self._search_source(
                handler_input,
                dict(context.get("source") or {}),
                dict(context.get("baseSearchPayload") or {}),
                next_page,
            )
            incoming = AvailabilityData.track_candidates(result)
            context["totalPages"] = AvailabilityData.search_total_pages(result)
            context["hasMore"] = bool(
                context["totalPages"] and next_page + 1 < context["totalPages"]
            )
        else:
            result = await self._availability(
                handler_input,
                dict(context.get("availabilityFilter") or {}),
                next_page,
            )
            incoming = (
                AvailabilityData.source_candidates(result)
                if context.get("kind") == AvailabilityConstants.SOURCE_KIND
                else AvailabilityData.publication_candidates(result)
            )
            context["totalPages"] = int(result.get("total_pages") or 0)
            context["hasMore"] = bool(result.get("has_more"))
        if result.get("failed"):
            context["pageLoadFailed"] = True
            return context
        existing = list(context.get("candidates") or [])
        seen = {(str(item.get("type")), str(item.get("id"))) for item in existing}
        existing.extend(
            item for item in incoming if (str(item.get("type")), str(item.get("id"))) not in seen
        )
        context.update(
            {
                "candidates": existing,
                "apiPage": next_page,
                "pageLoadFailed": False,
            }
        )
        return context

    async def _more(self, handler_input, context: dict):
        current_offset = max(0, int(context.get("offset") or 0))
        next_offset = current_offset + len(AvailabilityData.displayed(context))
        if next_offset >= len(context.get("candidates") or []) and AvailabilityData.remote_more(
            context
        ):
            await self._deps.progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
            context = await self._load_remote_page(handler_input, context)
        if context.get("pageLoadFailed"):
            context["offset"] = current_offset
            displayed = AvailabilityData.displayed(context)
            kind = str(context.get("kind") or "choice")
            self._activate(handler_input, context)
            return self._response(
                handler_input,
                AvailabilitySpeech.page_unavailable(
                    kind, displayed, has_previous=current_offset > 0
                ),
                "Say one of the names, or ask for more choices to try again.",
                displayed,
            )
        if next_offset >= len(context.get("candidates") or []):
            context["offset"] = current_offset
            displayed = AvailabilityData.displayed(context)
            kind = str(context.get("kind") or "choice")
            speech = f"Those are all the {kind} choices. " + AvailabilitySpeech.choice_retry(
                kind,
                displayed,
                has_more=False,
                has_previous=current_offset > 0,
            )
            self._activate(handler_input, context)
            return self._response(
                handler_input,
                speech,
                "Say one of the names, or say first, second, or third.",
                displayed,
            )
        context["offset"] = next_offset
        return self._choice_response(handler_input, context, "more")

    def _previous(self, handler_input, context: dict):
        current_offset = max(0, int(context.get("offset") or 0))
        context["offset"] = max(0, current_offset - DiscoveryConstants.CHOICE_PAGE_SIZE)
        position = "previous" if current_offset else "initial"
        return self._choice_response(handler_input, context, position)

    async def handle_dialog(self, handler_input):
        active = DialogStateManager.get_active(handler_input) or {}
        context = dict(active.get("context") or {})
        if active.get("type") != AvailabilityConstants.DIALOG_TYPE or not context:
            return None
        intent_name = AlexaRequest.get_intent_name(handler_input) or ""
        if intent_name in DialogConstants.CHOICE_DISMISS_INTENTS:
            DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
            return self._response(
                handler_input,
                Speech.CHOICES_DISMISSED,
                Speech.WELCOME_REPROMPT,
            )
        if intent_name in AvailabilityConstants.MORE_INTENTS:
            return await self._more(handler_input, context)
        if intent_name in AvailabilityConstants.PREVIOUS_INTENTS:
            return self._previous(handler_input, context)
        if intent_name == "AMAZON.NoIntent" and context.get("singleChoice"):
            DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
            return self._response(
                handler_input,
                "No problem. What would you like to listen to instead?",
                Speech.WELCOME_REPROMPT,
            )
        if intent_name == "AMAZON.YesIntent" and context.get("singleChoice"):
            return await self._select(
                handler_input, context, list(context.get("candidates") or [])[0]
            )
        binary_format_choice = bool(
            intent_name in {"AMAZON.YesIntent", "AMAZON.NoIntent"}
            and context.get("kind") == AvailabilityConstants.FORMAT_KIND
        )
        if binary_format_choice:
            publications = list(context.get("publicationCandidates") or [])
            single_publication_yes = bool(
                intent_name == "AMAZON.YesIntent"
                and int(context.get("publicationCount") or 0) == 1
                and publications
            )
            if single_publication_yes:
                return await self._play_selected(
                    handler_input, publications[0], dict(context.get("source") or {})
                )
            if intent_name == "AMAZON.NoIntent" and int(context.get("publicationCount") or 0) == 1:
                return await self._begin_tracks(handler_input, context)
        if intent_name == "AMAZON.NoIntent":
            DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
            return self._response(
                handler_input,
                Speech.CHOICES_DISMISSED,
                Speech.WELCOME_REPROMPT,
            )
        raw = self._request_text(handler_input)
        candidate = DialogSelection.match_pending_candidate(handler_input, context, raw)
        if candidate:
            return await self._select(handler_input, context, candidate)
        displayed = AvailabilityData.displayed(context)
        has_more = AvailabilityData.has_more(context)
        has_previous = max(0, int(context.get("offset") or 0)) > 0
        kind = str(context.get("kind") or "choice")
        speech = AvailabilitySpeech.choice_retry(
            kind, displayed, has_more=has_more, has_previous=has_previous
        )
        self._activate(handler_input, context)
        return self._response(
            handler_input,
            speech,
            AvailabilitySpeech.choice_reprompt(kind, len(displayed), has_more, has_previous),
            displayed,
        )
