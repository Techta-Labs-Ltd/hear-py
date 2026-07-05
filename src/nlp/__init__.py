from __future__ import annotations

import logging
import re

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.nlp.classifier import classify_utterance
from src.nlp.dynamic_data import is_loaded as dynamic_data_loaded, load as load_dynamic_data
from src.nlp.grpc_blocklist import is_gated_for_grpc, GATED_INTENTS
from src.nlp.grpc_resolver import resolve as grpc_resolve
from src.nlp.patterns import ALEXA_TO_NLP
from src.nlp.preprocess import preprocess_utterance
from src.nlp.suggestions import find_suggestions
from src.nlp.wink_instance import resolve_name

logger = logging.getLogger(__name__)


def _extract_raw_utterance(handler_input, alexa_intent: str | None) -> str | None:
    """Extract the best raw utterance text from the Alexa intent slots."""
    request = handler_input.request_envelope.request if handler_input.request_envelope else None
    intent = request.intent if request else None
    slots = intent.slots if intent else None
    if not slots:
        return None

    if alexa_intent == "PlayByCreatorIntent":
        priority_order = ["creatorQuery", "topic", "organizationQuery", "listPickPhrase", "category", "feedbackPhrase"]
    elif alexa_intent == "PlayByOrganizationIntent":
        priority_order = ["organizationQuery", "topic", "creatorQuery", "listPickPhrase", "category", "feedbackPhrase"]
    elif alexa_intent == "BrowseByCategoryIntent":
        priority_order = ["category", "topic", "creatorQuery", "organizationQuery", "listPickPhrase", "feedbackPhrase"]
    elif alexa_intent in ("BrowseContentIntent", "PlayContentIntent"):
        priority_order = ["topic", "category", "creatorQuery", "organizationQuery", "listPickPhrase", "feedbackPhrase"]
    else:
        priority_order = ["topic", "creatorQuery", "organizationQuery", "listPickPhrase", "category", "feedbackPhrase"]

    for slot_name in priority_order:
        slot = slots.get(slot_name)
        if slot and slot.value and str(slot.value).strip():
            return str(slot.value).strip()

    for slot_name, slot in slots.items():
        if slot and slot.value and str(slot.value).strip():
            return str(slot.value).strip()

    return None


