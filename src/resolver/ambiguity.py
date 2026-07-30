from __future__ import annotations

import re

from rapidfuzz import fuzz

from src.resolver.normalize import normalize_utterance
from src.utils.speech import resolved_search_request_label

_FILTER_KEYS = {
    "creator": "creatorIds",
    "organization": "organizationIds",
    "publication": "publicationIds",
}


def resolve_ambiguity_follow_up(utterance: str, context: dict) -> dict:
    phrase = normalize_utterance(utterance)
    candidates = list(context.get("candidates") or [])
    phrase_tokens = set(re.findall(r"[a-z0-9]+", phrase))
    containing = []
    ranked = []
    for candidate in candidates:
        name = normalize_utterance(candidate.get("name"))
        name_tokens = set(re.findall(r"[a-z0-9]+", name))
        if phrase_tokens and phrase_tokens <= name_tokens:
            containing.append(candidate)
        ranked.append((fuzz.token_set_ratio(phrase, name), candidate))
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
        return {
            "status": "ambiguous",
            "intent": str(context.get("intent") or "general"),
            "ambiguities": [{"phrase": phrase, "candidates": narrowed}],
            "slots": {"ambiguousReferences": [{
                "phrase": phrase,
                "candidates": narrowed,
            }]},
            "alternatives": narrowed,
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
    }
