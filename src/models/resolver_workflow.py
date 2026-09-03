from __future__ import annotations

import logging
import time

from config import settings
from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.speech import Speech
from src.constants.dialog import DialogConstants
from src.constants.discovery import DiscoveryConstants
from src.constants.resolver import ResolverConstants
from src.constants.search import SearchConstants
from src.models.dialog import DialogSelection, DialogStateManager
from src.models.resolver import ResolverUnavailable
from src.models.user import User
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilters, SearchFilterUtils
from src.utils.search_payload import SearchPayload


class ResolverWorkflow:
    logger = logging.getLogger(__name__)
    SEARCH_INTENTS = {
        "PlayContentIntent",
        "PlayLatestContentIntent",
        "PlayByCreatorIntent",
        "PlayByOrganizationIntent",
        "PlayPublicationIntent",
        "BrowseContentIntent",
        "BrowseByCategoryIntent",
        "WhatsTrendingIntent",
        "PlayLocalIntent",
        "PlayRecommendationIntent",
    }
    LOCATION_MUTATION_INTENTS = {"location_set", "town_capture"}
    AMBIGUITY_CONTROL_INTENTS = {
        "AMAZON.YesIntent",
        "AMAZON.NoIntent",
        "AMAZON.CancelIntent",
        "AMAZON.StopIntent",
        "AMAZON.HelpIntent",
        "AMAZON.FallbackIntent",
        "AMAZON.NextIntent",
        "AMAZON.PreviousIntent",
        "ShowMoreBrowseIntent",
        "ShowPreviousBrowseIntent",
    }
    CANONICAL_ZERO_SLOT_DISCOVERY = {
        "PlayContentIntent": "play",
        "PlayLatestContentIntent": "play latest",
        "PlayByCreatorIntent": "play",
        "PlayByOrganizationIntent": "play",
        "PlayPublicationIntent": "play publication",
        "BrowseByCategoryIntent": "play",
        "BrowseContentIntent": "what's new",
        "WhatsTrendingIntent": "what's trending",
        "PlayLocalIntent": "play local content",
        "PlayRecommendationIntent": "recommend something",
    }

    @staticmethod
    def _normalize_ordinal(value: object) -> str:
        return DialogSelection.normalize_ordinal(value)

    @staticmethod
    def _resolved_pending_candidate(pending: dict, candidate: dict) -> dict:
        entity_type = str(candidate["type"])
        entity_id, name = str(candidate["id"]), str(candidate["name"])
        filter_keys = SearchConstants.SEARCH_SOURCE_FILTERS
        filter_key = filter_keys.get(entity_type)
        filters = SearchFilters.replace_source(
            (pending.get("searchPayload") or {}).get("filter"), entity_type, entity_id
        )
        payload = {
            **dict(pending.get("searchPayload") or {}),
            "query": "",
            "filter": filters,
            "page": 0,
        }
        if entity_type == "publication":
            payload = SearchPayload.for_publication(payload, [entity_id], settings.search_page_limit)
        slots = {
            **dict(pending.get("slots") or {}),
            "residualQuery": "",
            "ambiguousReferences": [],
        }
        for source_key in (*filter_keys.values(), *SearchConstants.SEARCH_SOURCE_NAMES.values()):
            slots.pop(source_key, None)
        if filter_key:
            slots[filter_key] = [entity_id]
            slots[SearchConstants.SEARCH_SOURCE_NAMES[entity_type]] = name
        return {
            "status": "resolved",
            "intent": entity_type if entity_type in filter_keys else pending.get("intent", "search"),
            "ambiguityResolution": True,
            "confirmationLabel": f"content from {name}",
            "searchPayload": payload,
            "entities": [{"type": entity_type, "id": entity_id, "canonicalValue": name}],
            "slots": slots,
            "ambiguities": [],
        }

    @staticmethod
    def _unmatched_ambiguity_result(pending: dict, raw: str) -> dict:
        candidates = DialogSelection.choices(pending)
        reference = {"phrase": raw, "candidates": candidates}
        return {
            "status": "ambiguous",
            "intent": pending.get("intent", "search"),
            "slots": {
                **dict(pending.get("slots") or {}),
                "ambiguousReferences": [reference],
            },
            "ambiguities": [reference],
            "followUpMatched": True,
        }

    @staticmethod
    def _extract_raw_utterance(handler_input, alexa_intent: str | None) -> str | None:
        slots = DialogSelection.request_slots(handler_input)
        if not slots:
            return None
        date_text = AlexaRequest.get_resolved_slot_value(slots.get("dateQuery")) or ""
        if alexa_intent == "PlayLatestContentIntent":
            topic = AlexaRequest.get_resolved_slot_value(slots.get("topic"))
            content_format = AlexaRequest.get_resolved_slot_value(slots.get("format"))
            return " ".join(
                value for value in ("play", date_text, "latest", topic or content_format) if value
            )
        if alexa_intent == "PlayPublicationIntent":
            source = AlexaRequest.get_resolved_slot_value(slots.get("publicationSourceQuery"))
            requested_sort = AlexaRequest.get_resolved_slot_value(slots.get("publicationSort"))
            suffix = f"from {source}" if source else ""
            return " ".join(
                value
                for value in ("play", date_text, requested_sort, "publication", suffix)
                if value
            )
        ordered = ResolverConstants.RAW_SLOT_PRIORITY.get(
            alexa_intent, ResolverConstants.DEFAULT_RAW_SLOT_PRIORITY
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
            return f"{date_text} {raw}".strip()
        fallback = next(
            (
                str(getattr(slot, "value", "") or "").strip()
                for name, slot in slots.items()
                if name != "dateQuery" and str(getattr(slot, "value", "") or "").strip()
            ),
            None,
        )
        if fallback:
            return f"{date_text} {fallback}".strip()
        return date_text or None

    @staticmethod
    def _set_nlp(handler_input, payload: dict) -> None:
        attrs = RequestContext.request(handler_input)
        attrs["_nlp"] = payload
        RequestContext.replace_request(handler_input, attrs)

    @staticmethod
    def _local_discovery_resolution(
        alexa_intent: str, intent_slots: dict, raw: str | None
    ) -> dict | None:
        """Return discovery requests whose meaning Alexa has already supplied."""
        AlexaRequest.get_resolved_slot_value(intent_slots.get("topic"))
        date_query = AlexaRequest.get_resolved_slot_value(intent_slots.get("dateQuery"))
        normalized_raw = SearchFilterUtils.normalize_discovery_phrase(raw)
        if normalized_raw in DiscoveryConstants.LOCAL_HINTS:
            return ResolverWorkflow._direct_discovery_result(
                alexa_intent,
                "local",
                "latest",
            )
        direct: dict[str, tuple[str, str]] = {
            "WhatsTrendingIntent": ("trending", "trending"),
            "PlayRecommendationIntent": ("trending", "trending"),
            "BrowseContentIntent": ("browse", "latest"),
            "PlayLocalIntent": ("local", "latest"),
        }
        direct_slot_names = {
            "WhatsTrendingIntent": ("topic", "dateQuery"),
            "PlayRecommendationIntent": ("recommendationQuery",),
            "BrowseContentIntent": ("dateQuery",),
            "PlayLocalIntent": ("localQuery",),
        }
        if alexa_intent in direct and (
            not any(
                (
                    AlexaRequest.get_resolved_slot_value(intent_slots.get(name))
                    for name in direct_slot_names[alexa_intent]
                )
            )
        ):
            intent_name, sort = direct[alexa_intent]
            return ResolverWorkflow._direct_discovery_result(alexa_intent, intent_name, sort)
        if alexa_intent == "PlayByCreatorIntent" and (
            not SearchFilterUtils.is_meaningful_creator_source(raw)
        ):
            return {
                "status": "resolved",
                "intent": "creator",
                "alexaIntent": "creator",
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": True,
                "needsRedirect": False,
                "localResolved": True,
                "slots": {"creatorQuery": "", "genericCreatorRequest": True},
            }
        organization_request_kind = SearchFilterUtils.organization_request_kind(
            raw,
            organization_intent=alexa_intent == "PlayByOrganizationIntent",
        )
        generic_organization = (
            alexa_intent == "PlayByOrganizationIntent"
            and organization_request_kind != "specific"
            or alexa_intent == "PlayContentIntent"
            and organization_request_kind in {"generic", "repair"}
        )
        if generic_organization:
            organization_slots = {
                "organizationQuery": "",
                "genericOrganizationRequest": True,
            }
            if organization_request_kind == "repair":
                organization_slots["talkingNewspaperRepairCandidate"] = True
            return {
                "status": "resolved",
                "intent": "organization",
                "alexaIntent": "organization",
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": alexa_intent == "PlayByOrganizationIntent",
                "needsRedirect": alexa_intent != "PlayByOrganizationIntent",
                "localResolved": True,
                "slots": organization_slots,
            }
        if alexa_intent == "PlayPublicationIntent":
            source = AlexaRequest.get_resolved_slot_value(
                intent_slots.get("publicationSourceQuery")
            )
            if not SearchFilterUtils.is_meaningful_publication_source(source):
                return {
                    "status": "resolved",
                    "intent": "publication",
                    "alexaIntent": "publication",
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": True,
                    "needsRedirect": False,
                    "localResolved": True,
                    "publicationSourceRequired": True,
                    "slots": {
                        "publicationSourceQuery": source or "",
                        "publicationSort": AlexaRequest.get_resolved_slot_value(
                            intent_slots.get("publicationSort")
                        ),
                        "dateQuery": date_query,
                    },
                }
        if (
            alexa_intent in ResolverWorkflow.SEARCH_INTENTS
            and SearchFilterUtils.is_reserved_discovery_phrase(raw)
        ):
            return {
                "status": "resolved",
                "intent": "general",
                "alexaIntent": "general",
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": True,
                "needsRedirect": False,
                "localResolved": True,
                "searchPayload": {"query": "", "filter": {}},
                "slots": {"residualQuery": ""},
            }
        return None

    @staticmethod
    def _direct_discovery_result(alexa_intent: str, intent_name: str, sort: str) -> dict:
        return {
            "status": "resolved",
            "intent": intent_name,
            "alexaIntent": DiscoveryConstants.ALEXA_TO_NLP.get(alexa_intent, intent_name),
            "alexaRawIntent": alexa_intent,
            "nlpMatchesAlexa": alexa_intent == "PlayLocalIntent" or intent_name != "local",
            "needsRedirect": alexa_intent != "PlayLocalIntent" and intent_name == "local",
            "localResolved": True,
            "directDiscoveryRequest": True,
            "searchPayload": {"query": "", "filter": {}, "sort": sort, "page": 0, "limit": 20},
            "slots": {"residualQuery": "", "isRecommended": intent_name == "trending", "sort": sort},
        }


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

    async def _resolver_result(self, handler_input, raw: str, alexa_intent: str | None = None) -> dict:
        carrier = ResolverConstants.CARRIERS.get(alexa_intent, "")
        normalized = SearchFilterUtils.normalize_discovery_phrase(raw)
        has_carrier = not carrier or normalized == carrier or normalized.startswith(f"{carrier} ")
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
                narrowed[:3]
                if result.get("followUpMatched", True)
                else list(pending.get("displayedCandidates") or [])[:3]
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
