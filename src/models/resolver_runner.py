from __future__ import annotations

import time

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.constants.dialog import DialogConstants
from src.constants.discovery import DiscoveryConstants
from src.constants.resolver import ResolverConstants
from src.models.dialog import DialogSelection, DialogStateManager
from src.models.resolver import ResolverUnavailable
from src.models.resolver_workflow import ResolverWorkflow
from src.models.user import User
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilterUtils


class ResolverWorkflowRunner:
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

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
        slots = AlexaRequest.read(intent, "slots") or {}
        store = User.snapshot(handler_input)
        dialog = DialogStateManager.active_from_store(store)
        if (dialog or {}).get("type") == "availability":
            return None
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
    def _capture_location(handler_input, context: dict) -> bool:
        alexa_intent = context["alexa_intent"]
        if alexa_intent == "SetLocationIntent" and not context["ambiguity_active"]:
            town = AlexaRequest.get_resolved_slot_value(context["slots"].get("location"))
            ResolverWorkflow._set_nlp(
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
        town = AlexaRequest.get_resolved_slot_value(context["slots"].get("townName"))
        ResolverWorkflow._set_nlp(
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
        self, handler_input, raw: str, alexa_intent: str | None = None
    ) -> dict:
        carrier = ResolverConstants.CARRIERS.get(alexa_intent, "")
        normalized = SearchFilterUtils.normalize_discovery_phrase(raw)
        carrier_verb = carrier.partition(" ")[0]
        has_carrier = bool(
            not carrier
            or normalized == carrier
            or normalized.startswith(f"{carrier} ")
            or (carrier_verb and normalized.startswith(f"{carrier_verb} "))
        )
        utterance = raw if has_carrier else f"{carrier} {raw}"
        options = {
            "alexa_user_id": AlexaRequest.get_user_id(handler_input),
            "timeout_ms": DeadlineBudget.resolver_timeout_ms(handler_input),
        }
        listener_id = User.snapshot(handler_input).get("listenerId")
        if listener_id:
            options["listener_id"] = listener_id
        await self._deps.progressive.send(handler_input, Speech.RESOLVER_PROGRESSIVE)
        return await self._deps.resolver.resolve_utterance(utterance, **options)

    async def _resolve_ambiguity(
        self,
        handler_input,
        context: dict,
        raw: str | None,
        pending: dict | None,
    ) -> bool:
        if not raw or not isinstance(pending, dict):
            return False
        if int(pending.get("expiresAt") or 0) < int(time.time()):
            self._deps.user.update(handler_input, {"pendingAmbiguity": None})
            DialogStateManager.clear(handler_input, "ambiguity")
            return False
        alexa_intent = context["alexa_intent"]
        if alexa_intent in ResolverWorkflow.AMBIGUITY_CONTROL_INTENTS:
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
        replace = bool(
            alexa_intent in ResolverWorkflow.SEARCH_INTENTS
            and result.get("status") != "resolved"
            and not result.get("followUpMatched", False)
        )
        if replace:
            self._deps.user.update(handler_input, {"pendingAmbiguity": None})
            DialogStateManager.clear(handler_input, "ambiguity")
            return False
        if result.get("status") == "resolved":
            self._deps.user.update(
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
            self._deps.user.update(handler_input, {"pendingAmbiguity": narrowed_context})
            DialogStateManager.activate(handler_input, "ambiguity", context=narrowed_context)
        ResolverWorkflow._set_nlp(
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
            ResolverWorkflow._set_nlp(
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
        follow_up = (
            ("creator", "creatorQuery", "PlayByCreatorIntent")
            if store.get("awaitingCreatorName") or dialog_type == "creator_name"
            else ("organization", "organizationQuery", "PlayByOrganizationIntent")
            if store.get("awaitingOrganizationName") or dialog_type == "organization_name"
            else None
        )
        if not follow_up:
            return False
        intent_name, slot_name, matching_intent = follow_up
        result = await self._resolver_result(handler_input, raw, matching_intent)
        result["intent"] = intent_name
        result.setdefault("slots", {})[slot_name] = raw
        result["slots"][f"{intent_name}FollowUp"] = True
        if result.get("status") == "resolved":
            DialogStateManager.clear(handler_input, f"{intent_name}_name")
        ResolverWorkflow._set_nlp(
            handler_input,
            {
                **result,
                "alexaIntent": intent_name,
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": alexa_intent == matching_intent,
                "needsRedirect": alexa_intent != matching_intent,
                "localResolved": True,
            },
        )
        return True

    @staticmethod
    def _resolve_known_without_raw(handler_input, alexa_intent: str) -> None:
        if alexa_intent == "AMAZON.FallbackIntent":
            return
        known = DiscoveryConstants.ALEXA_TO_NLP.get(alexa_intent)
        if known and alexa_intent not in ResolverWorkflow.SEARCH_INTENTS:
            ResolverWorkflow._set_nlp(
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
    ) -> None:
        if not raw:
            ResolverWorkflowRunner._resolve_known_without_raw(handler_input, alexa_intent)
            return
        expected = DiscoveryConstants.ALEXA_TO_NLP.get(alexa_intent, "general")
        if alexa_intent in ResolverWorkflow.SEARCH_INTENTS:
            result = await self._resolver_result(handler_input, raw, alexa_intent)
        else:
            if alexa_intent not in DiscoveryConstants.ALEXA_TO_NLP:
                return
            result = {"intent": expected, "confidence": "high", "slots": {}}
        actual = result["intent"]
        if (
            alexa_intent in ResolverWorkflow.SEARCH_INTENTS
            and actual in ResolverWorkflow.LOCATION_MUTATION_INTENTS
        ):
            ResolverWorkflow.logger.warning(
                "Hear: blocked location mutation from discovery intent=%s resolved=%s",
                alexa_intent,
                actual,
            )
            actual = expected
            result = {**result, "intent": actual}
        ResolverWorkflow._set_nlp(
            handler_input,
            {
                **result,
                "alexaIntent": expected,
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": actual == expected,
                "needsRedirect": actual != expected,
                "localResolved": alexa_intent in ResolverWorkflow.SEARCH_INTENTS,
            },
        )

    async def _apply(self, handler_input) -> None:
        context = ResolverWorkflowRunner._request(handler_input)
        if not context or ResolverWorkflowRunner._capture_location(handler_input, context):
            return
        alexa_intent = context["alexa_intent"]
        raw = ResolverWorkflow._extract_raw_utterance(handler_input, alexa_intent)
        local = ResolverWorkflow._local_discovery_resolution(alexa_intent, context["slots"], raw)
        if local:
            ResolverWorkflow._set_nlp(handler_input, local)
            ResolverWorkflow.logger.info(
                "Hear: discovery request handled locally intent=%s result=%s",
                alexa_intent,
                local.get("intent"),
            )
            return
        if not raw and alexa_intent in ResolverWorkflow.SEARCH_INTENTS:
            raw = ResolverWorkflow.CANONICAL_ZERO_SLOT_DISCOVERY.get(alexa_intent)
        store = User.snapshot(handler_input)
        if await self._resolve_ambiguity(
            handler_input, context, raw, store.get("pendingAmbiguity")
        ):
            return
        if await self._resolve_follow_up(handler_input, context, raw, store):
            return
        await self._resolve_default(handler_input, alexa_intent, raw)

    async def apply(self, handler_input) -> None:
        try:
            await self._apply(handler_input)
        except ResolverUnavailable:
            ResolverWorkflow._set_nlp(
                handler_input,
                {"intent": "resolver_unavailable", "confidence": "low", "slots": {}},
            )
            ResolverWorkflow.logger.warning("Hear resolver unavailable")
        except Exception:
            ResolverWorkflow._set_nlp(
                handler_input,
                {"intent": "resolver_unavailable", "confidence": "low", "slots": {}},
            )
            ResolverWorkflow.logger.warning("Hear resolver workflow error", exc_info=True)
