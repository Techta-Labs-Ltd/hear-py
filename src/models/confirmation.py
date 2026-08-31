from __future__ import annotations

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.search_speech import SearchSpeech
from src.constants.dialog import DialogConstants
from src.models.resolver import ResolutionBuilder
from src.utils.filters import SearchFilterUtils


class ConfirmationPolicy:
    RESOLVED_INTENTS = frozenset(
        {
            "local",
            "creator",
            "organization",
            "publication",
            "category",
            "general",
            "trending",
            "browse",
            "following",
            "search",
        }
    )
    ALEXA_INTENTS = frozenset(
        {
            "PlayContentIntent",
            "PlayByCreatorIntent",
            "PlayByOrganizationIntent",
            "PlayPublicationIntent",
            "BrowseContentIntent",
            "BrowseByCategoryIntent",
            "WhatsTrendingIntent",
            "PlayLocalIntent",
            "PlayRecommendationIntent",
        }
    )
    SLOT_PRIORITY = {
        "PlayByCreatorIntent": (
            "creatorQuery",
            "topic",
            "organizationQuery",
            "listPickPhrase",
            "category",
            "feedbackPhrase",
        ),
        "PlayByOrganizationIntent": (
            "organizationQuery",
            "topic",
            "creatorQuery",
            "listPickPhrase",
            "category",
            "feedbackPhrase",
        ),
        "PlayPublicationIntent": (
            "publicationSourceQuery",
            "topic",
            "creatorQuery",
            "organizationQuery",
            "listPickPhrase",
            "category",
        ),
        "BrowseByCategoryIntent": (
            "category",
            "topic",
            "creatorQuery",
            "organizationQuery",
            "listPickPhrase",
            "feedbackPhrase",
        ),
    }
    DEFAULT_SLOT_PRIORITY = (
        "topic",
        "creatorQuery",
        "organizationQuery",
        "listPickPhrase",
        "category",
        "feedbackPhrase",
    )

    @staticmethod
    def has_pending_ambiguity(nlp: dict | None) -> bool:
        if not isinstance(nlp, dict):
            return False
        slots = nlp.get("slots") or {}
        return bool(nlp.get("ambiguities") or slots.get("ambiguousReferences"))

    @staticmethod
    def _has_meaningful_general_request(nlp: dict, raw: str | None) -> bool:
        slots = nlp.get("slots") or {}
        payload = nlp.get("searchPayload") or slots.get("searchPlan") or {}
        query = SearchFilterUtils.normalize_discovery_phrase(
            payload.get("query")
            or slots.get("residualQuery")
            or slots.get("topic")
            or slots.get("query")
            or raw
        )
        return bool(payload.get("filter")) or not SearchFilterUtils.is_reserved_discovery_phrase(
            query
        )

    @staticmethod
    def requires_clarification(nlp: dict, raw: str | None) -> bool:
        intent = str(nlp.get("intent") or "")
        slots = nlp.get("slots") or {}
        requirements = {
            "creator": slots.get("creatorIds") or slots.get("creatorName"),
            "organization": slots.get("organizationIds") or slots.get("organizationName"),
            "publication": slots.get("publicationIds")
            or slots.get("publicationName")
            or slots.get("publicationSourceQuery"),
            "category": slots.get("category") or slots.get("tags") or slots.get("residualQuery"),
        }
        if intent == "general":
            return not ConfirmationPolicy._has_meaningful_general_request(nlp, raw)
        return intent in requirements and not bool(requirements[intent])

    @staticmethod
    def _slot_context(nlp: dict) -> dict:
        slots = nlp.get("slots") or {}
        return {
            "slots": slots,
            "intent": nlp["intent"],
            "category": slots.get("category") or slots.get("topic"),
            "creator": slots.get("creatorName")
            or slots.get("creatorQuery")
            or slots.get("creator"),
            "organization": slots.get("organizationName")
            or slots.get("organizationQuery")
            or slots.get("organization"),
            "publication": slots.get("publicationSourceQuery"),
            "city": slots.get("city") or slots.get("placeName"),
            "residual": str(slots.get("residualQuery") or "").strip(),
        }

    @staticmethod
    def _resolved_subject(context: dict) -> str | None:
        intent = context["intent"]
        slots = context["slots"]
        source = {
            "organization": context["organization"],
            "creator": context["creator"],
            "publication": context["publication"],
        }.get(intent)
        if intent in {"organization", "creator"} and not source:
            return None
        if intent in {"organization", "creator", "publication"}:
            return SearchSpeech.resolved_search_request_label(slots, source)
        has_subject = bool(context["category"] or slots.get("tags") or context["residual"])
        if intent in {"category", "general"} and has_subject:
            return SearchSpeech.resolved_search_request_label(slots)
        if intent == "search" and context["city"]:
            return SearchSpeech.resolved_search_request_label(slots)
        return None

    @staticmethod
    def _discovery_subject(context: dict) -> str | None:
        intent = context["intent"]
        category = context["category"]
        city = context["city"]
        latest = "the latest " if context["slots"].get("latest") else ""
        if intent == "local":
            if category and city:
                return f"{latest}{category} nearest to {city}"
            if city:
                return f"{latest}from {city}" if latest else f"content from {city}"
            return f"{latest}{category} in your community" if category else "tracks near you"
        if intent == "trending":
            suffix = f" in {category}" if category else ""
            suffix += f" near {city}" if city else ""
            return f"whatâ€™s trending{suffix}" if suffix else "whatâ€™s trending right now"
        if intent == "browse":
            if category and city:
                return f"new {category} near {city}"
            if category or city:
                return f"new in {category}" if category else f"whatâ€™s new near {city}"
            return "browse content"
        if intent == "following":
            return (
                f"{category} from your followed creators" if category else "your followed creators"
            )
        return None

    @staticmethod
    def _source_subject(context: dict) -> str | None:
        intent = context["intent"]
        category = context["category"]
        residual = context["residual"]
        source = context["creator"] if intent == "creator" else context["organization"]
        if intent not in {"creator", "organization"} or not source:
            return None
        details = [value for value in (category, residual) if value]
        if not details:
            return f"the latest {source}" if context["slots"].get("latest") else source
        description = ", ".join(details)
        prefix = "the latest " if context["slots"].get("latest") else ""
        return f"{prefix}{description} from {source}"

    @staticmethod
    def confirmation_speech(nlp: dict | None) -> str | None:
        if not nlp or not nlp.get("intent"):
            return None
        context = ConfirmationPolicy._slot_context(nlp)
        slots = context["slots"]
        has_subject = bool(context["category"] or slots.get("tags") or context["residual"])
        has_source = bool(
            slots.get("creatorIds")
            or slots.get("organizationIds")
            or slots.get("publicationIds")
            or context["creator"]
            or context["organization"]
            or context["publication"]
        )
        if (
            context["intent"] in {"category", "general", "search"}
            and has_subject
            and not has_source
        ):
            subject = SearchSpeech.resolved_search_request_label(slots)
            prefix = (
                "the latest content on " if subject.startswith("the latest ") else "content on "
            )
            return prefix + subject.removeprefix("the latest ")
        if nlp.get("confirmationLabel"):
            return str(nlp["confirmationLabel"])
        subject = ConfirmationPolicy._resolved_subject(context)
        subject = subject or ConfirmationPolicy._discovery_subject(context)
        subject = subject or ConfirmationPolicy._source_subject(context)
        if subject:
            return subject
        if context["intent"] == "category":
            category = context["category"] or "that"
            return f"{category} from {context['residual']}" if context["residual"] else category
        return context["residual"] or slots.get("topic") or slots.get("query")

    @staticmethod
    def raw_utterance(handler_input) -> str | None:
        intent = AlexaRequest.get_intent_name(handler_input)
        if intent == "PlayLatestContentIntent":
            values = [
                AlexaRequest.get_slot_value(handler_input, name) for name in ("topic", "format")
            ]
            return " ".join(
                ["latest", *(value.strip() for value in values if value and value.strip())]
            )
        priority = ConfirmationPolicy.SLOT_PRIORITY.get(
            intent, ConfirmationPolicy.DEFAULT_SLOT_PRIORITY
        )
        return next(
            (
                value.strip()
                for name in priority
                if (value := AlexaRequest.get_slot_value(handler_input, name)) and value.strip()
            ),
            None,
        )

    @staticmethod
    def search_params(nlp: dict | None) -> dict | None:
        if not nlp or not nlp.get("intent"):
            return None
        slots = nlp.get("slots") or {}
        names = (
            "category",
            "topic",
            "creatorQuery",
            "creator",
            "organizationQuery",
            "organization",
            "publicationSourceQuery",
            "city",
            "placeName",
            "residualQuery",
        )
        parts = list(dict.fromkeys(str(slots[name]) for name in names if slots.get(name)))
        return {
            "intent": nlp["intent"],
            "query": " ".join(parts),
            "slots": slots,
            "resolution": ResolutionBuilder.build(nlp, nlp.get("confirmationLabel") or ""),
        }

    @staticmethod
    def clear_pending(attrs: dict) -> None:
        attrs.pop("_pendingConfirmation", None)
        attrs.pop("_resolverClarification", None)

    @staticmethod
    def _skip_confirmation(nlp: dict) -> bool:
        slots = nlp.get("slots") or {}
        return bool(
            ConfirmationPolicy.has_pending_ambiguity(nlp)
            or nlp.get("directDiscoveryRequest")
            or (nlp.get("intent") == "creator" and slots.get("genericCreatorRequest"))
            or (nlp.get("intent") == "organization" and slots.get("genericOrganizationRequest"))
        )

    @staticmethod
    def _clarification(nlp: dict, raw: str | None) -> dict | None:
        if nlp.get("publicationSourceRequired"):
            return {
                "speech": "Which publication, creator, or organization would you like?",
                "reprompt": "Please say the name of a publication, creator, or organization.",
                "elicitSlot": "publicationSourceQuery",
            }
        if ConfirmationPolicy.requires_clarification(nlp, raw):
            return {
                "speech": "Sorry, I didn't catch that. Please say your request again.",
                "reprompt": "Please say your request again.",
            }
        return None

    @staticmethod
    def _eligible(handler_input, nlp: dict | None) -> bool:
        if RequestContext.request(handler_input).get(DialogConstants.VALIDATION_FAILURE):
            return False
        return bool(
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input)
            and isinstance(nlp, dict)
            and nlp.get("intent") in ConfirmationPolicy.RESOLVED_INTENTS
            and (not nlp.get("status") or nlp.get("status") == "resolved")
        )

    @staticmethod
    def apply(handler_input) -> None:
        attrs = RequestContext.request(handler_input)
        nlp = attrs.get("_nlp")
        if not ConfirmationPolicy._eligible(handler_input, nlp):
            return
        if ConfirmationPolicy._skip_confirmation(nlp):
            ConfirmationPolicy.clear_pending(attrs)
            RequestContext.replace_request(handler_input, attrs)
            return
        raw = ConfirmationPolicy.raw_utterance(handler_input)
        clarification = ConfirmationPolicy._clarification(nlp, raw)
        confirm_text = ConfirmationPolicy.confirmation_speech(nlp)
        if clarification or not confirm_text:
            attrs["_resolverClarification"] = clarification or {
                "speech": "Sorry, I didn't catch that. Please say your request again.",
                "reprompt": "Please say your request again.",
            }
            attrs.pop("_pendingConfirmation", None)
            RequestContext.replace_request(handler_input, attrs)
            return
        search_params = ConfirmationPolicy.search_params(nlp) or {}
        search_params["confirmText"] = confirm_text
        if search_params.get("resolution"):
            search_params["resolution"]["confirmationLabel"] = confirm_text
        search_params["alternatives"] = nlp.get("alternatives") or []
        search_params["ambiguityResolution"] = bool(nlp.get("ambiguityResolution"))
        if search_params["ambiguityResolution"]:
            search_params["ambiguityCandidateName"] = next(
                (
                    str(entity.get("canonicalValue") or "").strip()
                    for entity in nlp.get("entities") or []
                    if entity.get("canonicalValue")
                ),
                confirm_text,
            )
        attrs["_pendingConfirmation"] = search_params
        RequestContext.replace_request(handler_input, attrs)
