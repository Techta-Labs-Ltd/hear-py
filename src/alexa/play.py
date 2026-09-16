"""Alexa request adapters for content, creator and organisation playback."""

from __future__ import annotations

from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.dialog import DialogStateManager
from src.alexa.request import AlexaRequest
from src.alexa.search import Search
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.resolver import ResolutionBuilder
from src.models.search_contracts import SearchRequest
from src.models.user import User
from src.services.logging_control import ApplicationLog
from src.utils.filters import SearchFilterUtils
from src.utils.search_payload import SearchPayload


class PlayContent:
    def __init__(
        self,
        user: User,
        heara,
        progressive,
        browse,
        playback,
        play_followed_creators,
        show_more_browse,
    ):
        self._user = user
        self._heara = heara
        self._progressive = progressive
        self._browse = browse
        self._playback = playback
        self._play_followed_creators = play_followed_creators
        self._show_more_browse = show_more_browse

    @staticmethod
    def _error_response(handler_input: HandlerInput):
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.ERROR_GENERIC))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    def _community_setup_response(self, handler_input: HandlerInput):
        self._user.update(handler_input, {"onboardingStage": "confirm_town_for_community"})
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.COMMUNITY_NEEDS_TOWN))
            .reprompt(Ssml.ssml(Speech.REPROMPT_ASK_TOWN))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def _has_location(store: dict) -> bool:
        return bool(
            store.get("locality")
            or store.get("userCity")
            or store.get("latitude")
            or store.get("devicePostalCode")
        )

    @staticmethod
    def _await_publication_source(handler_input) -> None:
        DialogStateManager.activate(
            handler_input,
            "publication_source",
            context={"slotName": "publicationSourceQuery"},
        )

    @staticmethod
    def _publication_source_response(handler_input):
        PlayContent._await_publication_source(handler_input)
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.ASK_PUBLICATION))
            .reprompt(Ssml.ssml(Speech.ASK_PUBLICATION_REPROMPT))
            .add_directive(
                DialogStateManager.capture_directive("publication_source")
            )
            .set_should_end_session(False)
            .response
        )

    async def _search(self, handler_input, query: str | None) -> dict:
        if query:
            return await Search.discover_content_via_search(
                handler_input,
                SearchRequest(query=query),
                heara=self._heara,
                progressive=self._progressive,
                user=self._user,
            )
        return await Search._discover_content_avoiding_recent(
            handler_input,
            SearchRequest(),
            heara=self._heara,
            progressive=self._progressive,
            user=self._user,
        )

    async def _execute(self, handler_input: HandlerInput):
        if not AlexaRequest.get_user_id(handler_input):
            return PlayContent._error_response(handler_input)
        store = self._user.snapshot(handler_input)
        nlp = RequestContext.request(handler_input).get("_nlp") or {}
        if (nlp.get("slots") or {}).get("genericPublicationRequest"):
            return PlayContent._publication_source_response(handler_input)
        raw = Search._raw_search_phrase(handler_input)
        query = Search._extract_slot_value(handler_input, "query") or raw
        if AlexaRequest.wants_play_from_followed_creators(handler_input, query or raw or ""):
            return await self._play_followed_creators(handler_input)
        pagination = bool(
            Search._is_misrouted_browse_pagination(query or "")
            or Search._is_misrouted_browse_pagination(raw or "")
        )
        if pagination and Search._has_active_browse_catalog(store):
            return await self._show_more_browse(handler_input)
        community = AlexaRequest.wants_local_community_content(handler_input, query or "")
        if community and not PlayContent._has_location(store):
            return self._community_setup_response(handler_input)
        result = await self._search(handler_input, query)
        ApplicationLog.info(
            "Hear: PlayContent search done hitCount=%s",
            len(result.get("results", [])),
        )
        if not result.get("results"):
            return Search._build_search_outcome_response(handler_input, result)
        if query and SearchFilterUtils.wants_latest_playback(raw or ""):
            return await Search._play_first_search_result(
                handler_input,
                result,
                label=query,
                user=self._user,
                browse=self._browse,
                playback=self._playback,
            )
        relaxed = bool(query and result.get("search_relaxation"))
        intro = (
            Speech.PLAY_COMMUNITY_INTRO(store.get("locality"), result.get("total_hits", 0))
            if community and not relaxed
            else None
        )
        response = await Search.auto_play_first_from_search(
            handler_input,
            result,
            {
                "discoveryIntent": AlexaRequest.get_intent_name(handler_input)
                or "PlayContentIntent",
                "q": query,
                "locality": store.get("locality"),
                "introOverride": intro,
            },
            user=self._user,
            browse=self._browse,
            playback=self._playback,
        )
        return response or Search._build_no_content_response(handler_input)

    async def execute(self, handler_input: HandlerInput):
        try:
            return await self._execute(handler_input)
        except Exception:
            ApplicationLog.exception("Hear: PlayContent failed")
            return PlayContent._error_response(handler_input)


