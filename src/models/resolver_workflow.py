from __future__ import annotations

from config import settings
from src.constants.dialog import DialogConstants
from src.constants.discovery import DiscoveryConstants
from src.constants.resolver import ResolverConstants
from src.constants.search import SearchConstants
from src.models.dialog_policy import DialogPolicy
from src.models.resolver_inputs import ResolverSlots
from src.services.logging_control import ApplicationLog
from src.utils.alexa_date import AlexaDateRange
from src.utils.filters import SearchFilters, SearchFilterUtils
from src.utils.search_payload import SearchPayload


class ResolverWorkflow:
    SEARCH_INTENTS = {
        "ChooseSourceKindIntent",
        "OpenDiscoveryIntent",
        "CarrierlessDiscoveryIntent",
        "PlayContentIntent",
        "SearchContentIntent",
        "PlayLatestContentIntent",
        "SearchCreatorIntent",
        "SelectCreatorCityIntent",
        "PlayByOrganizationIntent",
        "SearchOrganizationIntent",
        "SelectOrganizationIntent",
        "PlayPublicationIntent",
        "SelectPublicationSourceIntent",
        "SearchPublicationIntent",
        "BrowseContentIntent",
        "BrowseByCategoryIntent",
        "PlayLocalIntent",
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
        "PlayByOrganizationIntent": "play",
        "SelectOrganizationIntent": "play",
        "PlayPublicationIntent": "play publication",
        "SelectPublicationSourceIntent": "play publication",
        "BrowseByCategoryIntent": "play",
        "BrowseContentIntent": "what's new",
        "WhatsTrendingIntent": "what's trending",
        "PlayLocalIntent": "play local content",
        "PlayRecommendationIntent": "recommend something",
    }
    SEARCH_QUERY_SOURCE_INTENTS = {
        "SearchContentIntent": ("general", ("creator", "organization", "publication")),
        "SearchCreatorIntent": ("creator", ("creator",)),
        "SearchOrganizationIntent": ("organization", ("organization",)),
        "SearchPublicationIntent": (
            "publication",
            ("publication", "creator", "organization"),
        ),
    }
    SOURCE_NAME_SLOTS = {
        "creator": ("creatorName", "creatorIds"),
        "organization": ("organizationName", "organizationIds"),
        "publication": ("publicationName", "publicationIds"),
    }
    SOURCE_QUERY_SLOTS = {
        "creator": "creatorQuery",
        "organization": "organizationQuery",
        "publication": "publicationSourceQuery",
        "general": "residualQuery",
    }
    CARRIERLESS_SELECTOR_SLOTS = {
        "SelectOrganizationIntent": "organizationQuery",
        "SelectPublicationSourceIntent": "publicationSourceQuery",
    }

    @staticmethod
    def _normalize_ordinal(value: object) -> str:
        return DialogPolicy.normalize_ordinal(value)

    @staticmethod
    def _resolved_pending_candidate(pending: dict, candidate: dict) -> dict:
        entity_type = str(candidate.get("type") or candidate.get("entityType") or "")
        entity_id = str(candidate.get("id") or candidate.get("entityId") or "")
        name = str(candidate.get("name") or candidate.get("canonicalValue") or "")
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
        candidates = DialogPolicy.choices(pending)
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
    def _apply_date_constraint(result: dict, intent_slots: dict) -> dict:
        date_query = ResolverSlots.resolved(intent_slots, "dateQuery")
        date_range = AlexaDateRange.parse(date_query, settings.HEAR_RESOLVER_TIMEZONE)
        if not date_range:
            return result
        filters = {key: date_range[key] for key in ("publishedFrom", "publishedTo")}
        constrained = dict(result)
        payload = dict(constrained.get("searchPayload") or {})
        payload["filter"] = {**dict(payload.get("filter") or {}), **filters}
        constrained["searchPayload"] = payload
        slots = dict(constrained.get("slots") or {})
        search_plan = dict(slots.get("searchPlan") or {})
        search_plan["filter"] = {
            **dict(search_plan.get("filter") or {}),
            **filters,
        }
        slots.update(
            {
                "dateQuery": date_query,
                "temporalOriginal": date_range["temporalOriginal"],
                "searchPlan": search_plan,
            }
        )
        constrained["slots"] = slots
        return constrained

    @staticmethod
    def _resolved_source_names(result: dict) -> list[str]:
        slots = result.get("slots") or {}
        names = [
            str(slots[name_slot]).strip()
            for name_slot, _ in ResolverWorkflow.SOURCE_NAME_SLOTS.values()
            if str(slots.get(name_slot) or "").strip()
        ]
        for entity in result.get("entities") or []:
            entity_type = entity.get("entityType") or entity.get("type")
            if entity_type in ResolverWorkflow.SOURCE_NAME_SLOTS:
                name = str(entity.get("canonicalValue") or entity.get("name") or "").strip()
                if name:
                    names.append(name)
        result_intent = str(result.get("intent") or "")
        result_query_slot = ResolverWorkflow.SOURCE_QUERY_SLOTS.get(result_intent)
        if result_query_slot and result_query_slot != "residualQuery":
            query_name = str(slots.get(result_query_slot) or "").strip()
            if query_name:
                names.append(query_name)
        return list(dict.fromkeys(names))

    @staticmethod
    def _has_confident_primary_source(result: dict, expected_types: tuple[str, ...]) -> bool:
        if str(result.get("status") or "") != "resolved":
            return False
        resolved_type = str(result.get("intent") or "")
        if resolved_type not in expected_types:
            return False
        for entity in result.get("entities") or []:
            entity_type = entity.get("entityType") or entity.get("type")
            entity_id = entity.get("entityId") or entity.get("id")
            confidence = entity.get("confidence")
            if (
                entity_type == resolved_type
                and entity_id
                and isinstance(confidence, int)
                and not isinstance(confidence, bool)
                and confidence >= ResolverConstants.SECONDARY_FACET_MIN_CONFIDENCE
            ):
                return True
        return False

    @staticmethod
    def _reject_implausible_search_query_source(
        result: dict, alexa_intent: str, intent_slots: dict
    ) -> dict:
        if result.get("directDiscoveryRequest"):
            return result
        fallback = ResolverWorkflow.SEARCH_QUERY_SOURCE_INTENTS.get(alexa_intent)
        if not fallback:
            return result
        result_slots = result.get("slots") or {}
        if result.get("ambiguities") or result_slots.get("ambiguousReferences"):
            return result
        expected_intent, expected_types = fallback
        requested = ResolverSlots.resolved(intent_slots, "searchQuery")
        canonical_names = ResolverWorkflow._resolved_source_names(result)
        if not requested:
            return result
        if ResolverWorkflow._has_confident_primary_source(result, expected_types):
            return result
        verified = bool(canonical_names) and all(
            SearchFilterUtils.is_plausible_source_match(requested, canonical)
            for canonical in canonical_names
        )
        source_resolution = str(result.get("intent") or "") in ResolverWorkflow.SOURCE_NAME_SLOTS
        requires_source = expected_intent != "general"
        if verified or not canonical_names and not source_resolution and not requires_source:
            return result
        query_slot = ResolverWorkflow.SOURCE_QUERY_SLOTS[expected_intent]
        reference = {
            "phrase": requested,
            "expectedTypes": list(expected_types),
        }
        ApplicationLog.warning(
            "Hear: rejected implausible source match intent=%s canonicalCount=%s",
            alexa_intent,
            len(canonical_names),
        )
        return {
            "status": "resolved",
            "intent": expected_intent,
            "confidence": "low",
            "slots": {
                query_slot: requested,
                "residualQuery": "" if query_slot != "residualQuery" else requested,
                "unresolvedReferences": [reference],
            },
            "entities": [],
            "ambiguities": [],
        }

    @staticmethod
    def apply_alexa_constraints(result: dict, alexa_intent: str, intent_slots: dict) -> dict:
        constrained = ResolverWorkflow._apply_date_constraint(result, intent_slots)
        constrained = ResolverWorkflow._reject_implausible_search_query_source(
            constrained, alexa_intent, intent_slots
        )
        if alexa_intent not in {"WhatsTrendingIntent", "PlayRecommendationIntent"}:
            return constrained
        constrained = {
            **constrained,
            "intent": "trending",
            "semanticIntent": "trending",
        }
        slots = dict(constrained.get("slots") or {})
        search_plan = dict(slots.get("searchPlan") or {})
        search_plan["sort"] = "trending"
        slots.update(
            {
                "isRecommended": alexa_intent == "PlayRecommendationIntent",
                "sort": "trending",
                "searchPlan": search_plan,
            }
        )
        payload = dict(constrained.get("searchPayload") or {})
        payload["sort"] = "trending"
        constrained.update({"slots": slots, "searchPayload": payload})
        return constrained

    @staticmethod
    def _generic_source_resolution(
        alexa_intent: str,
        intent_slots: dict,
        raw: str | None,
    ) -> dict | None:
        values = [raw]
        values.extend(ResolverSlots.values(intent_slots))
        if any(SearchFilterUtils.is_generic_creator_request(value) for value in values):
            return ResolverWorkflow._generic_creator_resolution(alexa_intent)
        organization_kinds = [
            SearchFilterUtils.organization_request_kind(value) for value in values
        ]
        if "repair" in organization_kinds:
            return ResolverWorkflow._generic_organization_resolution(
                alexa_intent,
                repair=True,
            )
        if "generic" in organization_kinds:
            return ResolverWorkflow._generic_organization_resolution(alexa_intent)
        return None

    @staticmethod
    def _local_discovery_resolution(
        alexa_intent: str, intent_slots: dict, raw: str | None
    ) -> dict | None:
        date_query = ResolverSlots.resolved(intent_slots, "dateQuery")
        normalized_raw = SearchFilterUtils.normalize_discovery_phrase(raw)
        generic_source = ResolverWorkflow._generic_source_resolution(
            alexa_intent,
            intent_slots,
            raw,
        )
        if generic_source:
            return generic_source
        if alexa_intent == "ChooseSourceKindIntent":
            return ResolverWorkflow._source_kind_resolution(intent_slots)
        if alexa_intent == "PlayLocalIntent" or normalized_raw in DiscoveryConstants.LOCAL_HINTS:
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
            "WhatsTrendingIntent": ("topic",),
            "PlayRecommendationIntent": ("recommendationQuery",),
            "BrowseContentIntent": (),
            "PlayLocalIntent": ("cityQuery", "localQuery", "topic"),
        }
        if alexa_intent in direct and (
            not any(
                (
                    ResolverSlots.resolved(intent_slots, name)
                    for name in direct_slot_names[alexa_intent]
                )
            )
        ):
            intent_name, sort = direct[alexa_intent]
            return ResolverWorkflow._direct_discovery_result(alexa_intent, intent_name, sort)
        organization_request_kind = SearchFilterUtils.organization_request_kind(
            raw,
            organization_intent=alexa_intent in DiscoveryConstants.ORGANIZATION_INTENTS,
        )
        generic_organization = (
            alexa_intent in DiscoveryConstants.ORGANIZATION_INTENTS
            and organization_request_kind != "specific"
            or alexa_intent == "PlayContentIntent"
            and organization_request_kind in {"generic", "repair"}
        )
        if generic_organization:
            return ResolverWorkflow._generic_organization_resolution(
                alexa_intent,
                repair=organization_request_kind == "repair",
            )
        if alexa_intent in DiscoveryConstants.PUBLICATION_INTENTS:
            source = ResolverSlots.resolved(intent_slots, "publicationSourceQuery")
            if not SearchFilterUtils.is_meaningful_publication_source(source):
                return {
                    "status": "resolved",
                    "intent": "publication",
                    "alexaIntent": "publication",
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": True,
                    "needsRedirect": False,
                    "localResolved": True,
                    "slots": {
                        "publicationSourceQuery": source or "",
                        "genericPublicationRequest": True,
                        "publicationSort": ResolverSlots.resolved(
                            intent_slots, "publicationSort"
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
    def _source_kind_resolution(intent_slots: dict) -> dict | None:
        source_kind = SearchFilterUtils.normalize_discovery_phrase(
            ResolverSlots.resolved(intent_slots, "sourceKind")
        )
        publication_sort = ResolverSlots.resolved(intent_slots, "publicationSort")
        publication_source = ResolverSlots.resolved(intent_slots, "publicationSourceQuery")
        base = {
            "status": "resolved",
            "alexaRawIntent": "ChooseSourceKindIntent",
            "nlpMatchesAlexa": True,
            "needsRedirect": True,
            "localResolved": True,
            "directDiscoveryRequest": True,
        }
        if SearchFilterUtils.is_generic_creator_request(source_kind):
            return ResolverWorkflow._generic_creator_resolution("ChooseSourceKindIntent")
        if source_kind == "publication":
            if SearchFilterUtils.is_meaningful_publication_source(publication_source):
                return None
            return {
                **base,
                "intent": "publication",
                "alexaIntent": "publication",
                "slots": {
                    "publicationSourceQuery": "",
                    "publicationSort": publication_sort,
                    "genericPublicationRequest": True,
                },
            }
        if source_kind == "talking newspaper":
            return ResolverWorkflow._generic_organization_resolution(
                "ChooseSourceKindIntent"
            )
        return None

    @staticmethod
    def _generic_creator_resolution(alexa_intent: str) -> dict:
        return {
            "status": "resolved",
            "intent": "creator",
            "alexaIntent": "creator",
            "alexaRawIntent": alexa_intent,
            "nlpMatchesAlexa": alexa_intent == "ChooseSourceKindIntent",
            "needsRedirect": alexa_intent != "ChooseSourceKindIntent",
            "localResolved": True,
            "directDiscoveryRequest": True,
            "slots": {"creatorQuery": "", "genericCreatorRequest": True},
        }

    @staticmethod
    def _generic_organization_resolution(alexa_intent: str, *, repair: bool = False) -> dict:
        slots = {
            "organizationQuery": "",
            "genericOrganizationRequest": True,
        }
        if repair:
            slots["talkingNewspaperRepairCandidate"] = True
        return {
            "status": "resolved",
            "intent": "organization",
            "alexaIntent": "organization",
            "alexaRawIntent": alexa_intent,
            "nlpMatchesAlexa": alexa_intent in DiscoveryConstants.ORGANIZATION_INTENTS,
            "needsRedirect": alexa_intent not in DiscoveryConstants.ORGANIZATION_INTENTS,
            "localResolved": True,
            "directDiscoveryRequest": True,
            "slots": slots,
        }

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
                "isLocal": intent_name == "local",
                "isRecommended": alexa_intent == "PlayRecommendationIntent",
            },
            "slots": {
                "residualQuery": "",
                "isLocal": intent_name == "local",
                "isRecommended": alexa_intent == "PlayRecommendationIntent",
                "sort": sort,
            },
        }
