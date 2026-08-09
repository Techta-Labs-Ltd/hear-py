from __future__ import annotations

import re
from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractRequestInterceptor
from src.services.resolution import build_pending_resolution

from src.utils.speech import resolved_search_request_label, ssml
from src.middleware.dialog_validation import DIALOG_VALIDATION_FAILURE
from src.utils.discovery_request import (
    is_reserved_discovery_phrase,
    normalize_discovery_phrase,
)

_RESOLVED_DISCOVERY_INTENTS: set[str] = {
    "local", "creator", "organization", "publication", "category", "general",
    "trending", "browse", "following", "search",
}

_ALEXA_DISCOVERY_INTENTS: set[str] = {
    "PlayContentIntent", "PlayByCreatorIntent", "PlayByOrganizationIntent",
    "PlayPublicationIntent", "BrowseContentIntent", "BrowseByCategoryIntent",
    "WhatsTrendingIntent", "PlayLocalIntent", "PlayRecommendationIntent",
}

_DISCOVERY_QUERY_SLOTS: dict[str, str] = {
    "PlayContentIntent": "topic",
    "PlayByCreatorIntent": "creatorQuery",
    "PlayByOrganizationIntent": "organizationQuery",
    "PlayPublicationIntent": "publicationSourceQuery",
    "PlayLocalIntent": "localQuery",
    "PlayRecommendationIntent": "recommendationQuery",
}

def _has_meaningful_general_request(nlp: dict, raw: str | None) -> bool:
    slots = nlp.get("slots") or {}
    payload = nlp.get("searchPayload") or slots.get("searchPlan") or {}
    filters = payload.get("filter") or {}
    query = normalize_discovery_phrase(
        payload.get("query")
        or slots.get("residualQuery")
        or slots.get("topic")
        or slots.get("query")
        or raw
    )
    return bool(filters) or not is_reserved_discovery_phrase(query)


def _has_pending_ambiguity(nlp: dict | None) -> bool:
    if not isinstance(nlp, dict):
        return False
    slots = nlp.get("slots") or {}
    return bool(
        nlp.get("ambiguities")
        or slots.get("ambiguousReferences")
    )


def _requires_discovery_clarification(nlp: dict, raw: str | None) -> bool:
    intent = str(nlp.get("intent") or "")
    slots = nlp.get("slots") or {}
    if intent == "general":
        return not _has_meaningful_general_request(nlp, raw)
    if intent == "creator":
        return not bool(slots.get("creatorIds") or slots.get("creatorName"))
    if intent == "organization":
        return not bool(slots.get("organizationIds") or slots.get("organizationName"))
    if intent == "publication":
        return not bool(
            slots.get("publicationIds")
            or slots.get("publicationName")
            or slots.get("publicationSourceQuery")
        )
    if intent == "category":
        return not bool(slots.get("category") or slots.get("tags") or slots.get("residualQuery"))
    return False


def _build_confirmation_speech(nlp: dict | None) -> str | None:
    if not nlp or not nlp.get("intent"):
        return None
    intent = nlp["intent"]
    slots = nlp.get("slots") or {}
    if nlp.get("confirmationLabel"):
        return str(nlp["confirmationLabel"])
    category = slots.get("category") or slots.get("topic") or None
    creator = (
        slots.get("creatorName") or slots.get("creatorQuery")
        or slots.get("creator") or None
    )
    org = (
        slots.get("organizationName") or slots.get("organizationQuery")
        or slots.get("organization") or None
    )
    publication_source = slots.get("publicationSourceQuery") or None
    city = slots.get("city") or slots.get("placeName") or None
    residual = str(slots.get("residualQuery", "")).strip() or ""

    if intent == "organization" and org:
        return resolved_search_request_label(slots, org)
    if intent == "creator" and creator:
        return resolved_search_request_label(slots, creator)
    if intent == "publication":
        return resolved_search_request_label(slots, publication_source)
    if intent in {"category", "general"} and (
        category or slots.get("tags") or residual
    ):
        return resolved_search_request_label(slots)

    if intent == "local":
        prefix = "the latest " if slots.get("latest") else ""
        if category and city:
            return prefix + category + " nearest to " + city
        if city:
            return prefix + "from " + city if prefix else "content from " + city
        if category:
            return prefix + category + " in your community"
        return "tracks near you"

    if intent == "trending":
        tr = "what\u2019s trending"
        if category:
            tr += " in " + category
        if city:
            tr += " near " + city
        return tr if (category or city) else "what\u2019s trending right now"

    if intent == "browse":
        if category and city:
            return "new " + category + " near " + city
        if category:
            return "new in " + category
        if city:
            return "what\u2019s new near " + city
        return "browse content"

    if intent == "following":
        return category + " from your followed creators" if category else "your followed creators"

    parts: list[str] = []
    if intent == "creator":
        if creator:
            parts.append(creator)
        if category:
            parts.append(category)
    elif intent == "organization":
        if org:
            parts.append(org)
        if category:
            parts.append(category)
    else:
        if category and intent != "category":
            parts.append(category)
        if creator:
            parts.append(creator)
        elif org:
            parts.append(org)

    if parts:
        primary = parts[0]
        if slots.get("latest") and not re.match(r"^(?:the )?latest\b", primary, re.I):
            primary = "the latest " + primary
        if intent in ("creator", "organization"):
            desc_parts = parts[1:]
            if residual:
                desc_parts.append(residual)
            if desc_parts:
                desc_str = ", ".join(desc_parts)
                return (
                    "the latest " + desc_str + " from " + parts[0]
                    if slots.get("latest")
                    else desc_str + " from " + parts[0]
                )
            return primary
        return primary + " by " + " ".join(parts[1:]) if len(parts) > 1 else primary

    if intent == "category":
        cat = category or slots.get("topic") or "that"
        return cat + " from " + residual if residual else cat

    return residual or slots.get("topic") or slots.get("query") or None


