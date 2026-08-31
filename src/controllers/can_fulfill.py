from __future__ import annotations

from typing import Any, Dict

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from src.models.resolver import ResolverUnavailable
from src.utils.deadline import DeadlineBudget


class CanFulfillPolicy:
    CONTENT_INTENTS = {
        "PlayContentIntent",
        "PlayByCreatorIntent",
        "PlayByOrganizationIntent",
        "PlayPublicationIntent",
        "BrowseContentIntent",
        "WhatsTrendingIntent",
    }
    SEARCH_INTENTS = CONTENT_INTENTS | {
        "BrowseByCategoryIntent",
        "PlayLocalIntent",
        "PlayRecommendationIntent",
    }
    NO_UTTERANCE_OK = {"BrowseContentIntent", "WhatsTrendingIntent"}
    STRONG_INTENTS = {"creator", "organization", "publication", "category", "local"}
    SLOT_PRIORITY = [
        "creatorQuery",
        "organizationQuery",
        "publicationSourceQuery",
        "topic",
        "category",
        "listPickPhrase",
        "query",
    ]

    @staticmethod
    def _slot_utterance(intent: Dict[str, Any]) -> str:
        """Extract a representative utterance from the intent's slot values."""
        if not intent or not intent.get("slots"):
            return ""
        slots = intent.get("slots", {})
        vals = []
        for name in CanFulfillPolicy.SLOT_PRIORITY:
            s = slots.get(name)
            if s and s.get("value") and str(s["value"]).strip():
                vals.append(str(s["value"]).strip())
        if not vals:
            for name, s in slots.items():
                if s and s.get("value") and str(s["value"]).strip():
                    vals.append(str(s["value"]).strip())
        return " ".join(vals).strip()

    @staticmethod
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
            "response": {"canFulfillIntent": {"canFulfill": can_fulfill, "slots": slots}},
        }


class CanFulfillIntentHandler(AbstractRequestHandler):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return handler_input.request_envelope.request.type == "CanFulfillIntentRequest"

    async def handle(self, handler_input: HandlerInput):
        request = handler_input.request_envelope.request
        intent = request.intent or {}
        intent_name = intent.get("name", "")
        if (
            intent_name not in CanFulfillPolicy.CONTENT_INTENTS
            and intent_name not in CanFulfillPolicy.SEARCH_INTENTS
        ):
            return CanFulfillPolicy._reply("NO", intent)
        utterance = CanFulfillPolicy._slot_utterance(intent)
        if not utterance:
            return CanFulfillPolicy._reply(
                "YES" if intent_name in CanFulfillPolicy.NO_UTTERANCE_OK else "MAYBE",
                intent,
            )
        try:
            result = await self._deps.resolver.resolve_utterance(
                utterance, timeout_ms=DeadlineBudget.resolver_timeout_ms(handler_input)
            )
        except ResolverUnavailable:
            result = None
        if result and result.get("intent") in CanFulfillPolicy.STRONG_INTENTS:
            return CanFulfillPolicy._reply("YES", intent)
        return CanFulfillPolicy._reply("MAYBE", intent)
