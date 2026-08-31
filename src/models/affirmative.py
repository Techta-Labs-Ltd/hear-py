from __future__ import annotations

import json
import logging
import time

from ask_sdk_core.handler_input import HandlerInput

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.search import SearchConstants
from src.models.dialog import DialogStateManager
from src.models.feedback_response import EnjoyedFeedback
from src.models.playback_state import PlaybackQueue
from src.models.search import Search
from src.models.social import FollowCreator
from src.models.suggestion import SuggestionConfirmation
from src.utils.content import ContentUtils
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilters, SearchFilterUtils


class Affirmative:
    logger = logging.getLogger(__name__)
    "State-machine based Yes handler.\n\n    Routes the Yes intent based on the current store/session state:\n    1. awaitingSearchConfirmation  -> execute confirmed search\n    2. listModeActive              -> play current list item\n    4. awaitingStillListening      -> advance queue\n    5. awaitingContinueAfterFlag   -> acknowledge continue\n    6. awaitingFeedback            -> delegate to FeedbackEnjoyed\n    7. awaitingFollow              -> delegate to FollowCreator\n    9. pendingNlpSuggestion        -> confirm NLP suggestion\n    Fallback                       -> generic welcome reprompt\n    "

    def __init__(self, *, deps: object | None = None):
        if deps is None:
            raise RuntimeError("Confirmation requires injected dependencies")
        self._deps = deps

    @staticmethod
    def _ambiguity_response(handler_input):
        return (
            handler_input.response_builder.speak(
                Ssml.ssml("Please say one of the names I offered, or say show more.")
            )
            .reprompt(Ssml.ssml("Say one of the names, or say show more."))
            .set_should_end_session(False)
            .response
        )

    async def _dialog_response(
        self,
        handler_input,
        store: dict,
        session: dict,
        dialog_type: str | None,
    ):
        if dialog_type == "ambiguity":
            return Affirmative._ambiguity_response(handler_input)
        if dialog_type == "latest_source":
            return await self._handle_latest_source_yes(handler_input, store)
        search_pending = bool(
            dialog_type == "search_confirmation"
            or not dialog_type
            and (
                store.get("awaitingSearchConfirmation") or session.get("awaitingSearchConfirmation")
            )
        )
        if search_pending:
            return await self._handle_search_confirmation(handler_input, store, session)
        if store.get("awaitingLocationConfirm") or session.get("awaitingLocationConfirm"):
            return await self._confirm_location(handler_input, store, session)
        if store.get("awaitingCommunityPlayback") or session.get("awaitingCommunityPlayback"):
            return await self._handle_community_play_yes(handler_input, store, session)
        if dialog_type == "resume" or not dialog_type and store.get("awaitingResume"):
            return await self._handle_resume_yes(handler_input, store)
        return None

    async def _state_response(self, handler_input, store: dict):
        if store.get("listModeActive"):
            return await self._handle_list_mode_yes(handler_input, store)
        if store.get("awaitingStillListening"):
            return await self._handle_still_listening_yes(handler_input, store)
        if store.get("awaitingContinueAfterFlag"):
            self._deps.user.update(handler_input, {"awaitingContinueAfterFlag": False})
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.FLAGGED_CONTINUE_YES_ACK))
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )
        if store.get("awaitingFeedback"):
            return await EnjoyedFeedback(deps=self._deps).execute(handler_input)
        if store.get("awaitingFollow"):
            return await FollowCreator(deps=self._deps).execute(handler_input)
        if store.get("pendingNlpSuggestion"):
            return await SuggestionConfirmation(deps=self._deps).confirm(handler_input, store)
        return None

    async def execute(self, handler_input: HandlerInput):
        store = self._deps.user.snapshot(handler_input)
        session = RequestContext.session(handler_input) or {}
        dialog_type = (DialogStateManager.get_active(handler_input) or {}).get("type")
        response = await self._dialog_response(handler_input, store, session, dialog_type)
        response = response or await self._state_response(handler_input, store)
        if response:
            return response
        return (
            handler_input.response_builder.speak(Speech.WELCOME_REPROMPT)
            .reprompt(Speech.WELCOME_REPROMPT)
            .set_should_end_session(False)
            .response
        )

    async def _confirm_location(self, handler_input, store, session_attrs=None):
        pending = (
            store.get("pendingLocationConfirm")
            or (session_attrs or {}).get("pendingLocationConfirm")
            or {}
        )
        city = pending.get("city")
        if not city:
            self._deps.onboarding.clear_invalid_confirmation(handler_input)
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.LOCATION_RETRY))
                .set_should_end_session(False)
                .response
            )
        user_id = AlexaRequest.get_user_id(handler_input)
        final_city = city
        self._deps.onboarding.complete_location(
            handler_input,
            pending,
            offer_community_playback=True,
            preserve_postal_code=True,
        )
        DialogStateManager.clear(handler_input, "onboarding")
        confirmed = self._deps.user.snapshot(handler_input)
        if user_id:
            try:
                await self._deps.heara.sync_listener(
                    {
                        "alexaUserId": user_id,
                        "deviceId": confirmed.get("deviceId"),
                        "locale": getattr(handler_input.request_envelope.request, "locale", None),
                        "userName": confirmed.get("userName"),
                        "userEmail": confirmed.get("userEmail"),
                        "city": final_city,
                        "locality": confirmed.get("locality"),
                        "countryCode": confirmed.get("deviceCountryCode"),
                        "latitude": confirmed.get("latitude"),
                        "longitude": confirmed.get("longitude"),
                        "clientVersion": "alexa-skill",
                    },
                    timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
                )
            except Exception as err:
                self.logger.warning("Hear: listener sync failed error=%s", type(err).__name__)
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(
                    f"{Speech.LOCATION_CONFIRMED(final_city)} {Speech.COMMUNITY_PLAYBACK_OFFER(final_city)}"
                )
            )
            .reprompt(Ssml.ssml(Speech.COMMUNITY_PLAYBACK_OFFER(final_city)))
            .set_should_end_session(False)
            .response
        )

    async def _handle_latest_source_yes(self, handler_input, store):
        source = store.get("pendingLatestSource") or {}
        selected_source = ContentUtils.pick_content_source(source) or {}
        source_kind = source.get("sourceKind") or selected_source.get("kind")
        source_id = source.get("sourceId") or selected_source.get("id")
        source_name = source.get("sourceName") or selected_source.get("name") or "that source"
        self._deps.user.update(handler_input, {"pendingLatestSource": None})
        DialogStateManager.clear(handler_input, "latest_source")
        if not source_id or source_kind not in {"organization", "creator"}:
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.LATEST_SOURCE_DECLINED))
                .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
                .set_should_end_session(False)
                .response
            )
        filters = SearchFilters.source(source_kind, source_id)
        payload = {
            "query": "",
            "filter": filters,
            "sort": "latest",
            "page": 0,
            "limit": 3,
        }
        user_id = AlexaRequest.get_user_id(handler_input)
        if user_id:
            payload["alexaUserId"] = user_id
        result = await self._deps.heara.search(
            payload, timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input)
        )
        previous_id = source.get("contentId")
        result["results"] = [
            item for item in result.get("results", []) if item.get("contentId") != previous_id
        ]
        result["_search_payload"] = payload
        if result["results"]:
            return await Search.auto_play_first_from_search(
                handler_input,
                result,
                {
                    "discoveryIntent": "latest_source",
                    "q": "",
                    "introOverride": f"Here is the latest from {Speech.escape_ssml_lite(source_name)}.",
                },
                deps=self._deps,
            )
        speech = f"There is nothing newer from {Speech.escape_ssml_lite(source_name)} right now. What would you like to listen to?"
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    async def _handle_community_play_yes(self, handler_input, store, session_attrs=None):
        session_attrs = session_attrs or {}
        city = (
            store.get("userCity")
            or store.get("locality")
            or session_attrs.get("userCity")
            or session_attrs.get("locality")
        )
        self._deps.user.update(
            handler_input,
            {
                "awaitingCommunityPlayback": False,
                "awaitingSearchConfirmation": False,
                "pendingResolution": None,
            },
        )
        next_session_attrs = dict(RequestContext.session(handler_input) or {})
        next_session_attrs["awaitingCommunityPlayback"] = False
        RequestContext.replace_session(handler_input, next_session_attrs)
        DialogStateManager.clear(handler_input, "search_confirmation")
        attrs = RequestContext.request(handler_input)
        attrs["_nlp"] = {
            "intent": "local",
            "alexaIntent": "local",
            "confidence": "high",
            "nlpMatchesAlexa": True,
            "needsRedirect": False,
            "slots": {"city": city, "isLocal": True, "residualQuery": ""},
        }
        RequestContext.replace_request(handler_input, attrs)
        result = await Search.discover_content_via_search(
            handler_input, {"q": "", "intent": "local"}, deps=self._deps
        )
        if result.get("results"):
            return await Search.auto_play_first_from_search(
                handler_input,
                result,
                {
                    "discoveryIntent": "local",
                    "q": "",
                    "introOverride": f"Here is the latest from {Speech.escape_ssml_lite(city)}.",
                },
                deps=self._deps,
            )
        if result.get("client_message"):
            speech = Speech.escape_ssml_lite(str(result["client_message"]))
        elif result.get("failed"):
            speech = "I cannot reach the Hear catalogue right now. Please try again shortly."
        else:
            speech = f"I couldn't find anything available from {Speech.escape_ssml_lite(city)} right now."
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    def _expired_resolution_response(self, handler_input):
        self._deps.user.update(
            handler_input,
            {"awaitingSearchConfirmation": False, "pendingResolution": None},
        )
        return (
            handler_input.response_builder.speak(
                Ssml.ssml("That request has expired. Please say what you'd like to hear again.")
            )
            .reprompt(Speech.WELCOME_REPROMPT)
            .set_should_end_session(False)
            .response
        )

    def _clear_confirmed_resolution(self, handler_input, resolution: dict) -> None:
        self._deps.user.update(
            handler_input,
            {
                "awaitingSearchConfirmation": False,
                "pendingResolution": None,
                "awaitingLocationConfirm": False,
                "pendingLocationConfirm": None,
                "lastExecutedResolutionId": resolution.get("requestId"),
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.clear(handler_input, "search_confirmation")
        RequestContext.replace_session(handler_input, {})

    async def _confirmed_search_result(
        self,
        handler_input,
        resolution: dict,
        payload: dict,
        label: str,
    ):
        self.logger.info(
            "Hear: confirmed resolver search START id=%s label=%s payload=%s",
            resolution.get("requestId"),
            label,
            json.dumps(
                {key: value for key, value in payload.items() if key != "alexaUserId"},
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        result = await self._deps.heara.search(
            payload,
            timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
        )
        result["_search_payload"] = payload
        if not result.get("results"):
            return result, None
        response = await Search.auto_play_first_from_search(
            handler_input,
            result,
            {
                "discoveryIntent": resolution.get("intent") or "search",
                "q": payload.get("query") or "",
            },
            deps=self._deps,
        )
        return result, response

    def _relaxed_search_response(
        self,
        handler_input,
        resolution: dict,
        label: str,
    ):
        relaxed = self._source_only_relaxation(resolution)
        if not relaxed:
            return None
        self._deps.user.update(
            handler_input,
            {
                "awaitingSearchConfirmation": True,
                "pendingResolution": relaxed,
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.activate(handler_input, "search_confirmation", context=relaxed)
        source = relaxed["confirmationLabel"].removeprefix("the latest recordings from ")
        failed_label = label.removeprefix("the latest ")
        speech = (
            f"I couldn't find any {Speech.escape_ssml_lite(failed_label)}. "
            f"Would you like to hear the latest recordings from "
            f"{Speech.escape_ssml_lite(source)} instead?"
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(
                Ssml.ssml("Say yes to hear their latest recordings, or no to try something else.")
            )
            .set_should_end_session(False)
            .response
        )

    def _failed_search_response(
        self,
        handler_input,
        resolution: dict,
        result: dict,
        label: str,
    ):
        if result.get("failed"):
            speech = (
                f"I couldn't reach the Hear catalogue to search for "
                f"{Speech.escape_ssml_lite(label)}. Please try again shortly."
            )
            return (
                handler_input.response_builder.speak(Ssml.ssml(speech))
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )
        relaxed = self._relaxed_search_response(handler_input, resolution, label)
        if relaxed:
            return relaxed
        speech = (
            f"I couldn't find anything for {Speech.escape_ssml_lite(label)} right now. "
            "What would you like to try instead?"
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Speech.WELCOME_REPROMPT)
            .set_should_end_session(False)
            .response
        )

    def _missing_resolution_response(self, handler_input):
        self._deps.user.update(
            handler_input,
            {
                "awaitingSearchConfirmation": False,
                "pendingOrganizationConfirmation": False,
                "pendingSearchIntent": None,
                "pendingSearchQuery": None,
                "pendingSearchSlots": {},
                "pendingSuggestions": [],
                "suggestionIndex": 0,
                "excludedSuggestions": [],
            },
        )
        RequestContext.replace_session(handler_input, {})
        return (
            handler_input.response_builder.speak(
                Ssml.ssml(
                    "That earlier request has expired. Please tell me what you'd like to hear again."
                )
            )
            .reprompt(Ssml.ssml(Speech.WELCOME_REPROMPT))
            .set_should_end_session(False)
            .response
        )

    async def _handle_search_confirmation(self, handler_input, store, session_attrs):
        resolution = store.get("pendingResolution") or session_attrs.get("pendingResolution")
        if not isinstance(resolution, dict) or not resolution.get("searchPayload"):
            return self._missing_resolution_response(handler_input)
        if int(resolution.get("expiresAt") or 0) < int(time.time()):
            return self._expired_resolution_response(handler_input)
        payload = SearchFilterUtils.normalize_search_payload(resolution["searchPayload"])
        user_id = AlexaRequest.get_user_id(handler_input)
        if user_id:
            payload["alexaUserId"] = user_id
        label = str(resolution.get("confirmationLabel") or "that request")
        self._clear_confirmed_resolution(handler_input, resolution)
        result, response = await self._confirmed_search_result(
            handler_input, resolution, payload, label
        )
        return response or self._failed_search_response(handler_input, resolution, result, label)

    @staticmethod
    def _source_only_relaxation(resolution: dict) -> dict | None:
        payload = dict(resolution.get("searchPayload") or {})
        filters = dict(payload.get("filter") or {})
        source_keys = tuple(SearchConstants.SEARCH_SOURCE_FILTERS.values())
        if not any((filters.get(key) for key in source_keys)):
            return None
        constrained = bool(
            filters.get("categorySlugs")
            or filters.get("tags")
            or str(payload.get("query") or "").strip()
        )
        if not constrained:
            return None
        payload["filter"] = SearchFilters.without(filters, "categorySlugs", "tags")
        payload["query"] = ""
        payload["sort"] = "latest"
        source_name = next(
            (
                str(entity.get("canonicalValue") or "")
                for entity in resolution.get("resolvedEntities") or []
                if entity.get("type") in {"organization", "creator", "publication"}
                and entity.get("canonicalValue")
            ),
            "that source",
        )
        now = int(time.time())
        return {
            **resolution,
            "requestId": f"{resolution.get('requestId')}:source-only",
            "confirmationLabel": f"the latest recordings from {source_name}",
            "searchPayload": payload,
            "createdAt": now,
            "expiresAt": now + 300,
            "alternatives": [],
        }

    async def _handle_list_mode_yes(self, handler_input, store):
        content_id = PlaybackQueue.content_id(store)
        if not content_id:
            self._deps.user.update(handler_input, {"listModeActive": False})
            return handler_input.response_builder.speak(
                Ssml.ssml(Speech.NO_TRACKS_AVAILABLE)
            ).response
        self._deps.user.update(handler_input, {"listModeActive": False})
        await self._deps.feedback.clear(handler_input)
        payload = {
            "query": "",
            "filter": SearchFilters.content(content_id),
            "page": 0,
            "limit": 1,
        }
        user_id = AlexaRequest.get_user_id(handler_input)
        if user_id:
            payload["alexaUserId"] = user_id
        result = await self._deps.heara.search(
            payload, timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input)
        )
        if not result.get("results"):
            return handler_input.response_builder.speak(
                Ssml.ssml(Speech.NO_CONTENT_AVAILABLE)
            ).response
        return await self._deps.playback.start(handler_input, result["results"][0], "")

    async def _handle_resume_yes(self, handler_input, store):
        state = self._deps.playback.state.current(handler_input)
        self._deps.user.update(handler_input, {"awaitingResume": False})
        DialogStateManager.clear(handler_input, "resume")
        if not state or not state.get("contentId"):
            return handler_input.response_builder.speak(
                Ssml.ssml(Speech.NO_CONTENT_AVAILABLE)
            ).response
        return await self._deps.playback.resume(
            handler_input, state, "Continuing where you stopped."
        )

    async def _handle_still_listening_yes(self, handler_input, store):
        self._deps.user.update(
            handler_input,
            {"awaitingStillListening": False, "awaitingContinueAfterFlag": False},
        )
        self._deps.playback.queue.reset_completed(handler_input)
        queue = PlaybackQueue.read(store)
        next_id = self._deps.playback.queue.move(handler_input, 1)
        if queue and (not next_id):
            loaded = await self._deps.playback.queue.load_next_page(handler_input, self._deps.heara)
            if loaded:
                queue = PlaybackQueue.read(self._deps.user.snapshot(handler_input))
                next_id = self._deps.playback.queue.move(handler_input, 1)
        if not queue or not next_id:
            self._deps.playback.queue.clear(handler_input)
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.QUEUE_FINISHED))
                .reprompt(Speech.WELCOME_REPROMPT)
                .set_should_end_session(False)
                .response
            )
        payload = {
            "query": "",
            "filter": SearchFilters.content(next_id),
            "page": 0,
            "limit": 1,
        }
        user_id = AlexaRequest.get_user_id(handler_input)
        if user_id:
            payload["alexaUserId"] = user_id
        content = PlaybackQueue.cached_content(self._deps.user.snapshot(handler_input), next_id)
        if not content:
            result = await self._deps.heara.search(
                payload,
                timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
            )
            if not result.get("results"):
                self._deps.playback.queue.clear(handler_input)
                return (
                    handler_input.response_builder.speak(Ssml.ssml(Speech.NO_CONTENT_AVAILABLE))
                    .reprompt(Speech.WELCOME_REPROMPT)
                    .set_should_end_session(False)
                    .response
                )
            content = result["results"][0]
        current_queue = PlaybackQueue.read(self._deps.user.snapshot(handler_input)) or {}
        current_index = int(current_queue.get("currentIndex") or 0)
        total = len(queue["orderedContentIds"])
        intro = Speech.QUEUE_NEXT_ANNOUNCE(
            content.get("title"), content.get("creator"), current_index + 1, total
        )
        return await self._deps.playback.start(handler_input, content, intro)
