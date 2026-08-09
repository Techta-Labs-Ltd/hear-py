from __future__ import annotations
import logging
import re
import time
from ask_sdk_core.dispatch_components import AbstractRequestInterceptor
from src.models import ALEXA_TO_NLP
from src.clients.resolver import ResolverUnavailable
from src.dependencies import Dependencies
from src.services.dialog_state import (
    activate_dialog,
    active_dialog_from_store,
    clear_active_dialog,
)
from src.services.store import update_store
from src.utils.skill_request import (
    get_resolved_slot_id,
    get_resolved_slot_value,
    get_user_id,
)
from src.middleware.dialog_validation import DIALOG_VALIDATION_FAILURE
from src.utils.discovery_request import is_reserved_discovery_phrase
from src.utils.discovery_request import is_meaningful_publication_source
logger = logging.getLogger(__name__)


SEARCH_INTENTS = {
    "PlayContentIntent", "PlayByCreatorIntent", "PlayByOrganizationIntent",
    "PlayPublicationIntent",
    "BrowseContentIntent", "BrowseByCategoryIntent", "WhatsTrendingIntent",
    "PlayLocalIntent", "PlayRecommendationIntent",
}


AMBIGUITY_CONTROL_INTENTS = {
    "AMAZON.YesIntent", "AMAZON.NoIntent", "AMAZON.CancelIntent",
    "AMAZON.StopIntent", "AMAZON.HelpIntent", "AMAZON.FallbackIntent",
    "ShowMoreBrowseIntent",
}

CANONICAL_ZERO_SLOT_DISCOVERY = {
    "PlayContentIntent": "play",
    "PlayByCreatorIntent": "play",
    "PlayByOrganizationIntent": "play",
    "PlayPublicationIntent": "play publication",
    "BrowseByCategoryIntent": "play",
    "BrowseContentIntent": "what's new",
    "WhatsTrendingIntent": "what's trending",
    "PlayLocalIntent": "play local content",
    "PlayRecommendationIntent": "recommend something",
}

_ORDINAL_INDEX = {
    "first": 0, "one": 0, "1": 0, "number one": 0,
    "second": 1, "two": 1, "2": 1, "number two": 1,
    "third": 2, "three": 2, "3": 2, "number three": 2,
    "fourth": 3, "four": 3, "4": 3, "number four": 3,
    "fifth": 4, "five": 4, "5": 4, "number five": 4,
    "sixth": 5, "six": 5, "6": 5, "number six": 5,
}


def _normalize_ordinal(value: object) -> str:
    raw = str(value or "").strip().casefold()
    raw = raw.replace("1st", "first").replace("2nd", "second").replace("3rd", "third")
    raw = raw.replace("4th", "fourth").replace("5th", "fifth").replace("6th", "sixth")
    raw = re.sub(r"^(?:the\s+)", "", raw)
    raw = re.sub(r"\s+(?:one|option|choice)$", "", raw)
    return raw