class PlayCreator:
    def __init__(
        self,
        user: User,
        heara,
        progressive,
        browse,
        playback,
        ask_creator_city,
    ):
        self._user = user
        self._heara = heara
        self._progressive = progressive
        self._browse = browse
        self._playback = playback
        self._ask_creator_city = ask_creator_city

    async def execute(self, handler_input: HandlerInput):
        if not AlexaRequest.get_user_id(handler_input):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.ERROR_GENERIC))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        attrs = RequestContext.request(handler_input)
        nlp = attrs.get("_nlp", {}) if attrs else {}
        nlp_slots = nlp.get("slots", {}) if nlp else {}
        generic_creator_request = bool(nlp_slots.get("genericCreatorRequest"))
        resolved_creator = bool(nlp_slots.get("creatorIds"))
        if generic_creator_request or not resolved_creator:
            return self._ask_creator_city(handler_input)
        creator_query = str(nlp_slots.get("residualQuery") or "")
        creator_label = nlp_slots.get("creatorName")
        search_result = await Search.discover_content_via_search(
            handler_input,
            SearchRequest(query=creator_query, intent="creator"),
            heara=self._heara,
            progressive=self._progressive,
            user=self._user,
        )
        if not search_result.get("results"):
            if search_result.get("client_message"):
                return Search._build_search_outcome_response(handler_input, search_result)
            fallback = await Search._discover_content_avoiding_recent(
                handler_input,
                SearchRequest(),
                heara=self._heara,
                progressive=self._progressive,
                user=self._user,
            )
            if fallback.get("results"):
                response = await Search.auto_play_first_from_search(
                    handler_input,
                    fallback,
                    {
                        "discoveryIntent": "PlayContentIntent",
                        "q": "",
                        "locality": self._user.snapshot(handler_input).get("locality"),
                        "introOverride": f"{SearchSpeech.search_no_match(creator_label)} Here are some other picks for you.",
                    },
                    user=self._user,
                    browse=self._browse,
                    playback=self._playback,
                )
                return response or Search._build_no_content_response(handler_input)
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(SearchSpeech.search_no_match(creator_label))
                )
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        response = await Search.auto_play_first_from_search(
            handler_input,
            search_result,
            {
                "discoveryIntent": "creator",
                "q": creator_query,
                "locality": self._user.snapshot(handler_input).get("locality"),
                "introOverride": None,
            },
            user=self._user,
            browse=self._browse,
            playback=self._playback,
        )
        return response or Search._build_no_content_response(handler_input)