def _extract_raw_utterance_from_attrs(handler_input) -> str | None:
    try:
        slots = handler_input.request_envelope.request.intent.get("slots")
    except Exception:
        return None
    if not slots:
        return None
    try:
        alexa_intent = handler_input.request_envelope.request.intent.name
    except Exception:
        return None

    if alexa_intent == "PlayLatestContentIntent":
        parts = ["latest"]
        for slot_name in ("topic", "format"):
            slot = slots.get(slot_name)
            value = getattr(slot, "value", None) if slot else None
            if value and str(value).strip():
                parts.append(str(value).strip())
        return " ".join(parts) or None
    if alexa_intent == "PlayByCreatorIntent":
        priority = ["creatorQuery", "topic", "organizationQuery", "listPickPhrase", "category", "feedbackPhrase"]
    elif alexa_intent == "PlayByOrganizationIntent":
        priority = ["organizationQuery", "topic", "creatorQuery", "listPickPhrase", "category", "feedbackPhrase"]
    elif alexa_intent == "PlayPublicationIntent":
        priority = ["publicationSourceQuery", "topic", "creatorQuery", "organizationQuery", "listPickPhrase", "category"]
    elif alexa_intent == "BrowseByCategoryIntent":
        priority = ["category", "topic", "creatorQuery", "organizationQuery", "listPickPhrase", "feedbackPhrase"]
    else:
        priority = ["topic", "creatorQuery", "organizationQuery", "listPickPhrase", "category", "feedbackPhrase"]

    for slot_name in priority:
        slot = slots.get(slot_name)
        value = getattr(slot, "value", None) if slot else None
        if value and str(value).strip():
            return str(value).strip()
    return None


def _build_search_params(nlp: dict | None) -> dict | None:
    if not nlp or not nlp.get("intent"):
        return None
    slots = nlp.get("slots") or {}
    parts: list[str] = []
    if slots.get("category") or slots.get("topic"):
        parts.append(slots.get("category") or slots.get("topic"))
    if slots.get("creatorQuery") or slots.get("creator"):
        parts.append(slots.get("creatorQuery") or slots.get("creator"))
    if slots.get("organizationQuery") or slots.get("organization"):
        parts.append(slots.get("organizationQuery") or slots.get("organization"))
    if slots.get("publicationSourceQuery"):
        parts.append(slots.get("publicationSourceQuery"))
    if slots.get("city") or slots.get("placeName"):
        parts.append(slots.get("city") or slots.get("placeName"))
    if slots.get("residualQuery"):
        parts.append(slots.get("residualQuery"))
    query = " ".join(parts) if parts else (slots.get("topic") or "")
    return {
        "intent": nlp["intent"],
        "query": query,
        "slots": slots,
        "resolution": build_pending_resolution(
            nlp,
            nlp.get("confirmationLabel") or "",
        ),
    }