def _unique_candidates(candidates: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for candidate in candidates:
        name = str(candidate.get("name") or "").strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _selection_slot(handler_input):
    request = handler_input.request_envelope.request
    intent = getattr(request, "intent", None)
    slots = intent.get("slots") if intent else None
    return slots.get("selection") if slots else None


def _match_pending_candidate(
    handler_input,
    pending: dict,
    raw: str,
) -> dict | None:
    candidates = list(pending.get("candidates") or [])
    resolved_id = get_resolved_slot_id(_selection_slot(handler_input))
    if resolved_id:
        matched = next(
            (candidate for candidate in candidates if candidate.get("id") == resolved_id),
            None,
        )
        if matched:
            return matched

    choices = list(pending.get("choiceCandidates") or _unique_candidates(candidates))
    displayed = list(pending.get("displayedCandidates") or choices[:3])
    raw_key = _normalize_ordinal(raw)
    ordinal = _ORDINAL_INDEX.get(raw_key)
    if ordinal is not None and ordinal < len(displayed):
        return displayed[ordinal]

    matches = [
        candidate for candidate in choices
        if raw_key == str(candidate.get("name") or "").strip().casefold()
        or (
            len(raw_key) >= 3
            and raw_key in str(candidate.get("name") or "").strip().casefold()
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _resolved_pending_candidate(pending: dict, candidate: dict) -> dict:
    entity_type = str(candidate["type"])
    entity_id = str(candidate["id"])
    name = str(candidate["name"])
    filter_keys = {
        "creator": "creatorIds",
        "organization": "organizationIds",
        "publication": "publicationIds",
    }
    name_keys = {
        "creator": "creatorName",
        "organization": "organizationName",
        "publication": "publicationName",
    }
    filters = dict((pending.get("searchPayload") or {}).get("filter") or {})
    for key in filter_keys.values():
        filters.pop(key, None)
    filter_key = filter_keys.get(entity_type)
    if filter_key:
        filters[filter_key] = [entity_id]
    payload = {
        **dict(pending.get("searchPayload") or {}),
        "query": "",
        "filter": filters,
    }
    slots = {
        **dict(pending.get("slots") or {}),
        "residualQuery": "",
        "ambiguousReferences": [],
    }
    if filter_key:
        slots[filter_key] = [entity_id]
        slots[name_keys[entity_type]] = name
    return {
        "status": "resolved",
        "intent": entity_type if entity_type in filter_keys else pending.get("intent", "search"),
        "ambiguityResolution": True,
        "confirmationLabel": f"content from {name}",
        "searchPayload": payload,
        "entities": [{
            "type": entity_type,
            "id": entity_id,
            "canonicalValue": name,
        }],
        "slots": slots,
        "ambiguities": [],
    }


def _extract_raw_utterance(handler_input, alexa_intent: str | None) -> str | None:
    request = handler_input.request_envelope.request if handler_input.request_envelope else None
    intent = request.intent if request else None
    slots = intent.get("slots") if intent else None
    if not slots:
        return None
    date_slot = slots.get("dateQuery")
    date_value = getattr(date_slot, "value", None) if date_slot else None
    date_text = str(date_value).strip() if date_value else ""
    if alexa_intent == "PlayPublicationIntent":
        source_slot = slots.get("publicationSourceQuery")
        sort_slot = slots.get("publicationSort")
        source = getattr(source_slot, "value", None) if source_slot else None
        requested_sort = getattr(sort_slot, "value", None) if sort_slot else None
        parts = ["play"]
        if date_text:
            parts.append(date_text)
        if requested_sort and str(requested_sort).strip():
            parts.append(str(requested_sort).strip())
        parts.append("publication")
        if source and str(source).strip():
            parts.extend(("from", str(source).strip()))
        return " ".join(parts)
    priorities = {
        "TownCaptureIntent": ("townName", "selection"),
        "SetLocationIntent": ("location", "townName", "selection"),
        "PlayLocalIntent": ("localQuery", "topic", "category"),
        "PlayRecommendationIntent": ("recommendationQuery", "topic", "category"),
        "PlayByCreatorIntent": ("creatorQuery", "topic"),
        "PlayByOrganizationIntent": ("organizationQuery", "topic"),
        "PlayPublicationIntent": ("publicationSourceQuery", "topic"),
        "BrowseByCategoryIntent": ("category", "topic"),
    }
    ordered = priorities.get(
        alexa_intent,
        ("selection", "townName", "location", "topic", "category", "creatorQuery",
         "organizationQuery", "publicationSourceQuery", "listPickPhrase",
         "feedbackPhrase", "query"),
    )
    for name in ordered:
        slot = slots.get(name)
        value = getattr(slot, "value", None) if slot else None
        if value and str(value).strip():
            raw = str(value).strip()
            return f"{date_text} {raw}".strip()
    for slot in slots.values():
        if slot is date_slot:
            continue
        value = getattr(slot, "value", None) if slot else None
        if value and str(value).strip():
            raw = str(value).strip()
            return f"{date_text} {raw}".strip()
    return date_text or None


def _set_nlp(handler_input, payload: dict) -> None:
    attrs = handler_input.attributes_manager.request_attributes
    attrs["_nlp"] = payload
    handler_input.attributes_manager.request_attributes = attrs


class ResolverInterceptor(AbstractRequestInterceptor):

    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    async def process(self, handler_input) -> None:
        try:
            if handler_input.attributes_manager.request_attributes.get(
                DIALOG_VALIDATION_FAILURE
            ):
                return
            request = handler_input.request_envelope.request if handler_input.request_envelope else None
            if not request or request.type != "IntentRequest":
                return
            intent_obj = request.intent
            alexa_intent = intent_obj.name if intent_obj else None
            if not alexa_intent:
                return

            early_store = (
                handler_input.attributes_manager.request_attributes.get("_store") or {}
            )
            early_dialog = active_dialog_from_store(early_store)
            ambiguity_active = (
                isinstance(early_store.get("pendingAmbiguity"), dict)
                or (early_dialog or {}).get("type") == "ambiguity"
            )

            if alexa_intent == "SetLocationIntent" and not ambiguity_active:
                slot = (intent_obj.slots or {}).get("location")
                town = get_resolved_slot_value(slot)
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

            if (
                alexa_intent == "TownCaptureIntent"
                and not isinstance(early_store.get("pendingAmbiguity"), dict)
                and (early_dialog or {}).get("type") != "ambiguity"
            ):
                slot = (intent_obj.slots or {}).get("townName")
                town = get_resolved_slot_value(slot)
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
            if alexa_intent == "PlayPublicationIntent":
                slots = intent_obj.slots or {}
                source_slot = slots.get("publicationSourceQuery")
                source = get_resolved_slot_value(source_slot)
                if not is_meaningful_publication_source(source):
                    _set_nlp(handler_input, {
                        "status": "resolved",
                        "intent": "publication",
                        "alexaIntent": "publication",
                        "alexaRawIntent": alexa_intent,
                        "nlpMatchesAlexa": True,
                        "needsRedirect": False,
                        "localResolved": True,
                        "publicationSourceRequired": True,
                        "slots": {
                            "publicationSourceQuery": source or "",
                            "publicationSort": get_resolved_slot_value(slots.get("publicationSort")),
                            "dateQuery": get_resolved_slot_value(slots.get("dateQuery")),
                        },
                    })
                    logger.info("Hear: publication source required; resolver skipped")
                    return
            if not raw and alexa_intent in SEARCH_INTENTS:
                raw = CANONICAL_ZERO_SLOT_DISCOVERY.get(alexa_intent)
            store = handler_input.attributes_manager.request_attributes.get("_store") or {}
            pending_ambiguity = store.get("pendingAmbiguity")
            if raw and isinstance(pending_ambiguity, dict):
                if int(pending_ambiguity.get("expiresAt") or 0) < int(time.time()):
                    update_store(handler_input, {"pendingAmbiguity": None})
                    clear_active_dialog(handler_input, "ambiguity")
                elif alexa_intent not in AMBIGUITY_CONTROL_INTENTS:
                    matched_candidate = _match_pending_candidate(
                        handler_input, pending_ambiguity, raw,
                    )
                    result = (
                        _resolved_pending_candidate(
                            pending_ambiguity, matched_candidate,
                        )
                        if matched_candidate
                        else await self._deps.resolver.resolve_utterance(
                            raw,
                            alexa_user_id=get_user_id(handler_input),
                        )
                    )
                    replace_ambiguity = (
                        alexa_intent in SEARCH_INTENTS
                        and result.get("status") != "resolved"
                        and not result.get("followUpMatched", False)
                    )
                    if replace_ambiguity:
                        update_store(handler_input, {"pendingAmbiguity": None})
                        clear_active_dialog(handler_input, "ambiguity")
                    else:
                        if result.get("status") == "resolved":
                            update_store(handler_input, {
                                "pendingAmbiguity": None,
                                "awaitingLocationConfirm": False,
                                "pendingLocationConfirm": None,
                            })
                            clear_active_dialog(handler_input, "ambiguity")
                        elif result.get("status") == "ambiguous":
                            narrowed = (result.get("ambiguities") or [{}])[0].get("candidates") or []
                            displayed = (
                                narrowed[:3]
                                if result.get("followUpMatched", True)
                                else list(pending_ambiguity.get("displayedCandidates") or [])[:3]
                            )
                            narrowed_context = {
                                **pending_ambiguity,
                                "displayedCandidates": displayed,
                                "expiresAt": int(time.time()) + 300,
                            }
                            update_store(handler_input, {"pendingAmbiguity": narrowed_context})
                            activate_dialog(
                                handler_input,
                                "ambiguity",
                                context=narrowed_context,
                            )
                        _set_nlp(handler_input, {
                            **result,
                            "ambiguityRetry": result.get("status") == "ambiguous",
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

            if (
                raw
                and alexa_intent in SEARCH_INTENTS
                and is_reserved_discovery_phrase(raw)
            ):
                logger.info(
                    "Hear: reserved discovery phrase handled locally intent=%s phrase=%r",
                    alexa_intent,
                    raw,
                )
                _set_nlp(handler_input, {
                    "status": "resolved",
                    "intent": "general",
                    "alexaIntent": ALEXA_TO_NLP.get(alexa_intent, "general"),
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": True,
                    "needsRedirect": False,
                    "localResolved": True,
                    "searchPayload": {"query": "", "filter": {}},
                    "slots": {"residualQuery": ""},
                })
                return

            if raw and store.get("awaitingOrganizationName"):
                result = await self._deps.resolver.resolve_utterance(
                    raw,
                    alexa_user_id=get_user_id(handler_input),
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
                result = await self._deps.resolver.resolve_utterance(
                    raw,
                    alexa_user_id=get_user_id(handler_input),
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
            _set_nlp(handler_input, {
                "intent": "resolver_unavailable",
                "confidence": "low",
                "slots": {},
            })
            logger.warning("Hear: ResolverInterceptor error", exc_info=True)