class PlayOrganization:
    def __init__(self, user: User, heara, progressive, show_more_browse):
        self._user = user
        self._heara = heara
        self._progressive = progressive
        self._show_more_browse = show_more_browse

    @staticmethod
    def _await_name(handler_input) -> None:
        DialogStateManager.activate(
            handler_input,
            "organization_name",
            context={"slotName": "organizationQuery"},
        )

    @staticmethod
    def _name_retry_response(handler_input):
        DialogStateManager.clear(handler_input, "organization_name")
        prompt = (
            "I couldn't recognize that talking newspaper. "
            "Say its full name. For example, Tynedale Talking Newspaper."
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(prompt))
            .reprompt(Ssml.ssml(prompt))
            .set_should_end_session(False)
            .response
        )

    async def execute(self, handler_input: HandlerInput):
        if not AlexaRequest.get_user_id(handler_input):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.ERROR_GENERIC))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        active_store = self._user.snapshot(handler_input)
        attrs = RequestContext.request(handler_input)
        nlp = attrs.get("_nlp", {}) if attrs else {}
        nlp_slots = nlp.get("slots", {}) if nlp else {}
        org_query = (
            nlp_slots.get("organizationQuery")
            or Search._extract_slot_value(handler_input, "organizationQuery")
            or Search._extract_slot_value(handler_input, "query")
            or Search._raw_search_phrase(handler_input)
        )
        resolved_org = bool(nlp_slots.get("organizationIds"))
        org_label = nlp_slots.get("organizationName") or org_query
        if (
            org_query
            and Search._is_misrouted_browse_pagination(org_query)
            and Search._has_active_browse_catalog(active_store)
        ):
            return await self._show_more_browse(handler_input)
        if nlp_slots.get("ambiguousReferences"):
            result = await Search.discover_content_via_search(
                handler_input,
                SearchRequest(intent="organization"),
                heara=self._heara,
                progressive=self._progressive,
                user=self._user,
            )
            message = result.get("client_message") or SearchSpeech.talking_newspaper_not_recognized(
                org_query
            )
            return (
                handler_input.response_builder.speak(Ssml.ssml(message))
                .reprompt(Ssml.ssml("Please say the full talking newspaper name."))
                .set_should_end_session(False)
                .response
            )
        generic_request = bool(nlp_slots.get("genericOrganizationRequest")) or bool(
            nlp_slots.get("unresolvedGenericOrganization")
        )
        if nlp_slots.get("talkingNewspaperRepairCandidate"):
            DialogStateManager.activate(
                handler_input,
                "asr_repair",
                context={
                    "repair": "talking_newspaper",
                    "question": Speech.TALKING_NEWSPAPER_ASR_REPAIR,
                },
            )
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(Speech.TALKING_NEWSPAPER_ASR_REPAIR)
                )
                .reprompt(Ssml.ssml(Speech.TALKING_NEWSPAPER_ASR_REPAIR_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if generic_request or (not org_query and (not resolved_org)):
            if AlexaRequest.get_intent_name(handler_input) == "SelectOrganizationIntent":
                return PlayOrganization._name_retry_response(handler_input)
            PlayOrganization._await_name(handler_input)
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.ASK_TALKING_NEWSPAPER))
                .reprompt(Ssml.ssml(Speech.ASK_TALKING_NEWSPAPER_REPROMPT))
                .add_directive(
                    DialogStateManager.capture_directive("organization_name")
                )
                .set_should_end_session(False)
                .response
            )
        unresolved = nlp_slots.get("unresolvedReferences") or []
        if unresolved:
            reference = unresolved[0]
            message = SearchSpeech.unresolved_reference_message(
                str(reference.get("phrase") or org_query or ""),
                list(reference.get("expectedTypes") or []),
            )
            self._user.update(handler_input, {"awaitingOrganizationName": False})
            return (
                handler_input.response_builder.speak(Ssml.ssml(message))
                .reprompt(
                    Ssml.ssml("Please say the creator, organisation, or publication's full name.")
                )
                .set_should_end_session(False)
                .response
            )
        if not resolved_org:
            PlayOrganization._await_name(handler_input)
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(SearchSpeech.talking_newspaper_not_recognized(org_query))
                )
                .reprompt(Ssml.ssml(Speech.ASK_TALKING_NEWSPAPER_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if resolved_org:
            label = SearchPayload.resolved_request_label(nlp_slots, org_label)
            self._user.update(
                handler_input,
                {
                    "awaitingOrganizationName": False,
                    "awaitingSearchConfirmation": True,
                    "pendingResolution": ResolutionBuilder.build(nlp, label),
                    "_requiresReliableSave": True,
                },
            )
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(SearchSpeech.confirm_resolved_search(label))
                )
                .reprompt(Ssml.ssml("Say yes to play it, or no to try another name."))
                .set_should_end_session(False)
                .response
            )
