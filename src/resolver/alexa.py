from __future__ import annotations

import re

from rapidfuzz import fuzz
from rapidfuzz.distance import DamerauLevenshtein

from src.resolver.search import resolver
from src.resolver.normalization import normalize_utterance
from src.resolver.models import SearchPlan
from src.utils.search_query import normalize_search_query
from src.utils.speech import resolved_search_request_label

SEARCH_INTENTS = {
    "PlayContentIntent", "PlayByCreatorIntent", "PlayByOrganizationIntent",
    "PlayPublicationIntent",
    "BrowseContentIntent", "BrowseByCategoryIntent", "WhatsTrendingIntent",
    "PlayLocalIntent", "PlayRecommendationIntent",
}

_FILTER_KEYS = {
    "creator": "creatorIds",
    "organization": "organizationIds",
    "publication": "publicationIds",
}

def resolve_ambiguity_follow_up(utterance: str, context: dict) -> dict:
    """Resolve which ambiguity candidate the user selected."""
    phrase = normalize_utterance(utterance)
    candidates = list(context.get("candidates") or [])
    ambiguity_contexts = list((context.get("slots") or {}).get("ambiguousReferences") or [])
    original_phrase = normalize_utterance(
        ambiguity_contexts[0].get("phrase")
        if ambiguity_contexts and isinstance(ambiguity_contexts[0], dict)
        else ""
    )

    if original_phrase and phrase == original_phrase:
        return {
            "status": "ambiguous",
            "intent": str(context.get("intent") or "general"),
            "ambiguities": [{"phrase": original_phrase, "candidates": candidates}],
            "slots": {"ambiguousReferences": [{
                "phrase": original_phrase,
                "candidates": candidates,
            }]},
            "alternatives": candidates,
        }

    phrase_tokens = set(re.findall(r"[a-z0-9]+", phrase))
    containing = []
    ranked = []
    for candidate in candidates:
        name = normalize_utterance(candidate.get("name"))
        name_tokens = set(re.findall(r"[a-z0-9]+", name))
        if phrase_tokens and phrase_tokens <= name_tokens:
            containing.append(candidate)
        token_scores = [
            fuzz.ratio(phrase, token)
            for token in name_tokens
            if len(token) >= 3
        ]
        score = max([fuzz.token_set_ratio(phrase, name), *token_scores])
        ranked.append((score, candidate))

    narrowed = containing or [
        item[1] for item in sorted(ranked, key=lambda item: item[0], reverse=True)[:3]
    ]

    winner = None
    if len(narrowed) == 1:
        winner = narrowed[0]
    elif ranked:
        ranked.sort(key=lambda item: item[0], reverse=True)
        if ranked[0][0] >= 88 and (
            len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 6
        ):
            winner = ranked[0][1]

    if winner is None:
        best_score = max((item[0] for item in ranked), default=0)
        return {
            "status": "ambiguous",
            "intent": str(context.get("intent") or "general"),
            "ambiguities": [{"phrase": phrase, "candidates": narrowed}],
            "slots": {"ambiguousReferences": [{
                "phrase": phrase,
                "candidates": narrowed,
            }]},
            "alternatives": narrowed,
            "followUpMatched": best_score >= 60,
        }

    entity_type = str(winner.get("type") or "")
    filter_key = _FILTER_KEYS.get(entity_type)
    if not filter_key or not winner.get("id"):
        return {"status": "error", "error": "invalid_ambiguity_candidate"}

    payload = dict(context.get("searchPayload") or {})
    filters = dict(payload.get("filter") or {})
    filters[filter_key] = [winner["id"]]
    payload["filter"] = filters

    slots = dict(context.get("slots") or {})
    slots[filter_key] = [winner["id"]]
    slots[f"{entity_type}Name"] = winner["name"]
    slots["searchPlan"] = payload
    slots["ambiguousReferences"] = []

    return {
        "status": "resolved",
        "intent": entity_type,
        "confidence": 1.0,
        "entities": [{
            "type": entity_type,
            "id": winner["id"],
            "canonicalValue": winner["name"],
            "originalText": phrase,
            "confidence": 1.0,
            "method": "ambiguity-follow-up",
        }],
        "slots": slots,
        "searchPayload": payload,
        "confirmationLabel": resolved_search_request_label(slots, winner["name"]),
        "alternatives": [],
        "ambiguities": [],
        "unresolvedReferences": [],
        "ambiguityResolution": True,
    }


