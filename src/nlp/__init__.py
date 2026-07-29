"""Alexa request interception backed by the local Hear resolver."""
from __future__ import annotations

import asyncio
import logging

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from config import settings
from src.nlp.classifier import classify_utterance
from src.nlp.patterns import ALEXA_TO_NLP
from src.resolver.integration import SEARCH_INTENTS, resolve_for_alexa
from src.resolver.taxonomy import taxonomy_manager

logger = logging.getLogger(__name__)


def _extract_raw_utterance(handler_input, alexa_intent: str | None) -> str | None:
    request = handler_input.request_envelope.request if handler_input.request_envelope else None
    intent = request.intent if request else None
    slots = intent.get("slots") if intent else None
    if not slots:
        return None
    priorities = {
        "PlayLocalIntent": ("localQuery", "topic", "category"),
        "PlayRecommendationIntent": ("recommendationQuery", "topic", "category"),
        "PlayByCreatorIntent": ("creatorQuery", "topic"),
        "PlayByOrganizationIntent": ("organizationQuery", "topic"),
        "BrowseByCategoryIntent": ("category", "topic"),
    }
    ordered = priorities.get(
        alexa_intent,
        ("topic", "category", "creatorQuery", "organizationQuery",
         "listPickPhrase", "feedbackPhrase", "query"),
    )
    for name in ordered:
        slot = slots.get(name)
        value = getattr(slot, "value", None) if slot else None
        if value and str(value).strip():
            return str(value).strip()
    for slot in slots.values():
        value = getattr(slot, "value", None) if slot else None
        if value and str(value).strip():
            return str(value).strip()
    return None


def _set_nlp(handler_input, payload: dict) -> None:
    attrs = handler_input.attributes_manager.request_attributes
    attrs["_nlp"] = payload
    handler_input.attributes_manager.request_attributes = attrs


class NlpInterceptor(AbstractRequestInterceptor):
    """Resolve search requests locally and classify only non-search controls."""

    async def process(self, handler_input) -> None:
        try:
            request = handler_input.request_envelope.request if handler_input.request_envelope else None
            if not request or request.type != "IntentRequest":
                return
            intent_obj = request.intent
            alexa_intent = intent_obj.name if intent_obj else None
            if not alexa_intent:
                return

            if alexa_intent == "SetLocationIntent":
                slot = (intent_obj.slots or {}).get("location")
                town = str(slot.value).strip() if slot and slot.value else None
                _set_nlp(handler_input, {
                    "intent": "location_set",
                    "alexaIntent": "location_set",
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": True,
                    "needsRedirect": False,
                    "confidence": "high",
                    "slots": {"townName": town} if town else {},
                    "localResolved": bool(town),
                })
                return

            raw = _extract_raw_utterance(handler_input, alexa_intent)
            store = handler_input.attributes_manager.request_attributes.get("_store") or {}
            if raw and store.get("onboardingStage") == "ask_town":
                _set_nlp(handler_input, {
                    "intent": "town_capture",
                    "alexaIntent": ALEXA_TO_NLP.get(alexa_intent, "general"),
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": False,
                    "needsRedirect": True,
                    "confidence": "high",
                    "slots": {"townName": raw, "placeName": raw},
                })
                return

            if not raw:
                known = ALEXA_TO_NLP.get(alexa_intent)
                if known and alexa_intent not in SEARCH_INTENTS:
                    _set_nlp(handler_input, {
                        "intent": known,
                        "alexaIntent": known,
                        "alexaRawIntent": alexa_intent,
                        "nlpMatchesAlexa": True,
                        "needsRedirect": False,
                        "confidence": "high",
                        "slots": {},
                    })
                return

            if alexa_intent in SEARCH_INTENTS:
                if settings.HEAR_TAXONOMY_AUTO_REFRESH:
                    try:
                        await asyncio.to_thread(taxonomy_manager.refresh_if_needed)
                    except Exception:
                        logger.exception("Taxonomy refresh failed; using active snapshot")
                result = resolve_for_alexa(raw)
            else:
                result = classify_utterance(raw)

            expected = ALEXA_TO_NLP.get(alexa_intent, "general")
            actual = result["intent"]
            _set_nlp(handler_input, {
                **result,
                "alexaIntent": expected,
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": actual == expected,
                "needsRedirect": actual != expected,
                "localResolved": alexa_intent in SEARCH_INTENTS,
            })
        except Exception:
            logger.warning("Hear: NlpInterceptor error", exc_info=True)
