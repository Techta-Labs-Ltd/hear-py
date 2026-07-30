from __future__ import annotations

import re
from ask_sdk_core.dispatch_components import AbstractRequestInterceptor
from src.services.resolution_state import build_pending_resolution
from src.utils.speech import resolved_search_request_label

_CONFIRMABLE: set[str] = {
    "local", "creator", "organization", "category", "general",
}


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
    city = slots.get("city") or slots.get("placeName") or None
    residual = str(slots.get("residualQuery", "")).strip() or ""

    if intent == "organization" and org:
        return resolved_search_request_label(slots, org)
    if intent == "creator" and creator:
        return resolved_search_request_label(slots, creator)
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

    if alexa_intent == "PlayByCreatorIntent":
        priority = ["creatorQuery", "topic", "organizationQuery", "listPickPhrase", "category", "feedbackPhrase"]
    elif alexa_intent == "PlayByOrganizationIntent":
        priority = ["organizationQuery", "topic", "creatorQuery", "listPickPhrase", "category", "feedbackPhrase"]
    elif alexa_intent == "BrowseByCategoryIntent":
        priority = ["category", "topic", "creatorQuery", "organizationQuery", "listPickPhrase", "feedbackPhrase"]
    else:
        priority = ["topic", "creatorQuery", "organizationQuery", "listPickPhrase", "category", "feedbackPhrase"]

    for slot_name in priority:
        slot = slots.get(slot_name)
        if slot and slot.value and str(slot.value).strip():
            return str(slot.value).strip()
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
    if slots.get("city") or slots.get("placeName"):
        parts.append(slots.get("city") or slots.get("placeName"))
    if slots.get("residualQuery"):
        parts.append(slots.get("residualQuery"))
    query = " ".join(parts) if parts else (slots.get("topic") or "")
    payload = nlp.get("searchPayload") or slots.get("searchPlan") or {}
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
        if nlp["intent"] not in _CONFIRMABLE:
            return

        confirm_text = _build_confirmation_speech(nlp)
        if not confirm_text:
            return

        search_params = _build_search_params(nlp) or {}
        search_params["confirmText"] = confirm_text
        if search_params.get("resolution"):
            search_params["resolution"]["confirmationLabel"] = confirm_text

        raw = _extract_raw_utterance_from_attrs(handler_input)
        alternatives = nlp.get("alternatives") or []
        if not alternatives and raw:
            alternatives = []
        search_params["alternatives"] = alternatives

        attrs["_pendingConfirmation"] = search_params
        handler_input.attributes_manager.request_attributes = attrs