class AlexaResolverService:
    """Single Alexa-facing interface for resolution and Hear payload creation."""

    def resolve(
        self,
        utterance: str,
        alexa_user_id: str = "",
        timezone: str = "Europe/London",
        *,
        alexa_intent: str = "",
        taxonomy_view=None,
    ) -> dict:
        plan = resolver.resolve(
            utterance,
            alexa_user_id,
            timezone,
            taxonomy_view=taxonomy_view,
        )
        if alexa_intent == "PlayPublicationIntent":
            plan.is_publication = True
            if plan.sort == "relevance":
                plan.sort = "trending"
        deterministic_intent = (
            "category" if plan.category_slugs or plan.tags else
            "local" if plan.is_local or plan.city else
            "creator" if plan.creator_ids else
            "organization" if plan.organization_ids else
            "publication" if plan.is_publication or plan.publication_ids else ""
        )
        intent = deterministic_intent or "general"
        slots = {
            "residualQuery": plan.query,
            "latest": plan.sort == "latest",
            "isLocal": plan.is_local,
            "isRecommended": plan.is_recommended,
            "isPublication": plan.is_publication,
            "searchPlan": self.build_payload(plan),
            "unresolvedReferences": [
                {
                    "relation": item.relation,
                    "phrase": item.phrase,
                    "expectedTypes": list(item.expected_types),
                }
                for item in plan.unresolved_references
            ],
            "ambiguousReferences": [
                {
                    "phrase": item.phrase,
                    "candidates": [
                        {
                            "type": candidate.entity_type,
                            "id": candidate.entity_id,
                            "name": candidate.canonical_value,
                        }
                        for candidate in item.candidates
                    ],
                }
                for item in plan.ambiguous_references
            ],
        }
        if plan.temporal:
            slots["temporalOriginal"] = plan.temporal.original_text
        if plan.category_slugs:
            slots["category"] = plan.category_slugs[0]
        if plan.tags:
            slots["tags"] = list(plan.tags)
        if plan.creator_ids:
            slots["creatorIds"] = plan.creator_ids
            slots["creatorName"] = next(
                (
                    entity.canonical_value
                    for entity in plan.entities
                    if entity.entity_type == "creator"
                ),
                None,
            )
        if plan.organization_ids:
            slots["organizationIds"] = plan.organization_ids
            slots["organizationName"] = next(
                (
                    entity.canonical_value
                    for entity in plan.entities
                    if entity.entity_type == "organization"
                ),
                None,
            )
        if plan.publication_ids:
            slots["publicationIds"] = plan.publication_ids
            slots["publicationName"] = next(
                (
                    entity.canonical_value
                    for entity in plan.entities
                    if entity.entity_type == "publication"
                ),
                None,
            )
        if plan.city:
            slots["city"] = plan.city
        if plan.latitude is not None:
            slots["latitude"] = plan.latitude
        if plan.longitude is not None:
            slots["longitude"] = plan.longitude
        return {
            "intent": intent,
            "confidence": (
                "high"
                if deterministic_intent and plan.confidence >= 0.92
                else "medium"
            ),
            "slots": slots,
            "searchPlan": plan,
        }

    def resolve_organization_follow_up(
        self,
        utterance: str,
        alexa_user_id: str = "",
        timezone: str = "Europe/London",
        *,
        taxonomy_view=None,
    ) -> dict:
        """Resolve a source name after Alexa explicitly requested one.

        Short acronym typo recovery is deliberately restricted to this prompt
        context and requires one unique taxonomy-owned organisation.
        """
        phrase = normalize_utterance(utterance)
        letter_tokens = phrase.split()
        if 2 <= len(letter_tokens) <= 5 and all(
            len(token) == 1 and token.isalnum() for token in letter_tokens
        ):
            phrase = "".join(letter_tokens)

        result = self.resolve(
            f"play from {phrase}",
            alexa_user_id,
            timezone,
            taxonomy_view=taxonomy_view,
        )
        if result["slots"].get("organizationIds"):
            return result

        if not phrase or " " in phrase or not 2 <= len(phrase) <= 5:
            return result

        matches = {}
        snapshot = taxonomy_view or resolver.taxonomy.snapshot
        alias_items = (
            snapshot.fuzzy_alias_items("organization")
            if hasattr(snapshot, "fuzzy_alias_items")
            else snapshot.fuzzy.get("organization", {}).items()
        )
        for alias, record in alias_items:
            if not 2 <= len(alias) <= 5:
                continue
            if DamerauLevenshtein.distance(phrase, alias) > 1:
                continue
            identity = record.entity_id or record.canonical
            matches[identity] = record
        if len(matches) != 1:
            return result

        identity, record = next(iter(matches.items()))
        result["intent"] = "organization"
        result["confidence"] = "high"
        result["slots"].update({
            "organizationIds": [identity],
            "organizationName": record.canonical,
            "residualQuery": "",
            "unresolvedReferences": [],
        })
        return result

    @staticmethod
    def build_payload(plan: SearchPlan) -> dict:
        payload = {
            "isLocal": plan.is_local,
            "isRecommended": plan.is_recommended,
            "limit": plan.limit,
            "page": plan.page,
            "query": normalize_search_query(plan.query),
        }
        if plan.alexa_user_id:
            payload["alexaUserId"] = plan.alexa_user_id
        if plan.sort != "relevance":
            payload["sort"] = plan.sort
        elif plan.is_local:
            payload["sort"] = "nearest"
        filters = {}
        if plan.is_publication:
            filters["isPublication"] = True
        for key, value in (
            ("categorySlugs", plan.category_slugs),
            ("tags", plan.tags),
            ("creatorIds", plan.creator_ids),
            ("organizationIds", plan.organization_ids),
            ("publicationIds", plan.publication_ids),
        ):
            if value:
                filters[key] = value
        for key, value in (
            ("city", plan.city),
            ("latitude", plan.latitude),
            ("longitude", plan.longitude),
            ("countryCode", plan.country_code),
        ):
            if value is not None and value != "":
                filters[key] = value
        if plan.temporal:
            if plan.temporal.start_timestamp is not None:
                filters["publishedFrom"] = plan.temporal.start_timestamp
            if plan.temporal.end_timestamp is not None:
                filters["publishedTo"] = plan.temporal.end_timestamp
        if filters:
            payload["filter"] = filters
        return payload


alexa_resolver = AlexaResolverService()
