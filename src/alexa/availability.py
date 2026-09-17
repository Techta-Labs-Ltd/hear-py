
from __future__ import annotations

from src.alexa.availability_dialog import AvailabilityDialog
from src.alexa.availability_speech import AvailabilitySpeech
from src.alexa.context import RequestContext
from src.alexa.dialog import DialogStateManager
from src.alexa.entities import AlexaEntities
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.search import Search
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.availability import AvailabilityConstants
from src.constants.discovery import DiscoveryConstants
from src.models.availability_data import AvailabilityData, AvailabilityOutcome
from src.models.availability_request import AvailabilityRequest
from src.models.search_contracts import SearchRequest
from src.models.user import User
from src.services.logging_control import ApplicationLog
from src.utils.content import ContentUtils
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilters
from src.utils.search_payload import SearchPayload


class Availability:
    __slots__ = ("_heara", "_progressive", "_user", "_browse", "_playback", "_dialog")

    def __init__(self, heara, progressive, user: User, browse, playback) -> None:
        self._heara = heara
        self._progressive = progressive
        self._user = user
        self._browse = browse
        self._playback = playback
        self._dialog = AvailabilityDialog(self, progressive)

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

    async def _availability(
        self,
        handler_input,
        availability_filter: dict,
        page: int,
        discovery: dict | None = None,
        *,
        resolution_id: str | None = None,
        is_local: bool = False,
    ) -> dict:
        store = self._user.snapshot(handler_input)
        payload = {
            "filter": availability_filter,
            "alexaUserId": AlexaRequest.get_user_id(handler_input),
            "page": max(0, int(page or 0)),
            "limit": DiscoveryConstants.CHOICE_PAGE_SIZE,
        }
        if store.get("listenerId"):
            payload["listenerId"] = store["listenerId"]
        if resolution_id:
            payload["resolutionId"] = resolution_id
        payload.update(discovery or {})
        if is_local:
            payload["isLocal"] = True
        ApplicationLog.info(
            "Hear: availability request filter=%s page=%s limit=%s resolutionIdPresent=%s",
            availability_filter,
            payload["page"],
            payload["limit"],
            bool(resolution_id),
        )
        return await self._heara.availability(
            payload,
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )

    @staticmethod
    def ask_creator_city(handler_input, *, rejected: bool = False):
        DialogStateManager.activate(
            handler_input,
            "creator_location",
            context={"slotName": "cityQuery"},
        )
        speech = (
            Speech.CREATOR_CITY_NOT_RECOGNISED if rejected else Speech.ASK_CREATOR_CITY
        )
        reprompt = (
            Speech.CREATOR_CITY_NOT_RECOGNISED
            if rejected
            else Speech.ASK_CREATOR_CITY_REPROMPT
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(reprompt))
            .add_directive(DialogStateManager.capture_directive("creator_location"))
            .set_should_end_session(False)
            .response
        )

    async def begin_creator_location(self, handler_input, nlp: dict | None = None):
        resolved = dict(nlp or RequestContext.request(handler_input).get("_nlp") or {})
        if resolved.get("locationRejected"):
            return self.ask_creator_city(handler_input, rejected=True)
        payload = AvailabilityRequest.local(
            resolved,
            alexa_user_id=AlexaRequest.get_user_id(handler_input),
            user_state=self._user.snapshot(handler_input),
        ).to_search_payload()
        availability_filter = AvailabilityData.availability_filter(
            payload,
            self._user.snapshot(handler_input),
        )
        requested_city = AvailabilityData.requested_city(resolved, payload)
        if not requested_city or not availability_filter or "location" not in availability_filter:
            return self.ask_creator_city(handler_input)
        availability_filter["isCreator"] = True
        await self._progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
        result = await self._availability(
            handler_input,
            availability_filter,
            0,
            resolution_id=payload.get("resolutionId"),
        )
        candidates = AvailabilityData.source_candidates(result, "creator")[
            : DiscoveryConstants.CHOICE_PAGE_SIZE
        ]
        if result.get("failed"):
            return self._creator_terminal_response(
                handler_input,
                requested_city,
                failed=True,
            )
        if not candidates:
            return self._creator_terminal_response(handler_input, requested_city)
        context = {
            "kind": AvailabilityConstants.SOURCE_KIND,
            "candidates": candidates,
            "offset": 0,
            "apiPage": int(result.get("page") or 0),
            "totalPages": int(result.get("total_pages") or 0),
            "hasMore": bool(result.get("has_more")),
            "availabilityFilter": availability_filter,
            "baseSearchPayload": payload,
            "requestedCity": requested_city,
            "sourceType": "creator",
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

    @staticmethod
    def _creator_terminal_response(handler_input, city: str, *, failed: bool = False):
        DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
        speech = (
            AvailabilitySpeech.creator_unavailable(city)
            if failed
            else AvailabilitySpeech.creator_no_results(city)
        )
        return AlexaResponse.present_idle_next(handler_input, speech, Speech.WELCOME_REPROMPT)

    async def begin_recommendations(
        self,
        handler_input,
        *,
        nlp: dict | None = None,
    ):
        await self._progressive.send(handler_input, Speech.RECOMMENDATION_PROGRESSIVE)
        discovery = {"isRecommended": True}
        resolved = nlp if isinstance(nlp, dict) else {}
        payload_candidate = resolved.get("searchPayload")
        search_payload: dict = (
            payload_candidate if isinstance(payload_candidate, dict) else {}
        )
        filter_candidate = search_payload.get("filter")
        search_filter: dict = filter_candidate if isinstance(filter_candidate, dict) else {}
        # Availability discovers sources; content taxonomy remains in the
        # base search payload and is applied only after a source is selected.
        availability_filter: dict = {}
        result = await self._availability(
            handler_input,
            availability_filter,
            0,
            discovery,
            resolution_id=search_payload.get("resolutionId"),
        )
        candidates = AvailabilityData.source_candidates(result)
        if result.get("failed"):
            return self._terminal_response(handler_input, failed=True)
        if not candidates:
            return self._terminal_response(handler_input)
        context = {
            "kind": AvailabilityConstants.SOURCE_KIND,
            "candidates": candidates,
            "offset": 0,
            "apiPage": int(result.get("page") or 0),
            "totalPages": int(result.get("total_pages") or 0),
            "hasMore": bool(result.get("has_more")),
            "availabilityFilter": availability_filter,
            "availabilityDiscovery": discovery,
            "baseSearchPayload": {"query": "", "filter": search_filter},
            "discoveryMode": "recommended",
        }
        return self._choice_response(handler_input, context)

    def _terminal_response(
        self,
        handler_input,
        *,
        failed: bool = False,
        city: str | None = None,
        source_name: str | None = None,
    ):
        DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
        speech = (
            AvailabilitySpeech.unavailable(city=city, source_name=source_name)
            if failed
            else AvailabilitySpeech.no_results(city=city, source_name=source_name)
        )
        return AlexaResponse.present_idle_next(handler_input, speech, Speech.WELCOME_REPROMPT)

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
        has_previous = max(0, int(context.get("offset") or 0)) > 0 or bool(
            context.get("sourceType") == "creator"
            and int(context.get("apiPage") or 0) > 0
        )
        kind = str(context.get("kind") or "")
        if kind == AvailabilityConstants.SOURCE_KIND:
            speech = AvailabilitySpeech.source_choices(
                displayed,
                position=position,
                has_more=has_more,
                has_previous=has_previous,
                requested_city=context.get("requestedCity"),
                discovery_mode=context.get("discoveryMode"),
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
        payload = AvailabilityRequest.local(
            resolved,
            alexa_user_id=AlexaRequest.get_user_id(handler_input),
            user_state=self._user.snapshot(handler_input),
        ).to_search_payload()
        if AvailabilityData.request_scope(payload) != AvailabilityConstants.LOCATION_KIND:
            return await self._search_mixed_local_request(handler_input)
        availability_filter = AvailabilityData.availability_filter(
            payload,
            self._user.snapshot(handler_input),
        )
        requested_city = AvailabilityData.requested_city(resolved, payload)
        if not availability_filter or "location" not in availability_filter:
            self._user.update(handler_input, {"onboardingStage": "confirm_town_for_community"})
            return self._response(
                handler_input,
                Speech.COMMUNITY_NEEDS_TOWN,
                Speech.REPROMPT_ASK_TOWN,
            )
        await self._progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
        result = await self._availability(
            handler_input,
            availability_filter,
            0,
            resolution_id=payload.get("resolutionId"),
            is_local=True,
        )
        outcome = AvailabilityOutcome.classify(
            result, AvailabilityData.source_candidates(result)
        )
        candidates = list(outcome.candidates)
        if outcome.kind == "unavailable":
            return self._terminal_response(
                handler_input,
                failed=True,
                city=requested_city,
            )
        if not candidates:
            return self._terminal_response(handler_input, city=requested_city)
        context = {
            "kind": AvailabilityConstants.SOURCE_KIND,
            "candidates": candidates,
            "offset": 0,
            "apiPage": int(result.get("page") or 0),
            "totalPages": int(result.get("total_pages") or 0),
            "hasMore": bool(result.get("has_more")),
            "availabilityFilter": availability_filter,
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
            availability_filter = AvailabilityData.availability_filter(
                payload,
                self._user.snapshot(handler_input),
            )
            if not availability_filter:
                return None
            await self._progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
            return await self._begin_source(
                handler_input, source, payload, availability_filter,
                continue_with_search_on_failure=True,
            )
        publication_source = self._publication_source(resolution, payload)
        if publication_source:
            await self._progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
            return await self._begin_source(
                handler_input,
                publication_source,
                payload,
                self._source_availability_filter(publication_source),
                continue_with_search_on_failure=True,
                prefer_publications=True,
            )
        if scope == AvailabilityConstants.LOCATION_KIND and (
            resolution.get("intent") == "local" or AvailabilityData.has_location_payload(payload)
        ):
            slots_candidate = resolution.get("slots")
            resolution_slots: dict = (
                slots_candidate if isinstance(slots_candidate, dict) else {}
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
    def _publication_source(resolution: dict, payload: dict) -> dict | None:
        """Return the resolved organisation for an unconstrained publication request."""
        if resolution.get("intent") != "publication" or str(payload.get("query") or "").strip():
            return None
        filters = payload.get("filter")
        if not isinstance(filters, dict):
            return None
        organization_ids = filters.get("organizationIds")
        if not isinstance(organization_ids, list) or len(organization_ids) != 1:
            return None
        if filters.get("publicationIds") or not filters.get("isPublication"):
            return None
        allowed_filter_keys = {"organizationIds", "isPublication"}
        if any(key not in allowed_filter_keys for key in filters):
            return None
        source_resolution = {
            **resolution,
            "searchPayload": {
                "query": "",
                "filter": {"organizationIds": organization_ids},
            },
        }
        source = AvailabilityData.source_from_resolution(source_resolution)
        return source if source and source.get("type") == "organization" else None

    @staticmethod
    def _source_availability_filter(source: dict) -> dict:
        key = "organizationId" if source.get("type") == "organization" else "creatorId"
        return {key: source.get("id")}

    async def _begin_source(
        self, handler_input, source: dict, base_payload: dict,
        availability_filter: dict | None = None, *,
        continue_with_search_on_failure: bool = False,
        prefer_publications: bool = False,
    ):
        requested_filter = availability_filter or self._source_availability_filter(source)
        result = await self._availability(
            handler_input,
            requested_filter,
            0,
            resolution_id=base_payload.get("resolutionId"),
        )
        if result.get("failed"):
            if continue_with_search_on_failure:
                ApplicationLog.warning("Hear: source availability failed; using catalogue search")
                return None
            return self._terminal_response(
                handler_input,
                failed=True,
                source_name=source.get("name"),
            )
        publication_count = int(result.get("publication_count") or 0)
        track_count = int(result.get("standalone_track_count") or 0)
        publications = AvailabilityData.publication_candidates(result)
        if prefer_publications:
            if publication_count <= 0:
                return self._terminal_response(handler_input, source_name=source.get("name"))
            if publication_count == 1 and publications:
                return await self._play_selected(
                    handler_input,
                    publications[0],
                    source,
                    base_payload,
                )
            if publications:
                publication_context = {
                    "kind": AvailabilityConstants.PUBLICATION_KIND,
                    "source": source,
                    "candidates": publications,
                    "offset": 0,
                    "apiPage": int(result.get("page") or 0),
                    "totalPages": int(result.get("total_pages") or 0),
                    "hasMore": bool(result.get("has_more")),
                    "availabilityFilter": requested_filter,
                    "baseSearchPayload": base_payload,
                    "publicationCount": publication_count,
                    "trackCount": track_count,
                }
                return self._choice_response(handler_input, publication_context)
            return self._terminal_response(handler_input, source_name=source.get("name"))
        if publication_count <= 0:
            if track_count > 0:
                return await self._play_source_directly(handler_input, source, base_payload)
            return await self._play_source_directly(
                handler_input,
                source,
                base_payload,
                standalone_tracks=False,
            )
        publication_context = {
            "kind": AvailabilityConstants.PUBLICATION_KIND,
            "source": source,
            "candidates": publications,
            "offset": 0,
            "apiPage": int(result.get("page") or 0),
            "totalPages": int(result.get("total_pages") or 0),
            "hasMore": bool(result.get("has_more")),
            "availabilityFilter": requested_filter,
            "baseSearchPayload": base_payload,
            "publicationCount": publication_count,
            "trackCount": track_count,
        }
        if track_count <= 0:
            if not publications:
                return self._terminal_response(
                    handler_input,
                    source_name=source.get("name"),
                )
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

    def _source_search_payload(
        self,
        handler_input,
        source: dict,
        base_payload: dict,
        page: int = 0,
        *,
        standalone_tracks: bool = True,
    ):
        store = self._user.snapshot(handler_input)
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
        # /search treats these filters as opt-in constraints.  Omit the
        # default false value instead of serialising it as a filter.
        filters.pop("isPublication", None)
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

    async def _search_source(
        self,
        handler_input,
        source: dict,
        base_payload: dict,
        page: int = 0,
        *,
        standalone_tracks: bool = True,
    ):
        payload = self._source_search_payload(
            handler_input,
            source,
            base_payload,
            page,
            standalone_tracks=standalone_tracks,
        )
        ApplicationLog.info(
            "Hear: availability catalogue search filter=%s page=%s limit=%s",
            payload.get("filter"),
            payload.get("page"),
            payload.get("limit"),
        )
        result = await self._heara.search(
            payload,
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )
        result.setdefault("_search_payload", payload)
        result.setdefault("_request_label", source.get("name"))
        return result

    async def _play_source_directly(
        self,
        handler_input,
        source: dict,
        base_payload: dict,
        *,
        standalone_tracks: bool = True,
    ):
        result = await self._search_source(
            handler_input,
            source,
            base_payload,
            standalone_tracks=standalone_tracks,
        )
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
            user=self._user,
            browse=self._browse,
            playback=self._playback,
        )

    async def _search_mixed_local_request(self, handler_input):
        result = await Search.discover_content_via_search(
            handler_input,
            SearchRequest(intent="local"),
            heara=self._heara,
            progressive=self._progressive,
            user=self._user,
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
            user=self._user,
            browse=self._browse,
            playback=self._playback,
        )

    async def _begin_tracks(self, handler_input, context: dict):
        source = dict(context.get("source") or {})
        base_payload = dict(context.get("baseSearchPayload") or {})
        await self._progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
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
            user=self._user,
            browse=self._browse,
            playback=self._playback,
        )

    async def _play_selected(
        self,
        handler_input,
        candidate: dict,
        source: dict,
        base_payload: dict | None = None,
    ):
        store = self._user.snapshot(handler_input)
        if candidate.get("type") == "publication":
            payload = SearchPayload.for_publication(
                base_payload or {},
                [candidate.get("id")],
                DiscoveryConstants.CHOICE_PAGE_SIZE,
            )
        else:
            payload = {
                "query": "",
                "filter": SearchFilters.content(candidate.get("id")),
                "page": 0,
                "limit": 1,
            }
        payload = SearchPayload.with_identity(
            payload, alexa_user_id=AlexaRequest.get_user_id(handler_input), listener_id=store.get("listenerId")
        )
        ApplicationLog.info(
            "Hear: availability catalogue search filter=%s page=%s limit=%s",
            payload.get("filter"),
            payload.get("page"),
            payload.get("limit"),
        )
        await self._progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
        result = await self._heara.search(
            payload,
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )
        result.setdefault("_search_payload", payload)
        result.setdefault("_request_label", candidate.get("name"))
        if not result.get("results"):
            return Search._build_search_outcome_response(handler_input, result)
        DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
        source_name = source.get("name") if candidate.get("type") != "publication" else None
        return await Search.auto_play_first_from_search(
            handler_input,
            result,
            {
                "discoveryIntent": candidate.get("type") or "search",
                "q": "",
                "introOverride": AvailabilitySpeech.playing_choice(
                    candidate.get("name")
                    or ContentUtils.content_title_for_speech(result["results"][0]),
                    source_name,
                ),
            },
            user=self._user,
            browse=self._browse,
            playback=self._playback,
        )

    async def handle_dialog(self, handler_input):
        return await self._dialog.handle(handler_input)
