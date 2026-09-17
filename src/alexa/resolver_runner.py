from __future__ import annotations

import time

from src.alexa.context import RequestContext
from src.alexa.dialog import DialogSelection, DialogStateManager
from src.alexa.dialog_request import intent_slots
from src.alexa.direct_intents import DirectIntentPolicy
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.clients.progressive import ProgressiveResponseClient
from src.constants.availability import AvailabilityConstants
from src.constants.dialog import DialogConstants
from src.constants.discovery import DiscoveryConstants
from src.constants.onboarding import OnboardingConstants
from src.constants.resolver import ResolverConstants
from src.models.resolver import ResolverUnavailable, UtteranceResolver
from src.models.resolver_inputs import ResolverSlot
from src.models.resolver_workflow import ResolverWorkflow
from src.models.user import User
from src.services.logging_control import ApplicationLog
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilterUtils


class ResolverWorkflowRunner:
    # These requests have dedicated handlers and must never be interpreted as
    # discovery/search utterances, even if an interaction model slot is present.
    DIRECT_HANDLER_INTENTS = DirectIntentPolicy.BYPASS_RESOLVER_INTENTS

    def __init__(
        self,
        *,
        alexa_user_id: str | None = None,
        listener_id: str | None = None,
        progressive: ProgressiveResponseClient,
        resolver: UtteranceResolver,
        user: User,
    ) -> None:
        self._alexa_user_id = alexa_user_id
        self._listener_id = listener_id
        self._progressive = progressive
        self._resolver = resolver
        self._user = user

    @staticmethod
    def _resolver_slots(slots: dict) -> dict[str, ResolverSlot]:
        return {
            name: ResolverSlot(
                resolved=AlexaRequest.get_resolved_slot_value(slot),
                spoken=AlexaRequest.get_spoken_slot_value(slot),
            )
            for name, slot in slots.items()
        }

    @staticmethod
    def _set_nlp(handler_input, payload: dict) -> None:
        attrs = RequestContext.request(handler_input)
        attrs["_nlp"] = payload
        RequestContext.replace_request(handler_input, attrs)

    @staticmethod
    def _extract_raw_utterance(handler_input, alexa_intent: str | None) -> str | None:
        slots = intent_slots(handler_input)
        if not slots:
            return None
        if alexa_intent == "CarrierlessDiscoveryIntent":
            spoken = AlexaRequest.get_spoken_slot_value(slots.get("discoveryQuery"))
            if spoken:
                return spoken
        if User.snapshot(handler_input).get("onboardingStage") == "ask_town":
            return next(
                (
                    value.strip()
                    for slot in slots.values()
                    if (value := AlexaRequest.get_resolved_slot_value(slot)) and value.strip()
                ),
                None,
            )
        if alexa_intent == "PlayLatestContentIntent":
            topic = AlexaRequest.get_resolved_slot_value(slots.get("topic"))
            content_format = AlexaRequest.get_resolved_slot_value(slots.get("format"))
            return " ".join(value for value in ("play", "latest", topic or content_format) if value)
        if alexa_intent in DiscoveryConstants.PUBLICATION_INTENTS:
            source = AlexaRequest.get_resolved_slot_value(slots.get("publicationSourceQuery"))
            requested_sort = AlexaRequest.get_resolved_slot_value(slots.get("publicationSort"))
            if str(requested_sort or "").casefold() not in ResolverConstants.PUBLICATION_SORTS:
                requested_sort = None
            suffix = f"from {source}" if source else ""
            return " ".join(
                value for value in ("play", requested_sort, "publication", suffix) if value
            )
        if alexa_intent in DiscoveryConstants.ORGANIZATION_INTENTS:
            topic = AlexaRequest.get_resolved_slot_value(slots.get("topic"))
            source = AlexaRequest.get_resolved_slot_value(slots.get("organizationQuery"))
            if source:
                if (
                    SearchFilterUtils.normalize_discovery_phrase(source)
                    in DiscoveryConstants.LOCAL_HINTS
                    or SearchFilterUtils.organization_request_kind(source, organization_intent=True)
                    != "specific"
                ):
                    return source
                return " ".join(value for value in ("play", topic, "from", source) if value)
        if alexa_intent == "PlayLocalIntent":
            topic = AlexaRequest.get_resolved_slot_value(slots.get("topic"))
            location = AlexaRequest.get_resolved_slot_value(
                slots.get("cityQuery") or slots.get("localQuery")
            )
            if topic and location:
                return f"play {topic} near {location}"
            if location:
                return f"play near {location}"
        ordered = (
            ResolverConstants.RAW_SLOT_PRIORITY.get(
                alexa_intent, ResolverConstants.DEFAULT_RAW_SLOT_PRIORITY
            )
            if alexa_intent
            else ResolverConstants.DEFAULT_RAW_SLOT_PRIORITY
        )
        raw = next(
            (
                value.strip()
                for name in ordered
                if (value := AlexaRequest.get_resolved_slot_value(slots.get(name)))
                and value.strip()
            ),
            None,
        )
        if raw:
            return raw
        return next(
            (
                str(AlexaRequest.get_spoken_slot_value(slot) or "").strip()
                for name, slot in slots.items()
                if name != "dateQuery"
                and str(AlexaRequest.get_spoken_slot_value(slot) or "").strip()
            ),
            None,
        )

    @staticmethod
    def _extract_effective_discovery_input(
        handler_input, alexa_intent: str | None, raw: str | None
    ) -> str | None:
        if alexa_intent != "CarrierlessDiscoveryIntent":
            return raw
        for slot_name in ("discoveryQuery", "topic"):
            selection = AlexaRequest.get_discovery_slot_selection(
                intent_slots(handler_input).get(slot_name)
            )
            if selection["effective"]:
                return selection["effective"]
        return raw

    @staticmethod
    def _request(handler_input) -> dict | None:
        if RequestContext.request(handler_input).get(DialogConstants.VALIDATION_FAILURE):
            return None
        request = AlexaRequest.read(handler_input.request_envelope, "request")
        intent = AlexaRequest.read(request, "intent")
        if not request or AlexaRequest.read(request, "type") != "IntentRequest" or not intent:
            return None
        alexa_intent = AlexaRequest.read(intent, "name")
        if not alexa_intent:
            return None
        if alexa_intent in ResolverWorkflowRunner.DIRECT_HANDLER_INTENTS:
            return None
        slots = AlexaRequest.read(intent, "slots") or {}
        store = User.snapshot(handler_input)
        dialog = DialogStateManager.active_from_store(store)
        active_dialog: dict = dialog if isinstance(dialog, dict) else {}
        if active_dialog.get("type") == AvailabilityConstants.DIALOG_TYPE:
            dialog_context_candidate = active_dialog.get("context")
            dialog_context: dict = (
                dialog_context_candidate if isinstance(dialog_context_candidate, dict) else {}
            )
            raw = ResolverWorkflowRunner._extract_raw_utterance(handler_input, alexa_intent)
            candidate = DialogSelection.request_candidate(handler_input, dialog_context)
            if not candidate and raw:
                candidate = DialogSelection.match_pending_candidate(
                    handler_input, dialog_context, raw
                )
            is_dialog_control = (
                alexa_intent in AvailabilityConstants.EXIT_INTENTS
                or alexa_intent in AvailabilityConstants.MORE_INTENTS
                or alexa_intent in AvailabilityConstants.PREVIOUS_INTENTS
                or alexa_intent in DialogConstants.CHOICE_DISMISS_INTENTS
                or (
                    alexa_intent in {"AMAZON.YesIntent", "AMAZON.NoIntent"}
                    and dialog_context.get("singleChoice")
                )
                or (
                    alexa_intent in {"AMAZON.YesIntent", "AMAZON.NoIntent"}
                    and dialog_context.get("kind") == AvailabilityConstants.FORMAT_KIND
                )
                or alexa_intent == "AMAZON.NoIntent"
                or alexa_intent == "ClarifySelectionIntent"
                or alexa_intent == "AMAZON.FallbackIntent"
                or DialogSelection.is_dismiss_phrase(raw)
                or bool(candidate)
            )
            if is_dialog_control:
                return None
            DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
            store = User.snapshot(handler_input)
            dialog = None
        ambiguity_active = bool(
            isinstance(store.get("pendingAmbiguity"), dict)
            or (dialog or {}).get("type") == "ambiguity"
        )
        return {
            "alexa_intent": alexa_intent,
            "slots": slots,
            "store": store,
            "dialog": dialog,
            "ambiguity_active": ambiguity_active,
        }

    @staticmethod
    def _location_capture_active(context: dict) -> bool:
        store = context["store"]
        dialog = context.get("dialog") or {}
        dialog_context = dialog.get("context") or {}
        stage = store.get("onboardingStage") or dialog_context.get("stage")
        return stage in {
            OnboardingConstants.ASK_PERMISSION,
            OnboardingConstants.ASK_TOWN,
            OnboardingConstants.AWAIT_LOCATION_CONFIRMATION,
        }

    @staticmethod
    def _capture_location(handler_input, context: dict) -> bool:
        alexa_intent = context["alexa_intent"]
        if (
            alexa_intent
            in {
                "SetLocationIntent",
                "SearchLocationIntent",
            }
            and not context["ambiguity_active"]
        ):
            slot_name = "searchQuery" if alexa_intent == "SearchLocationIntent" else "location"
            town = AlexaRequest.get_resolved_slot_value(context["slots"].get(slot_name))
            ResolverWorkflowRunner._set_nlp(
                handler_input,
                {
                    "intent": "location_set",
                    "alexaIntent": "location_set",
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": True,
                    "needsRedirect": False,
                    "confidence": "high",
                    "slots": {"townName": town} if town else {},
                    "localResolved": bool(town),
                },
            )
            return True
        if alexa_intent != "TownCaptureIntent" or context["ambiguity_active"]:
            return False
        if not ResolverWorkflowRunner._location_capture_active(context):
            ResolverWorkflowRunner._set_nlp(
                handler_input,
                {
                    "intent": "general",
                    "alexaIntent": "general",
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": False,
                    "needsRedirect": True,
                    "confidence": "low",
                    "slots": {},
                },
            )
            return True
        town = AlexaRequest.get_resolved_slot_value(context["slots"].get("townName"))
        ResolverWorkflowRunner._set_nlp(
            handler_input,
            {
                "intent": "town_capture",
                "alexaIntent": "town_capture",
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": True,
                "needsRedirect": False,
                "confidence": "high",
                "slots": {"townName": town, "placeName": town} if town else {},
            },
        )
        return True

    async def _resolver_result(
        self,
        handler_input,
        raw: str,
        alexa_intent: str | None = None,
        *,
        prefer_location: bool = False,
    ) -> dict:
        carrier = ResolverConstants.CARRIERS.get(alexa_intent, "") if alexa_intent else ""
        normalized = SearchFilterUtils.normalize_discovery_phrase(raw)
        carrier_verb = carrier.partition(" ")[0]
        has_carrier = bool(
            not carrier
            or normalized == carrier
            or normalized.startswith(f"{carrier} ")
            or (carrier_verb and normalized.startswith(f"{carrier_verb} "))
        )
        utterance = raw if has_carrier else f"{carrier} {raw}"
        alexa_user_id = self._alexa_user_id or AlexaRequest.get_user_id(handler_input)
        listener_id = self._listener_id or User.snapshot(handler_input).get("listenerId")
        resolved_listener_id = str(listener_id).strip() if listener_id else None
        await self._progressive.send(handler_input, Speech.RESOLVER_PROGRESSIVE)
        timeout_ms = DeadlineBudget.resolver_timeout_ms(handler_input)
        ApplicationLog.info(
            "Hear: resolver input alexaIntent=%s utterance=%r preferLocation=%s timeoutMs=%s listenerIdPresent=%s",
            alexa_intent or "unknown",
            utterance,
            prefer_location,
            timeout_ms,
            bool(resolved_listener_id),
        )
        if resolved_listener_id and prefer_location:
            return await self._resolver.resolve_utterance(
                utterance,
                alexa_user_id=alexa_user_id,
                timeout_ms=timeout_ms,
                listener_id=resolved_listener_id,
                prefer_location=True,
            )
        if resolved_listener_id:
            return await self._resolver.resolve_utterance(
                utterance,
                alexa_user_id=alexa_user_id,
                timeout_ms=timeout_ms,
                listener_id=resolved_listener_id,
            )
        if prefer_location:
            return await self._resolver.resolve_utterance(
                utterance,
                alexa_user_id=alexa_user_id,
                timeout_ms=timeout_ms,
                prefer_location=True,
            )
        return await self._resolver.resolve_utterance(
            utterance,
            alexa_user_id=alexa_user_id,
            timeout_ms=timeout_ms,
        )

    async def _resolve_ambiguity(
        self,
        handler_input,
        context: dict,
        raw: str | None,
        pending: dict | None,
    ) -> bool:
        if not isinstance(pending, dict):
            return False
        if int(pending.get("expiresAt") or 0) < int(time.time()):
            self._user.update(handler_input, {"pendingAmbiguity": None})
            DialogStateManager.clear(handler_input, "ambiguity")
            return False
        alexa_intent = context["alexa_intent"]
        if alexa_intent in ResolverWorkflow.AMBIGUITY_CONTROL_INTENTS:
            return False
        if (
            alexa_intent in DialogConstants.CHOICE_DISMISS_INTENTS
            or alexa_intent == "AMAZON.NoIntent"
            or DialogSelection.is_dismiss_phrase(raw)
        ):
            self._user.update(handler_input, {"pendingAmbiguity": None})
            DialogStateManager.dismiss_ambiguity(handler_input)
            ResolverWorkflowRunner._set_nlp(
                handler_input,
                {
                    "intent": "dismiss_choices",
                    "status": "resolved",
                    "alexaIntent": "dismiss_choices",
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": False,
                    "needsRedirect": True,
                    "localResolved": True,
                },
            )
            return True
        if not raw:
            return False
        candidate = DialogSelection.request_candidate(handler_input, pending)
        if not candidate:
            candidate = DialogSelection.match_pending_candidate(handler_input, pending, raw)
        if candidate:
            result = ResolverWorkflow._resolved_pending_candidate(pending, candidate)
        elif alexa_intent == "ClarifySelectionIntent":
            result = ResolverWorkflow._unmatched_ambiguity_result(pending, raw)
        else:
            result = await self._resolver_result(handler_input, raw, alexa_intent)
        if result.get("status") == "resolved":
            self._user.update(
                handler_input,
                {
                    "pendingAmbiguity": None,
                    "awaitingLocationConfirm": False,
                    "pendingLocationConfirm": None,
                },
            )
            DialogStateManager.clear(handler_input, "ambiguity")
        elif result.get("status") == "ambiguous":
            narrowed = (result.get("ambiguities") or [{}])[0].get("candidates") or []
            displayed = (
                narrowed[: DiscoveryConstants.CHOICE_PAGE_SIZE]
                if result.get("followUpMatched", True)
                else DialogSelection.displayed_choices(pending)
            )
            narrowed_context = {
                **pending,
                "displayedCandidates": displayed,
                "expiresAt": int(time.time()) + 300,
            }
            self._user.update(handler_input, {"pendingAmbiguity": narrowed_context})
            DialogStateManager.activate(handler_input, "ambiguity", context=narrowed_context)
        else:
            result = ResolverWorkflow._unmatched_ambiguity_result(pending, raw)
            displayed = DialogSelection.displayed_choices(pending)
            narrowed_context = {
                **pending,
                "displayedCandidates": displayed,
                "expiresAt": int(time.time()) + 300,
            }
            self._user.update(handler_input, {"pendingAmbiguity": narrowed_context})
            DialogStateManager.activate(handler_input, "ambiguity", context=narrowed_context)
        ResolverWorkflowRunner._set_nlp(
            handler_input,
            {
                **result,
                "ambiguityRetry": result.get("status") == "ambiguous",
                "alexaIntent": DiscoveryConstants.ALEXA_TO_NLP.get(alexa_intent, "general"),
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": False,
                "needsRedirect": True,
                "localResolved": True,
            },
        )
        return True

    async def _resolve_creator_location_query(
        self,
        handler_input,
        city_candidate: str | None,
        alexa_intent: str,
    ) -> bool:
        try:
            result = await self._resolver_result(
                handler_input,
                city_candidate or "",
                prefer_location=True,
            )
        except ResolverUnavailable:
            result = {}
        location = ResolverWorkflowRunner._canonical_location(result)
        if location:
            DialogStateManager.clear(handler_input, "creator_location")
            slots = {
                **dict(result.get("slots") or {}),
                **location,
                "placeName": location["city"],
                "isLocal": True,
            }
            search_payload = dict(result.get("searchPayload") or {})
            search_payload["filter"] = location
            result.update(
                {
                    "intent": "creator_location",
                    "requestedLocation": True,
                    "slots": slots,
                    "searchPayload": {**search_payload, "query": ""},
                }
            )
        else:
            result = {
                "status": "resolved",
                "intent": "creator_location",
                "requestedLocation": True,
                "locationRejected": True,
                "slots": {},
                "searchPayload": {"query": "", "filter": {}},
            }
        ResolverWorkflowRunner._set_nlp(
            handler_input,
            {
                **result,
                "alexaIntent": "creator_location",
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": True,
                "needsRedirect": True,
                "localResolved": True,
            },
        )
        return True

    async def _resolve_follow_up(
        self,
        handler_input,
        context: dict,
        raw: str | None,
        store: dict,
    ) -> bool:
        if not raw:
            return False
        alexa_intent = context["alexa_intent"]
        if store.get("onboardingStage") == "ask_town":
            ResolverWorkflowRunner._set_nlp(
                handler_input,
                {
                    "intent": "town_capture",
                    "alexaIntent": DiscoveryConstants.ALEXA_TO_NLP.get(alexa_intent, "general"),
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": False,
                    "needsRedirect": True,
                    "confidence": "high",
                    "slots": {"townName": raw, "placeName": raw},
                },
            )
            return True
        dialog_type = (DialogStateManager.active_from_store(store) or {}).get("type")
        if dialog_type == "creator_location":
            return await self._resolve_creator_location_query(
                handler_input,
                ResolverWorkflowRunner._creator_location_follow_up(handler_input, raw),
                alexa_intent,
            )
        follow_up = (
            ("organization", "organizationQuery", "PlayByOrganizationIntent")
            if store.get("awaitingOrganizationName") or dialog_type == "organization_name"
            else ("publication", "publicationSourceQuery", "PlayPublicationIntent")
            if store.get("awaitingPublicationSource") or dialog_type == "publication_source"
            else None
        )
        if not follow_up:
            return False
        intent_name, slot_name, matching_intent = follow_up
        matching_intents = (
            DiscoveryConstants.ORGANIZATION_INTENTS
            if intent_name == "organization"
            else DiscoveryConstants.PUBLICATION_INTENTS
        )
        result = await self._resolver_result(handler_input, raw, matching_intent)
        result["intent"] = intent_name
        result.setdefault("slots", {})[slot_name] = raw
        result["slots"][f"{intent_name}FollowUp"] = True
        if result.get("status") == "resolved":
            dialog_name = (
                "publication_source" if intent_name == "publication" else f"{intent_name}_name"
            )
            DialogStateManager.clear(handler_input, dialog_name)
        ResolverWorkflowRunner._set_nlp(
            handler_input,
            {
                **result,
                "alexaIntent": intent_name,
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": alexa_intent in matching_intents,
                "needsRedirect": alexa_intent not in matching_intents,
                "localResolved": True,
            },
        )
        return True

    @staticmethod
    def _canonical_location(result: dict) -> dict | None:
        if result.get("status") != "resolved":
            return None
        resolution = result.get("resolution")
        match = resolution.get("match") if isinstance(resolution, dict) else None
        if not isinstance(match, dict):
            return None
        slots_candidate = result.get("slots")
        slots: dict = slots_candidate if isinstance(slots_candidate, dict) else {}
        city = str(match.get("city") or match.get("locality") or "").strip()
        country_code = str(
            match.get("countryCode") or slots.get("countryCode") or ""
        ).strip()
        latitude = match.get("latitude", slots.get("latitude"))
        longitude = match.get("longitude", slots.get("longitude"))
        if not city or not country_code or latitude is None or longitude is None:
            return None
        return {
            "city": city,
            "countryCode": country_code,
            "latitude": latitude,
            "longitude": longitude,
        }

    @staticmethod
    def _creator_location_follow_up(handler_input, fallback: str | None) -> str | None:
        slots = DialogSelection.request_slots(handler_input)
        for slot_name in ResolverConstants.CREATOR_LOCATION_SLOTS:
            value = AlexaRequest.get_resolved_slot_value(slots.get(slot_name))
            if value:
                return value.strip()
        return next(
            (
                spoken.strip()
                for slot in slots.values()
                if (spoken := AlexaRequest.get_spoken_slot_value(slot)) and spoken.strip()
            ),
            fallback,
        )

    @staticmethod
    def _resolve_known_without_raw(handler_input, alexa_intent: str) -> None:
        if alexa_intent == "AMAZON.FallbackIntent":
            return
        known = DiscoveryConstants.ALEXA_TO_NLP.get(alexa_intent)
        if known and alexa_intent not in ResolverWorkflow.SEARCH_INTENTS:
            ResolverWorkflowRunner._set_nlp(
                handler_input,
                {
                    "intent": known,
                    "alexaIntent": known,
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": True,
                    "needsRedirect": False,
                    "confidence": "high",
                    "slots": {},
                },
            )

    async def _resolve_default(
        self,
        handler_input,
        alexa_intent: str,
        raw: str | None,
        intent_slots: dict,
        reported_alexa_intent: str | None = None,
    ) -> None:
        if not raw:
            ResolverWorkflowRunner._resolve_known_without_raw(handler_input, alexa_intent)
            return
        expected = DiscoveryConstants.ALEXA_TO_NLP.get(alexa_intent, "general")
        if alexa_intent in ResolverWorkflow.SEARCH_INTENTS:
            result = await self._resolver_result(handler_input, raw, alexa_intent)
            result = ResolverWorkflow.apply_alexa_constraints(
                result,
                alexa_intent,
                ResolverWorkflowRunner._resolver_slots(intent_slots),
            )
        else:
            if alexa_intent not in DiscoveryConstants.ALEXA_TO_NLP:
                return
            result = {"intent": expected, "confidence": "high", "slots": {}}
        actual = str(result.get("semanticIntent") or result["intent"])
        result = {**result, "intent": actual}
        if (
            alexa_intent in ResolverWorkflow.SEARCH_INTENTS
            and actual in ResolverWorkflow.LOCATION_MUTATION_INTENTS
        ):
            ApplicationLog.warning(
                "Hear: blocked location mutation from discovery intent=%s resolved=%s",
                alexa_intent,
                actual,
            )
            actual = expected
            result = {**result, "intent": actual}
        reported = reported_alexa_intent or alexa_intent
        ResolverWorkflowRunner._set_nlp(
            handler_input,
            {
                **result,
                "alexaIntent": expected,
                "alexaRawIntent": reported,
                "nlpMatchesAlexa": actual == expected and reported == alexa_intent,
                "needsRedirect": actual != expected or reported != alexa_intent,
                "localResolved": alexa_intent in ResolverWorkflow.SEARCH_INTENTS,
            },
        )

    async def _apply(self, handler_input) -> None:
        context = ResolverWorkflowRunner._request(handler_input)
        if not context:
            return
        alexa_intent = context["alexa_intent"]
        raw = ResolverWorkflowRunner._extract_raw_utterance(handler_input, alexa_intent)
        effective = ResolverWorkflowRunner._extract_effective_discovery_input(
            handler_input, alexa_intent, raw
        )
        store = User.snapshot(handler_input)
        dialog_type = (context.get("dialog") or {}).get("type")
        if await self._resolve_ambiguity(
            handler_input, context, raw, store.get("pendingAmbiguity")
        ):
            return
        follow_up_input = (
            ResolverWorkflowRunner._creator_location_follow_up(handler_input, raw)
            if dialog_type == "creator_location"
            else effective
        )
        if await self._resolve_follow_up(handler_input, context, follow_up_input, store):
            return
        raw_norm = (raw or "").strip().lower()
        effective_norm = (effective or "").strip().lower()
        candidate_term = effective_norm or raw_norm
        if not dialog_type:
            if candidate_term in {"stop", "cancel"} or raw_norm in {"stop", "cancel"}:
                ResolverWorkflowRunner._set_nlp(
                    handler_input,
                    {
                        "status": "resolved",
                        "intent": "stop",
                        "alexaIntent": "AMAZON.StopIntent",
                        "alexaRawIntent": alexa_intent,
                        "nlpMatchesAlexa": False,
                        "needsRedirect": True,
                        "slots": {},
                    },
                )
                return
            if (
                DialogSelection.is_dismiss_phrase(candidate_term)
                or DialogSelection.is_dismiss_phrase(raw_norm)
                or candidate_term in DialogConstants.CHOICE_DISMISS_PHRASES
                or raw_norm in DialogConstants.CHOICE_DISMISS_PHRASES
                or candidate_term in DialogConstants.IDLE_AFFIRMATIVE_PHRASES
                or raw_norm in DialogConstants.IDLE_AFFIRMATIVE_PHRASES
                or candidate_term in {"no", "nope", "nah", "none", "nothing", "never mind", "no thanks"}
                or raw_norm in {"no", "nope", "nah", "none", "nothing", "never mind", "no thanks"}
            ):
                ResolverWorkflowRunner._set_nlp(
                    handler_input,
                    {
                        "status": "resolved",
                        "intent": "idle_dismiss",
                        "alexaIntent": "OpenDiscoveryIntent",
                        "alexaRawIntent": alexa_intent,
                        "nlpMatchesAlexa": False,
                        "needsRedirect": True,
                        "slots": {},
                    },
                )
                return
        if alexa_intent == "SelectCreatorCityIntent":
            city_query = (
                AlexaRequest.get_spoken_slot_value(context["slots"].get("cityQuery"))
                or raw
            )
            extracted = SearchFilterUtils.extract_creator_city(city_query) or city_query
            await self._resolve_creator_location_query(handler_input, extracted, alexa_intent)
            return
        creator_city = SearchFilterUtils.extract_creator_city(raw) or SearchFilterUtils.extract_creator_city(effective)
        if creator_city:
            await self._resolve_creator_location_query(handler_input, creator_city, alexa_intent)
            return
        carrierless_slot = ResolverWorkflow.CARRIERLESS_SELECTOR_SLOTS.get(alexa_intent)
        if carrierless_slot and not dialog_type:
            spoken = AlexaRequest.get_spoken_slot_value(context["slots"].get(carrierless_slot))
            if spoken:
                await self._resolve_default(
                    handler_input,
                    "SearchContentIntent",
                    spoken,
                    {"searchQuery": {"value": spoken}},
                    reported_alexa_intent=alexa_intent,
                )
                return
        if (
            alexa_intent in {"SetLocationIntent", "TownCaptureIntent"}
            and raw
            and not ResolverWorkflowRunner._location_capture_active(context)
        ):
            await self._resolve_default(
                handler_input,
                "SearchContentIntent",
                raw,
                {"searchQuery": {"value": raw}},
                reported_alexa_intent=alexa_intent,
            )
            return
        if ResolverWorkflowRunner._capture_location(handler_input, context):
            return
        local = ResolverWorkflow._local_discovery_resolution(
            alexa_intent,
            ResolverWorkflowRunner._resolver_slots(context["slots"]),
            effective,
        )
        if local:
            local = ResolverWorkflow.apply_alexa_constraints(
                local,
                alexa_intent,
                ResolverWorkflowRunner._resolver_slots(context["slots"]),
            )
            ResolverWorkflowRunner._set_nlp(handler_input, local)
            ApplicationLog.info(
                "Hear: discovery request handled locally intent=%s result=%s",
                alexa_intent,
                local.get("intent"),
            )
            return
        if not effective and alexa_intent in ResolverWorkflow.SEARCH_INTENTS:
            effective = ResolverWorkflow.CANONICAL_ZERO_SLOT_DISCOVERY.get(alexa_intent)
        await self._resolve_default(handler_input, alexa_intent, effective, context["slots"])

    async def apply(self, handler_input) -> None:
        try:
            await self._apply(handler_input)
        except ResolverUnavailable:
            ResolverWorkflowRunner._set_nlp(
                handler_input,
                {"intent": "resolver_unavailable", "confidence": "low", "slots": {}},
            )
            ApplicationLog.warning("Hear resolver unavailable")
        except Exception:
            ResolverWorkflowRunner._set_nlp(
                handler_input,
                {"intent": "resolver_unavailable", "confidence": "low", "slots": {}},
            )
            ApplicationLog.warning("Hear resolver workflow error", exc_info=True)
