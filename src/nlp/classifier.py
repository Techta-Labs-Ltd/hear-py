from __future__ import annotations

from src.nlp.patterns import (
    BROWSE_HINTS,
    FEEDBACK_ENJOYED_HINTS,
    FEEDBACK_NOT_ENJOYED_HINTS,
    FEEDBACK_SKIP_HINTS,
    FEEDBACK_SOMEWHAT_HINTS,
    FOLLOWING_HINTS,
    LOCAL_HINTS,
    MORE_HINTS,
    TRENDING_HINTS,
)
from src.resolver.engine import resolver
from src.resolver.normalize import normalize_utterance
from src.services.semantic_routing import semantic_intent_router


def _normalized_hints(values: set[str]) -> set[str]:
    return {normalize_utterance(value) for value in values}


INTENT_HINTS = (
    ("feedback_not_enjoyed", _normalized_hints(FEEDBACK_NOT_ENJOYED_HINTS)),
    ("feedback_somewhat", _normalized_hints(FEEDBACK_SOMEWHAT_HINTS)),
    ("feedback_enjoyed", _normalized_hints(FEEDBACK_ENJOYED_HINTS)),
    ("feedback_skip", _normalized_hints(FEEDBACK_SKIP_HINTS)),
    ("show_more", _normalized_hints(MORE_HINTS)),
    ("following", _normalized_hints(FOLLOWING_HINTS)),
    ("trending", _normalized_hints(TRENDING_HINTS)),
    ("local", _normalized_hints(LOCAL_HINTS)),
    ("browse", _normalized_hints(BROWSE_HINTS)),
)

def classify_utterance(raw: str | None) -> dict:
    normalized = normalize_utterance(raw)
    if not normalized:
        return {"intent": "general", "confidence": "low", "slots": {}}

    for intent, hints in INTENT_HINTS:
        if normalized in hints:
            return {"intent": intent, "confidence": "high", "slots": {}}

    plan = resolver.resolve(normalized)
    slots = {
        "latest": plan.sort == "latest",
        "isPublication": plan.is_publication,
        "residualQuery": plan.query,
    }
    if plan.category_slugs:
        slots["category"] = plan.category_slugs[0]
    if plan.city:
        slots["city"] = plan.city
        slots["placeName"] = plan.city

    intent = (
        "local" if plan.is_local else
        "category" if plan.category_slugs else
        "publication" if plan.is_publication else
        ""
    )
    has_deterministic_evidence = bool(
        plan.entities
        or plan.unresolved_references
        or plan.ambiguous_references
    )
    semantic = (
        None
        if intent or has_deterministic_evidence
        else semantic_intent_router.route(normalized)
    )
    intent = intent or (semantic.route if semantic else "general")
    return {
        "intent": intent,
        "confidence": (
            "high"
            if plan.is_local or plan.category_slugs or plan.is_publication
            else "high"
            if semantic and semantic.score >= 0.82
            else "medium"
        ),
        "slots": slots,
        "semanticRoute": semantic.route if semantic else None,
        "semanticScore": semantic.score if semantic else None,
    }
