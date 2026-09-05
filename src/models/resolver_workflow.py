from __future__ import annotations

import logging

from config import settings
from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.constants.dialog import DialogConstants
from src.constants.discovery import DiscoveryConstants
from src.constants.resolver import ResolverConstants
from src.constants.search import SearchConstants
from src.models.dialog import DialogSelection
from src.models.user import User
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
    } | DialogConstants.CHOICE_DISMISS_INTENTS
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
            payload = SearchPayload.for_publication(
                payload, [entity_id], settings.search_page_limit
            )
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
            "intent": entity_type
            if entity_type in filter_keys
            else pending.get("intent", "search"),
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
        if User.snapshot(handler_input).get("onboardingStage") == "ask_town":
            return next(
                (
                    value.strip()
                    for slot in slots.values()
                    if (value := AlexaRequest.get_resolved_slot_value(slot)) and value.strip()
                ),
                None,
            )
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
        if alexa_intent == "PlayByOrganizationIntent":
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
        if alexa_intent == "PlayByCreatorIntent":
            topic = AlexaRequest.get_resolved_slot_value(slots.get("topic"))
            creator = AlexaRequest.get_resolved_slot_value(slots.get("creatorQuery"))
            if creator:
                if (
                    SearchFilterUtils.normalize_discovery_phrase(creator)
                    in DiscoveryConstants.LOCAL_HINTS
                    or not SearchFilterUtils.is_meaningful_creator_source(creator)
                ):
                    return creator
                return " ".join(value for value in ("play", topic, "by", creator) if value)
        if alexa_intent == "PlayLocalIntent":
            topic = AlexaRequest.get_resolved_slot_value(slots.get("topic"))
            location = AlexaRequest.get_resolved_slot_value(
                slots.get("cityQuery") or slots.get("localQuery")
            )
            if topic and location:
                return f"play {topic} near {location}"
            if location:
                return f"play near {location}"
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
            "PlayLocalIntent": ("cityQuery", "localQuery", "topic"),
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
            "searchPayload": {
                "query": "",
                "filter": {},
                "sort": sort,
                "page": 0,
                "limit": DiscoveryConstants.CHOICE_PAGE_SIZE,
            },
            "slots": {
                "residualQuery": "",
                "isRecommended": intent_name == "trending",
                "sort": sort,
            },
        }
