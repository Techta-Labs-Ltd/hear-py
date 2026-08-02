from __future__ import annotations

from rapidfuzz.distance import DamerauLevenshtein

from src.resolver.engine import resolver
from src.resolver.normalize import normalize_utterance
from src.resolver.payload import build_hear_payload
from src.services.semantic_routing import SEARCH_ROUTE_NAMES, semantic_intent_router

SEARCH_INTENTS = {
    "PlayContentIntent", "PlayByCreatorIntent", "PlayByOrganizationIntent",
    "PlayPublicationIntent",
    "BrowseContentIntent", "BrowseByCategoryIntent", "WhatsTrendingIntent",
    "PlayLocalIntent", "PlayRecommendationIntent",
}


def resolve_for_alexa(
    utterance: str,
    alexa_user_id: str = "",
    timezone: str = "Europe/London",
    *,
    alexa_intent: str = "",
) -> dict:
    plan = resolver.resolve(utterance, alexa_user_id, timezone)
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
    has_deterministic_evidence = bool(
        plan.entities
        or plan.unresolved_references
        or plan.ambiguous_references
    )
    semantic = (
        None
        if deterministic_intent or has_deterministic_evidence
        else semantic_intent_router.route(utterance, SEARCH_ROUTE_NAMES)
    )
    intent = deterministic_intent or (semantic.route if semantic else "general")
    slots = {
        "residualQuery": plan.query,
        "latest": plan.sort == "latest",
        "isLocal": plan.is_local,
        "isRecommended": plan.is_recommended,
        "isPublication": plan.is_publication,
        "searchPlan": build_hear_payload(plan),
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
        "semanticRoute": semantic.route if semantic else None,
        "semanticScore": semantic.score if semantic else None,
    }
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
    return {
        "intent": intent,
        "confidence": (
            "high"
            if deterministic_intent and plan.confidence >= 0.92
            else "high"
            if semantic and semantic.score >= 0.82
            else "medium"
        ),
        "slots": slots,
        "searchPlan": plan,
    }


def resolve_organization_follow_up(
    utterance: str,
    alexa_user_id: str = "",
    timezone: str = "Europe/London",
) -> dict:
    """Resolve a source name after Alexa explicitly requested one.

    Short acronym typo recovery is deliberately restricted to this prompt
    context and requires one unique taxonomy-owned organisation.
    """
    phrase = normalize_utterance(utterance)
    # Alexa commonly transcribes spoken initialisms as "y. t. n.".  The
    # normalizer deliberately removes punctuation, so compact a sequence of
    # single-letter tokens before both exact and fuzzy organization matching.
    letter_tokens = phrase.split()
    if 2 <= len(letter_tokens) <= 5 and all(
        len(token) == 1 and token.isalnum() for token in letter_tokens
    ):
        phrase = "".join(letter_tokens)

    result = resolve_for_alexa(
        f"play from {phrase}",
        alexa_user_id,
        timezone,
    )
    if result["slots"].get("organizationIds"):
        return result

    if not phrase or " " in phrase or not 2 <= len(phrase) <= 5:
        return result

    matches = {}
    for alias, record in resolver.taxonomy.snapshot.fuzzy.get(
        "organization", {}
    ).items():
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