class NlpInterceptor(AbstractRequestInterceptor):
    """Request interceptor that performs NLP classification on incoming Alexa intents."""

    async def process(self, handler_input) -> None:
        """Classify the user utterance and attach NLP result to request attributes."""
        try:
            if not dynamic_data_loaded():
                await load_dynamic_data()

            request = handler_input.request_envelope.request if handler_input.request_envelope else None
            request_type = request.type if request else None
            if request_type != "IntentRequest":
                return

            intent_obj = request.intent if request else None
            alexa_intent = intent_obj.name if intent_obj else None
            if not alexa_intent:
                return

            # SetLocationIntent: the AMAZON.GB_CITY slot already gives a clean
            # town/city, so route straight to "location_set" without wink
            # classification. An empty slot ("change my location") is handled
            # downstream by asking the user for the town.
            if alexa_intent == "SetLocationIntent":
                loc_slots = intent_obj.slots if intent_obj else {}
                loc_slot = loc_slots.get("location") if loc_slots else None
                town = str(loc_slot.value).strip() if loc_slot and loc_slot.value else None
                attrs = handler_input.attributes_manager.request_attributes
                attrs["_nlp"] = {
                    "intent": "location_set",
                    "alexaIntent": "location_set",
                    "alexaRawIntent": alexa_intent,
                    "nlpMatchesAlexa": True,
                    "needsRedirect": False,
                    "confidence": "high",
                    "slots": {"townName": town} if town else {},
                }
                handler_input.attributes_manager.request_attributes = attrs
                logger.info("Hear: SetLocationIntent captured", extra={"town": town})
                return

            raw = _extract_raw_utterance(handler_input, alexa_intent)

            if not raw:
                slots = intent_obj.slots if intent_obj else {}
                slot_dump = {}
                if slots:
                    for sn, s in slots.items():
                        slot_dump[sn] = s.value if s else None

                if alexa_intent == "AMAZON.FallbackIntent":
                    fallback_slot = slots.get("query") if slots else None
                    fallback_val = fallback_slot.value if fallback_slot else None
                    if fallback_val and str(fallback_val).strip():
                        raw = str(fallback_val).strip()
                    else:
                        logger.info("Hear: NLP fallback skipped (FallbackIntent, no slot)",
                                    extra={"alexaIntent": alexa_intent, "slots": slot_dump})
                        return

                if not raw:
                    known_intent = ALEXA_TO_NLP.get(alexa_intent)
                    if known_intent and alexa_intent not in GATED_INTENTS:
                        attrs = handler_input.attributes_manager.request_attributes
                        attrs["_nlp"] = {
                            "intent": known_intent,
                            "alexaIntent": known_intent,
                            "alexaRawIntent": alexa_intent,
                            "nlpMatchesAlexa": True,
                            "needsRedirect": False,
                            "confidence": "high",
                            "slots": {},
                        }
                        handler_input.attributes_manager.request_attributes = attrs
                        return

                    attrs = handler_input.attributes_manager.request_attributes
                    attrs["_nlp"] = {
                        "intent": "unclear",
                        "alexaIntent": "general",
                        "alexaRawIntent": alexa_intent,
                        "nlpMatchesAlexa": False,
                        "needsRedirect": True,
                        "confidence": "low",
                        "slots": {},
                        "suggestions": [],
                    }
                    handler_input.attributes_manager.request_attributes = attrs
                    logger.info("Hear: NLP unclear (no utterance captured)",
                                extra={"alexaIntent": alexa_intent, "slots": slot_dump})
                    return

            if is_gated_for_grpc(alexa_intent, raw):
                grpc_result = await grpc_resolve(raw)
                if grpc_result:
                    g_alexa_nlp = ALEXA_TO_NLP.get(alexa_intent, "general")
                    g_match = grpc_result["intent"] == g_alexa_nlp
                    g_attrs = handler_input.attributes_manager.request_attributes
                    g_attrs["_nlp"] = {
                        "intent": grpc_result["intent"],
                        "alexaIntent": g_alexa_nlp,
                        "alexaRawIntent": alexa_intent,
                        "nlpMatchesAlexa": g_match,
                        "needsRedirect": not g_match,
                        "confidence": grpc_result["confidence"],
                        "slots": grpc_result["slots"],
                        "alternatives": grpc_result.get("alternatives"),
                        "suggestions": grpc_result.get("alternatives") if grpc_result["intent"] == "unclear" else None,
                        "grpcResolved": True,
                        "grpcResolvedInMs": grpc_result.get("resolvedInMs", 0),
                    }
                    handler_input.attributes_manager.request_attributes = g_attrs
                    logger.info("Hear: gRPC resolved", extra={
                        "raw": raw,
                        "intent": grpc_result["intent"],
                        "confidence": grpc_result["confidence"],
                        "slots": grpc_result["slots"],
                        "ms": grpc_result.get("resolvedInMs"),
                    })
                    return

            nlp_result = classify_utterance(raw)

            alexa_slots = intent_obj.slots if intent_obj else {}
            if alexa_slots:
                creator_slot = alexa_slots.get("creatorQuery")
                if creator_slot and creator_slot.value and str(creator_slot.value).strip():
                    raw_creator = str(creator_slot.value).strip()
                    resolved_creator = resolve_name("CREATOR", raw_creator)
                    creator_resolved = resolved_creator != raw_creator
                    creator_single_word = " " not in raw_creator
                    if creator_resolved:
                        nlp_result["slots"]["creatorQuery"] = resolved_creator
                    elif (nlp_result["slots"].get("creatorQuery") and
                          nlp_result["slots"]["creatorQuery"].lower() == raw_creator.lower()):
                        nlp_result["slots"]["creatorQuery"] = resolved_creator
                    elif (not nlp_result["slots"].get("creatorQuery") and creator_single_word and
                          bool(re.match(r"^PlayByCreator", alexa_intent, re.IGNORECASE))):
                        nlp_result["slots"]["creatorQuery"] = resolved_creator

                org_slot = alexa_slots.get("organizationQuery")
                if org_slot and org_slot.value and str(org_slot.value).strip():
                    raw_org = str(org_slot.value).strip()
                    resolved_org = resolve_name("ORGANIZATION", raw_org)
                    org_resolved = resolved_org != raw_org
                    org_single_word = " " not in raw_org
                    if org_resolved:
                        nlp_result["slots"]["organizationQuery"] = resolved_org
                    elif (nlp_result["slots"].get("organizationQuery") and
                          nlp_result["slots"]["organizationQuery"].lower() == raw_org.lower()):
                        nlp_result["slots"]["organizationQuery"] = resolved_org
                    elif (not nlp_result["slots"].get("organizationQuery") and org_single_word and
                          bool(re.match(r"^PlayByOrganization", alexa_intent, re.IGNORECASE))):
                        nlp_result["slots"]["organizationQuery"] = resolved_org

                topic_slot = alexa_slots.get("topic")
                if topic_slot and topic_slot.value and str(topic_slot.value).strip():
                    topic_val = str(topic_slot.value).strip()
                    topic_stripped = re.sub(
                        r"^(?:me\s+)?(?:the\s+)?(latest|newest|most\s+recent|recent)\s+",
                        "", topic_val, flags=re.IGNORECASE,
                    ).strip()
                    if topic_stripped != topic_val:
                        nlp_result["slots"]["latest"] = True
                    nlp_result["slots"]["topic"] = topic_stripped
                    if topic_stripped != raw:
                        topic_nlp = classify_utterance(topic_stripped)
                        if topic_nlp["slots"].get("category"):
                            nlp_result["slots"]["category"] = topic_nlp["slots"]["category"]
                        if topic_nlp["slots"].get("city"):
                            nlp_result["slots"]["city"] = topic_nlp["slots"]["city"]
                        if topic_nlp["slots"].get("placeName"):
                            nlp_result["slots"]["placeName"] = topic_nlp["slots"]["placeName"]
                        if topic_nlp["slots"].get("latest"):
                            nlp_result["slots"]["latest"] = True

                category_slot = alexa_slots.get("category")
                if category_slot and category_slot.value and str(category_slot.value).strip():
                    raw_cat = str(category_slot.value).strip()
                    cat_stripped = re.sub(
                        r"^(?:the )?(latest|newest|most recent|recent)\s+",
                        "", raw_cat, flags=re.IGNORECASE,
                    ).strip()
                    if cat_stripped != raw_cat:
                        nlp_result["slots"]["latest"] = True
                    resolved_cat = resolve_name("CATEGORY", cat_stripped)
                    if resolved_cat == cat_stripped:
                        from_raw = resolve_name("CATEGORY", raw_cat)
                        if from_raw != raw_cat:
                            resolved_cat = from_raw
                    if resolved_cat != cat_stripped or not nlp_result["slots"].get("category"):
                        nlp_result["slots"]["category"] = resolved_cat
                        if nlp_result["slots"].get("topic") == raw_cat:
                            nlp_result["slots"]["topic"] = resolved_cat

            alexa_nlp_intent = ALEXA_TO_NLP.get(alexa_intent, "general")

            if nlp_result["intent"] == "general" and alexa_nlp_intent != "general":
                if alexa_nlp_intent == "creator" and nlp_result["slots"].get("creatorQuery"):
                    fuzzy_match = None
                    for s in find_suggestions(raw):
                        if s["intent"] == "creator" and s["confidence"] >= 7:
                            fuzzy_match = s
                            break
                    if fuzzy_match:
                        nlp_result["slots"]["creatorQuery"] = fuzzy_match.get("query") or nlp_result["slots"]["creatorQuery"]
                        logger.info("Hear: NLP fuzzy-matched creator from DynamoDB", extra={
                            "raw": raw, "matched": fuzzy_match.get("query"), "confidence": fuzzy_match["confidence"],
                        })
                    nlp_result["intent"] = "creator"
                elif alexa_nlp_intent == "organization" and nlp_result["slots"].get("organizationQuery"):
                    fuzzy_org_match = None
                    for s in find_suggestions(raw):
                        if s["intent"] == "organization" and s["confidence"] >= 7:
                            fuzzy_org_match = s
                            break
                    if fuzzy_org_match:
                        nlp_result["slots"]["organizationQuery"] = fuzzy_org_match.get("query") or nlp_result["slots"]["organizationQuery"]
                        logger.info("Hear: NLP fuzzy-matched organization from DynamoDB", extra={
                            "raw": raw, "matched": fuzzy_org_match.get("query"), "confidence": fuzzy_org_match["confidence"],
                        })
                    nlp_result["intent"] = "organization"
                elif alexa_nlp_intent == "category" and nlp_result["slots"].get("category"):
                    nlp_result["intent"] = "category"

            match = nlp_result["intent"] == alexa_nlp_intent

            try:
                store = handler_input.attributes_manager.request_attributes.get("_store")
                town_name = nlp_result["slots"].get("placeName") or nlp_result["slots"].get("city")
                if store and store.get("onboardingStage") == "ask_town" and town_name:
                    nlp_result["intent"] = "town_capture"
                    nlp_result["slots"]["townName"] = town_name
                    match = False
                    logger.info("Hear: NLP town capture override", extra={"town": town_name})
            except Exception:
                pass

            if nlp_result["intent"] == "general" and (
                not nlp_result["slots"].get("topic") or nlp_result["slots"].get("topic") == raw
            ):
                suggestions = find_suggestions(raw)
                if suggestions and suggestions[0]["confidence"] >= 5:
                    logger.info("Hear: NLP unclear -> suggestions found", extra={
                        "raw": raw,
                        "suggestionCount": len(suggestions),
                        "top": f'{suggestions[0]["intent"]}:{suggestions[0].get("query") or ""}',
                        "topConfidence": suggestions[0]["confidence"],
                    })
                    attrs = handler_input.attributes_manager.request_attributes
                    attrs["_nlp"] = {
                        "intent": "unclear",
                        "alexaIntent": "general",
                        "alexaRawIntent": alexa_intent,
                        "nlpMatchesAlexa": False,
                        "needsRedirect": True,
                        "confidence": "low",
                        "slots": {},
                        "suggestions": suggestions,
                    }
                    handler_input.attributes_manager.request_attributes = attrs
                    return
                logger.info("Hear: NLP unclear -> no suggestions",
                            extra={"raw": raw, "intent": nlp_result["intent"]})

            attrs = handler_input.attributes_manager.request_attributes
            attrs["_nlp"] = {
                "intent": nlp_result["intent"],
                "alexaIntent": alexa_nlp_intent,
                "alexaRawIntent": alexa_intent,
                "nlpMatchesAlexa": match,
                "needsRedirect": not match,
                "confidence": nlp_result["confidence"],
                "slots": nlp_result["slots"],
            }
            handler_input.attributes_manager.request_attributes = attrs

            if not match:
                logger.info("Hear: intent mismatch", extra={
                    "raw": raw,
                    "alexaIntent": alexa_intent,
                    "alexaNlpIntent": alexa_nlp_intent,
                    "nlpIntent": nlp_result["intent"],
                    "confidence": nlp_result["confidence"],
                })

        except Exception as err:
            logger.warning("Hear: NlpInterceptor error", exc_info=True)
