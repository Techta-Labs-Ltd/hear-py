"""Alexa request interception backed by the dedicated resolver Lambda."""
from __future__ import annotations

import logging
import time

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.nlp.patterns import ALEXA_TO_NLP
from src.services.resolver_client import ResolverUnavailable, resolve_utterance
from src.services.dialog_state import activate_dialog, active_dialog_from_store
from src.services.storage.persistence import update_store
from src.utils.skill_request import get_user_id

logger = logging.getLogger(__name__)
SEARCH_INTENTS = {
    "PlayContentIntent", "PlayByCreatorIntent", "PlayByOrganizationIntent",
    "BrowseContentIntent", "BrowseByCategoryIntent", "WhatsTrendingIntent",
    "PlayLocalIntent", "PlayRecommendationIntent",
}


def _extract_raw_utterance(handler_input, alexa_intent: str | None) -> str | None:
    request = handler_input.request_envelope.request if handler_input.request_envelope else None
    intent = request.intent if request else None
    slots = intent.get("slots") if intent else None
    if not slots:
        return None
    priorities = {
        "TownCaptureIntent": ("townName",),
        "PlayLocalIntent": ("localQuery", "topic", "category"),
        "PlayRecommendationIntent": ("recommendationQuery", "topic", "category"),
        "PlayByCreatorIntent": ("creatorQuery", "topic"),
        "PlayByOrganizationIntent": ("organizationQuery", "topic"),
        "BrowseByCategoryIntent": ("category", "topic"),
    }
    ordered = priorities.get(
        alexa_intent,
        ("topic", "category", "creatorQuery", "organizationQuery",
         "selection", "listPickPhrase", "feedbackPhrase", "query"),
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

            early_store = (
                handler_input.attributes_manager.request_attributes.get("_store") or {}
            )
            early_dialog = active_dialog_from_store(early_store)
            if (
                alexa_intent == "TownCaptureIntent"
                and not isinstance(early_store.get("pendingAmbiguity"), dict)
                and (early_dialog or {}).get("type") != "ambiguity"
            ):
                slot = (intent_obj.slots or {}).get("townName")
                town = str(slot.value).strip() if slot and slot.value else None
                _set_nlp(handler_input, {
                    "intent": "town_capture",
                    "alexaIntent": "town_capture",
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": True,
                    "needsRedirect": False,
                    "confidence": "high",
                    "slots": {"townName": town, "placeName": town} if town else {},
                })
                return

            raw = _extract_raw_utterance(handler_input, alexa_intent)
            store = handler_input.attributes_manager.request_attributes.get("_store") or {}
            pending_ambiguity = store.get("pendingAmbiguity")
            if raw and isinstance(pending_ambiguity, dict):
                if int(pending_ambiguity.get("expiresAt") or 0) < int(time.time()):
                    update_store(handler_input, {"pendingAmbiguity": None})
                else:
                    result = await resolve_utterance(
                        "resolve_ambiguity_follow_up",
                        raw,
                        alexa_intent=alexa_intent,
                        alexa_user_id=get_user_id(handler_input) or "",
                        request_id=str(getattr(request, "request_id", "") or ""),
                        context=pending_ambiguity,
                    )
                    if result.get("status") == "resolved":
                        update_store(handler_input, {"pendingAmbiguity": None})
                        activate_dialog(
                            handler_input,
                            "ambiguity",
                            context=pending_ambiguity,
                        )
                    elif result.get("status") == "ambiguous":
                        narrowed = (result.get("ambiguities") or [{}])[0].get("candidates") or []
                        narrowed_context = {
                            **pending_ambiguity,
                            "candidates": narrowed[:3],
                            "expiresAt": int(time.time()) + 300,
                        }
                        update_store(handler_input, {
                            "pendingAmbiguity": {
                                **narrowed_context,
                            },
                        })
                        activate_dialog(
                            handler_input,
                            "ambiguity",
                            context=narrowed_context,
                        )
                    _set_nlp(handler_input, {
                        **result,
                        "alexaIntent": ALEXA_TO_NLP.get(alexa_intent, "general"),
                        "alexaRawIntent": alexa_intent,
                        "nlpMatchesAlexa": False,
                        "needsRedirect": True,
                        "localResolved": True,
                    })
                    return

            # The latest explicit prompt owns the reply. A stale onboarding
            # stage must not steal an organization/creator ambiguity answer.
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

            if raw and store.get("awaitingOrganizationName"):
                result = await resolve_utterance(
                    "resolve_organization_follow_up",
                    raw,
                    alexa_intent=alexa_intent,
                    alexa_user_id=get_user_id(handler_input) or "",
                    request_id=str(getattr(request, "request_id", "") or ""),
                )
                result["intent"] = "organization"
                result.setdefault("slots", {})["organizationQuery"] = raw
                result["slots"]["organizationFollowUp"] = True
                _set_nlp(handler_input, {
                    **result,
                    "alexaIntent": "organization",
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": alexa_intent == "PlayByOrganizationIntent",
                    "needsRedirect": alexa_intent != "PlayByOrganizationIntent",
                    "localResolved": True,
                })
                return

            if not raw:
                # Alexa does not expose the rejected utterance on a fallback
                # request. Do not invent a generic search: preserve the
                # request so the state-aware FallbackHandler can repeat the
                # active clarification or give normal fallback guidance.
                if alexa_intent == "AMAZON.FallbackIntent":
                    return
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
                result = await resolve_utterance(
                    "resolve_search",
                    raw,
                    alexa_intent=alexa_intent,
                    alexa_user_id=get_user_id(handler_input) or "",
                    request_id=str(getattr(request, "request_id", "") or ""),
                )
            else:
                known = ALEXA_TO_NLP.get(alexa_intent)
                if not known:
                    return
                result = {
                    "intent": known,
                    "confidence": "high",
                    "slots": {},
                }

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
        except ResolverUnavailable:
            _set_nlp(handler_input, {
                "intent": "resolver_unavailable",
                "confidence": "low",
                "slots": {},
            })
            logger.warning("Hear resolver unavailable")
        except Exception:
            logger.warning("Hear: NlpInterceptor error", exc_info=True)
