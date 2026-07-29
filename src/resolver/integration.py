from __future__ import annotations

from src.resolver.engine import resolver
from src.resolver.payload import build_hear_payload
from src.services.semantic_routing import SEARCH_ROUTE_NAMES, semantic_intent_router

SEARCH_INTENTS = {
    "PlayContentIntent", "PlayByCreatorIntent", "PlayByOrganizationIntent",
    "BrowseContentIntent", "BrowseByCategoryIntent", "WhatsTrendingIntent",
    "PlayLocalIntent", "PlayRecommendationIntent",
}


def resolve_for_alexa(utterance: str, alexa_user_id: str = "", timezone: str = "Europe/London") -> dict:
    plan = resolver.resolve(utterance, alexa_user_id, timezone)
    deterministic_intent = (
        "local" if plan.is_local else
        "category" if plan.category_slugs else
        "creator" if plan.creator_ids else
        "organization" if plan.organization_ids else ""
    )
    has_deterministic_evidence = bool(
        plan.entities
        or plan.unresolved_references
        or plan.ambiguous_references
    )
    semantic = (
        None
        if has_deterministic_evidence
        else semantic_intent_router.route(utterance, SEARCH_ROUTE_NAMES)
    )
    intent = deterministic_intent or (semantic.route if semantic else "general")
    slots = {
        "residualQuery": plan.query,
        "latest": plan.sort == "latest",
        "isLocal": plan.is_local,
        "isRecommended": plan.is_recommended,
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
