from __future__ import annotations

from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.dialog import DialogStateManager
from src.models.resolver import ResolutionBuilder
from src.models.search import Search
from src.models.user import User
from src.utils.filters import SearchFilterUtils


class PlayContent:
    def __init__(self, *, deps: object | None = None):
        self._deps = Search._dependencies(deps)

    @staticmethod
    def _error_response(handler_input: HandlerInput):
        return (
            handler_input.response_builder.speak(Ssml.ssml(Speech.ERROR_GENERIC))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def _community_setup_response(handler_input: HandlerInput):
        User.update(handler_input, {"onboardingStage": "confirm_town_for_community"})
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

    async def _search(self, handler_input, query: str | None) -> dict:
        if query:
            return await Search.discover_content_via_search(
                handler_input, {"q": query}, deps=self._deps
            )
        return await Search._discover_content_avoiding_recent(
            handler_input, {"q": ""}, deps=self._deps
        )

    async def _execute(self, handler_input: HandlerInput):
        if not AlexaRequest.get_user_id(handler_input):
            return PlayContent._error_response(handler_input)
        store = User.snapshot(handler_input)
        raw = Search._raw_search_phrase(handler_input)
        query = Search._extract_slot_value(handler_input, "query") or raw
        if AlexaRequest.wants_play_from_followed_creators(handler_input, query or raw or ""):
            return await Search.play_from_followed_creators(handler_input, deps=self._deps)
        pagination = bool(
            Search._is_misrouted_browse_pagination(query or "")
            or Search._is_misrouted_browse_pagination(raw or "")
        )
        if pagination and Search._has_active_browse_catalog(store):
            return await Search._show_more_browse(handler_input, self._deps)
        community = AlexaRequest.wants_local_community_content(handler_input, query)
        if community and not PlayContent._has_location(store):
            return PlayContent._community_setup_response(handler_input)
        result = await self._search(handler_input, query)
        Search.logger.info(
            "Hear: PlayContent search done q=%s hitCount=%s",
            query,
            len(result.get("results", [])),
        )
        if not result.get("results"):
            return Search._build_search_outcome_response(handler_input, result)
        if query and SearchFilterUtils.wants_latest_playback(raw or ""):
            return await Search._play_first_search_result(
                handler_input, result, label=query, deps=self._deps
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
            deps=self._deps,
        )
        return response or Search._build_no_content_response(handler_input)

    async def execute(self, handler_input: HandlerInput):
        try:
            return await self._execute(handler_input)
        except Exception:
            Search.logger.exception("Hear: PlayContent failed")
            return PlayContent._error_response(handler_input)


class PlayCreator:
    def __init__(self, *, deps: object | None = None):
        self._deps = Search._dependencies(deps)

    async def execute(self, handler_input: HandlerInput):
        if not AlexaRequest.get_user_id(handler_input):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.ERROR_GENERIC))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        active_store = User.snapshot(handler_input)
        attrs = RequestContext.request(handler_input)
        nlp = attrs.get("_nlp", {}) if attrs else {}
        nlp_slots = nlp.get("slots", {}) if nlp else {}
        generic_creator_request = bool(nlp_slots.get("genericCreatorRequest"))
        creator_query = (
            nlp_slots.get("creatorQuery")
            or Search._extract_slot_value(handler_input, "creatorQuery")
            or Search._extract_slot_value(handler_input, "query")
            or Search._raw_search_phrase(handler_input)
        )
        resolved_creator = bool(nlp_slots.get("creatorIds"))
        creator_label = nlp_slots.get("creatorName") or creator_query
        raw_phrase = Search._raw_search_phrase(handler_input)
        if (
            creator_query
            and Search._is_misrouted_browse_pagination(creator_query)
            and Search._has_active_browse_catalog(active_store)
        ):
            return await Search._show_more_browse(handler_input, self._deps)
        if nlp_slots.get("ambiguousReferences"):
            result = await Search.discover_content_via_search(
                handler_input, {"q": "", "intent": "creator"}, deps=self._deps
            )
            message = result.get("client_message") or SearchSpeech.unresolved_reference_message(
                creator_query or "that name", ["creator"]
            )
            return (
                handler_input.response_builder.speak(Ssml.ssml(message))
                .reprompt(Ssml.ssml("Please say one of the creator names I just offered."))
                .set_should_end_session(False)
                .response
            )
        if generic_creator_request or (not creator_query and (not resolved_creator)):
            User.update(handler_input, {"awaitingCreatorName": True})
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml("Which creator would you like to hear?")
                )
                .reprompt(Ssml.ssml("Just say their name."))
                .add_directive({"type": "Dialog.ElicitSlot", "slotToElicit": "creatorQuery"})
                .set_should_end_session(False)
                .response
            )
        User.update(handler_input, {"awaitingCreatorName": False})
        search_result = await Search.discover_content_via_search(
            handler_input,
            {
                "q": nlp_slots.get("residualQuery", "") if resolved_creator else creator_query,
                "intent": "creator",
            },
            deps=self._deps,
        )
        if not search_result.get("results"):
            fallback = await Search._discover_content_avoiding_recent(
                handler_input, {"q": ""}, deps=self._deps
            )
            if fallback.get("results"):
                response = await Search.auto_play_first_from_search(
                    handler_input,
                    fallback,
                    {
                        "discoveryIntent": "PlayContentIntent",
                        "q": "",
                        "locality": User.snapshot(handler_input).get("locality"),
                        "introOverride": f"{SearchSpeech.search_no_match(creator_label)} Here are some other picks for you.",
                    },
                    deps=self._deps,
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
        try:
            if SearchFilterUtils.wants_latest_playback(raw_phrase or ""):
                return await Search._play_first_search_result(
                    handler_input, search_result, label=creator_label, deps=self._deps
                )
        except Exception:
            pass
        was_relaxed = bool(search_result.get("search_relaxation"))
        response = await Search.auto_play_first_from_search(
            handler_input,
            search_result,
            {
                "discoveryIntent": "PlayByCreatorIntent",
                "q": creator_query,
                "locality": User.snapshot(handler_input).get("locality"),
                "introOverride": None
                if was_relaxed
                else f"Here is what I found for {Speech.escape_ssml_lite(creator_label)}.",
            },
            deps=self._deps,
        )
        return response or Search._build_no_content_response(handler_input)


class PlayOrganization:
    def __init__(self, *, deps: object | None = None):
        self._deps = Search._dependencies(deps)

    async def execute(self, handler_input: HandlerInput):
        if not AlexaRequest.get_user_id(handler_input):
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.ERROR_GENERIC))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        active_store = User.snapshot(handler_input)
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
            return await Search._show_more_browse(handler_input, self._deps)
        if nlp_slots.get("ambiguousReferences"):
            result = await Search.discover_content_via_search(
                handler_input, {"q": "", "intent": "organization"}, deps=self._deps
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
            User.update(handler_input, {"awaitingOrganizationName": True})
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.ASK_TALKING_NEWSPAPER))
                .reprompt(Ssml.ssml(Speech.ASK_TALKING_NEWSPAPER_REPROMPT))
                .add_directive({"type": "Dialog.ElicitSlot", "slotToElicit": "organizationQuery"})
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
            User.update(handler_input, {"awaitingOrganizationName": False})
            return (
                handler_input.response_builder.speak(Ssml.ssml(message))
                .reprompt(
                    Ssml.ssml("Please say the creator, organisation, or publication's full name.")
                )
                .set_should_end_session(False)
                .response
            )
        if not resolved_org:
            User.update(handler_input, {"awaitingOrganizationName": True})
            return (
                handler_input.response_builder.speak(
                    Ssml.ssml(SearchSpeech.talking_newspaper_not_recognized(org_query))
                )
                .reprompt(Ssml.ssml(Speech.ASK_TALKING_NEWSPAPER_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        if resolved_org:
            label = SearchSpeech.resolved_search_request_label(nlp_slots, org_label)
            User.update(
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