class ConfirmationMiddleware(AbstractRequestInterceptor):
    def process(self, handler_input) -> None:
        if handler_input.attributes_manager.request_attributes.get(
            DIALOG_VALIDATION_FAILURE
        ):
            return
        try:
            request_type = handler_input.request_envelope.request.type
        except Exception:
            return
        if request_type != "IntentRequest":
            return

        try:
            alexa_intent = handler_input.request_envelope.request.intent.name
        except Exception:
            return
        if not alexa_intent:
            return

        attrs = handler_input.attributes_manager.request_attributes
        nlp = attrs.get("_nlp")
        if not nlp or not nlp.get("intent"):
            return
        if nlp.get("status") and nlp.get("status") != "resolved":
            return
        if nlp["intent"] == "unclear":
            return
        if nlp["intent"] not in _RESOLVED_DISCOVERY_INTENTS:
            return

        # The resolver contract can report status=resolved while still
        # returning ambiguity candidates. Candidate selection must happen
        # before confirmation or generic-query validation.
        if _has_pending_ambiguity(nlp):
            attrs.pop("_pendingConfirmation", None)
            attrs.pop("_resolverClarification", None)
            handler_input.attributes_manager.request_attributes = attrs
            return

        if alexa_intent == "WhatsTrendingIntent" and nlp.get("intent") == "trending":
            attrs.pop("_pendingConfirmation", None)
            attrs.pop("_resolverClarification", None)
            handler_input.attributes_manager.request_attributes = attrs
            return

        raw = _extract_raw_utterance_from_attrs(handler_input)
        if (
            nlp.get("intent") == "creator"
            and (nlp.get("slots") or {}).get("genericCreatorRequest")
        ):
            # The creator handler owns the prompt and follow-up state.
            attrs.pop("_pendingConfirmation", None)
            attrs.pop("_resolverClarification", None)
            handler_input.attributes_manager.request_attributes = attrs
            return
        if (
            nlp.get("intent") == "organization"
            and (nlp.get("slots") or {}).get("genericOrganizationRequest")
        ):
            # The organization handler owns this prompt because it also
            # persists awaitingOrganizationName for the follow-up turn.
            attrs.pop("_pendingConfirmation", None)
            attrs.pop("_resolverClarification", None)
            handler_input.attributes_manager.request_attributes = attrs
            return
        if nlp.get("publicationSourceRequired"):
            attrs["_resolverClarification"] = {
                "speech": "Which publication, creator, or organization would you like?",
                "reprompt": "Please say the name of a publication, creator, or organization.",
                "elicitSlot": "publicationSourceQuery",
            }
            attrs.pop("_pendingConfirmation", None)
            handler_input.attributes_manager.request_attributes = attrs
            return
        if _requires_discovery_clarification(nlp, raw):
            attrs["_resolverClarification"] = {
                "speech": "What would you like me to play? You can name a topic, creator, publication, or talking newspaper.",
                "reprompt": "What would you like to play?",
                "elicitSlot": (
                    _DISCOVERY_QUERY_SLOTS.get(alexa_intent)
                    if not raw
                    else None
                ),
            }
            attrs.pop("_pendingConfirmation", None)
            handler_input.attributes_manager.request_attributes = attrs
            return

        confirm_text = _build_confirmation_speech(nlp)
        if not confirm_text:
            attrs["_resolverClarification"] = {
                "speech": "What would you like me to play? You can name a topic, creator, publication, or talking newspaper.",
                "reprompt": "What would you like to play?",
                "elicitSlot": (
                    _DISCOVERY_QUERY_SLOTS.get(alexa_intent)
                    if not raw
                    else None
                ),
            }
            attrs.pop("_pendingConfirmation", None)
            handler_input.attributes_manager.request_attributes = attrs
            return

        search_params = _build_search_params(nlp) or {}
        search_params["confirmText"] = confirm_text
        if search_params.get("resolution"):
            search_params["resolution"]["confirmationLabel"] = confirm_text

        alternatives = nlp.get("alternatives") or []
        if not alternatives and raw:
            alternatives = []
        search_params["alternatives"] = alternatives
        search_params["ambiguityResolution"] = bool(nlp.get("ambiguityResolution"))
        if search_params["ambiguityResolution"]:
            search_params["ambiguityCandidateName"] = next((
                str(entity.get("canonicalValue") or "").strip()
                for entity in nlp.get("entities") or []
                if entity.get("canonicalValue")
            ), confirm_text)

        attrs["_pendingConfirmation"] = search_params
        handler_input.attributes_manager.request_attributes = attrs


class SearchConfirmationGateHandler(AbstractRequestHandler):
    """Prevent discovery handlers from bypassing resolver confirmation."""

    def can_handle(self, handler_input) -> bool:
        try:
            request = handler_input.request_envelope.request
            alexa_intent = request.intent.name
        except Exception:
            return False
        if request.type != "IntentRequest" or alexa_intent not in _ALEXA_DISCOVERY_INTENTS:
            return False
        attrs = handler_input.attributes_manager.request_attributes
        if attrs.get(DIALOG_VALIDATION_FAILURE):
            return False
        nlp = attrs.get("_nlp")
        if not isinstance(nlp, dict) or not nlp.get("intent"):
            return True
        if nlp.get("intent") in {"unclear", "resolver_unavailable"}:
            return False
        if nlp.get("status") and nlp.get("status") != "resolved":
            return False
        if _has_pending_ambiguity(nlp):
            return False
        if alexa_intent == "WhatsTrendingIntent" and nlp.get("intent") == "trending":
            return False
        nlp_slots = nlp.get("slots") or {}
        if (
            nlp_slots.get("genericCreatorRequest")
            or nlp_slots.get("genericOrganizationRequest")
        ):
            # These are explicit incomplete requests, not unconfirmed
            # searches. Their discovery handlers own the name prompt.
            return False
        return (
            nlp.get("intent") in _RESOLVED_DISCOVERY_INTENTS
            and not attrs.get("_pendingConfirmation")
            and not attrs.get("_resolverClarification")
        )

    def handle(self, handler_input):
        return handler_input.response_builder \
            .speak(ssml("I couldn't safely confirm that search. Please say what you'd like to hear again.")) \
            .reprompt(ssml("Name a topic, creator, publication, or talking newspaper.")) \
            .set_should_end_session(False) \
            .response
