from __future__ import annotations

import logging
from typing import Any, Dict

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.services.resolver_client import ResolverUnavailable, resolve_utterance

logger = logging.getLogger(__name__)

CONTENT_INTENTS = {
    "PlayContentIntent", "PlayByCreatorIntent", "PlayByOrganizationIntent",
    "BrowseContentIntent", "WhatsTrendingIntent",
}
SEARCH_INTENTS = CONTENT_INTENTS | {
    "BrowseByCategoryIntent", "PlayLocalIntent", "PlayRecommendationIntent",
}

NO_UTTERANCE_OK = {"BrowseContentIntent", "WhatsTrendingIntent"}

STRONG_INTENTS = {"creator", "organization", "category", "local"}

SLOT_PRIORITY = ["creatorQuery", "organizationQuery", "topic", "category",
                 "listPickPhrase", "query"]


def _slot_utterance(intent: Dict[str, Any]) -> str:
    """Extract a representative utterance from the intent's slot values."""
    if not intent or not intent.get("slots"):
        return ""
    slots = intent.get("slots", {})
    vals = []
    for name in SLOT_PRIORITY:
        s = slots.get(name)
        if s and s.get("value") and str(s["value"]).strip():
            vals.append(str(s["value"]).strip())
    if not vals:
        for name, s in slots.items():
            if s and s.get("value") and str(s["value"]).strip():
                vals.append(str(s["value"]).strip())
    return " ".join(vals).strip()


def _reply(can_fulfill: str, intent: Dict[str, Any]) -> Dict[str, Any]:
    """Build a CanFulfill response dict."""
    slots = {}
    if intent and intent.get("slots"):
        understood = "YES" if can_fulfill == "YES" else "MAYBE"
        for name in intent["slots"]:
            s = intent["slots"][name]
            has_val = s and s.get("value") and str(s["value"]).strip()
            slots[name] = {
                "canUnderstand": understood if has_val else "NO",
                "canFulfill": understood if has_val else "NO",
            }
    return {
        "version": "1.0",
        "response": {
            "canFulfillIntent": {
                "canFulfill": can_fulfill,
                "slots": slots,
            },
        },
    }


class CanFulfillIntentHandler(AbstractRequestHandler):
    """Responds to Alexa CanFulfillIntentRequest for skill certification."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return handler_input.request_envelope.request.type == "CanFulfillIntentRequest"

    async def handle(self, handler_input: HandlerInput):
        request = handler_input.request_envelope.request
        intent = request.intent or {}
        intent_name = intent.get("name", "")

        if intent_name not in CONTENT_INTENTS and intent_name not in SEARCH_INTENTS:
            return _reply("NO", intent)

        utterance = _slot_utterance(intent)

        if not utterance:
            return _reply("YES" if intent_name in NO_UTTERANCE_OK else "MAYBE", intent)

        try:
            result = await resolve_utterance(
                "resolve_search", utterance, alexa_intent=intent_name,
            )
        except ResolverUnavailable:
            result = None

        if result and result.get("intent") in STRONG_INTENTS:
            return _reply("YES", intent)

        return _reply("MAYBE", intent)
