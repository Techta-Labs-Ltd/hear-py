from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.models.resolver import ResolutionBuilder
from src.utils.filters import SearchFilterUtils
from src.utils.search_payload import SearchPayload


@dataclass(frozen=True, slots=True)
class ConfirmationDecision:
    kind: Literal["none", "clear", "clarify", "confirm"] = "none"
    pending: dict | None = None
    clarification: dict | None = None

    def __post_init__(self) -> None:
        if self.kind == "confirm" and not isinstance(self.pending, dict):
            raise ValueError("confirmation decision requires pending data")
        if self.kind == "clarify" and not isinstance(self.clarification, dict):
            raise ValueError("clarification decision requires clarification data")
        if self.kind in {"none", "clear"} and (
            self.pending is not None or self.clarification is not None
        ):
            raise ValueError("empty confirmation decisions cannot carry data")


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
            "ClarifySelectionIntent",
            "ChooseSourceKindIntent",
            "OpenDiscoveryIntent",
            "CarrierlessDiscoveryIntent",
            "PlayContentIntent",
            "SearchContentIntent",
            "SearchCreatorIntent",
            "SelectCreatorCityIntent",
            "PlayByOrganizationIntent",
            "SearchOrganizationIntent",
            "SelectOrganizationIntent",
            "PlayPublicationIntent",
            "SelectPublicationSourceIntent",
            "SearchPublicationIntent",
            "TownCaptureIntent",
            "BrowseContentIntent",
            "BrowseByCategoryIntent",
            "WhatsTrendingIntent",
            "PlayLocalIntent",
            "PlayRecommendationIntent",
        }
    )
    SLOT_PRIORITY = {
        "ClarifySelectionIntent": ("selection",),
        "ChooseSourceKindIntent": ("sourceKind", "publicationSort"),
        "OpenDiscoveryIntent": ("searchQuery",),
        "CarrierlessDiscoveryIntent": ("discoveryQuery", "topic"),
        "SearchContentIntent": ("searchQuery",),
        "SearchCreatorIntent": ("searchQuery",),
        "SearchOrganizationIntent": ("searchQuery",),
        "SearchPublicationIntent": ("searchQuery",),
        "SelectCreatorCityIntent": ("cityQuery",),
        "PlayByOrganizationIntent": (
            "organizationQuery",
            "topic",
            "creatorQuery",
            "listPickPhrase",
            "category",
            "feedbackPhrase",
        ),
        "SelectOrganizationIntent": (
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
        "SelectPublicationSourceIntent": (
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
        "selection",
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
            "publication": slots.get("publicationName")
            or slots.get("publicationSourceQuery"),
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
            return SearchPayload.resolved_request_label(slots, source)
        has_subject = bool(context["category"] or slots.get("tags") or context["residual"])
        if intent in {"category", "general"} and has_subject:
            return SearchPayload.resolved_request_label(slots)
        if intent == "search" and context["city"]:
            return SearchPayload.resolved_request_label(slots)
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
            return (
                f"{latest}{category} in your community"
                if category
                else "content from your community"
            )
        if intent == "trending":
            suffix = f" in {category}" if category else ""
            suffix += f" near {city}" if city else ""
            return f"what's trending{suffix}" if suffix else "what's trending right now"
        if intent == "browse":
            if category and city:
                return f"new {category} near {city}"
            if category or city:
                return f"new in {category}" if category else f"what's new near {city}"
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
            subject = SearchPayload.resolved_request_label(slots)
            prefix = (
                "the latest content on " if subject.startswith("the latest ") else "content on "
            )
            return prefix + subject.removeprefix("the latest ")
        if nlp.get("confirmationLabel"):
            return str(nlp["confirmationLabel"])
        resolved_subject = ConfirmationPolicy._resolved_subject(context)
        discovery_subject = ConfirmationPolicy._discovery_subject(context)
        source_subject = ConfirmationPolicy._source_subject(context)
        selected_subject = resolved_subject or discovery_subject or source_subject
        if selected_subject:
            return selected_subject
        if context["intent"] == "category":
            category = context["category"] or "that"
            return f"{category} from {context['residual']}" if context["residual"] else category
        return context["residual"] or slots.get("topic") or slots.get("query")

    @staticmethod
    def raw_utterance(alexa_intent: str | None, slot_values: dict | None) -> str | None:
        values: dict = slot_values if isinstance(slot_values, dict) else {}
        if alexa_intent == "PlayLatestContentIntent":
            topic_format = (values.get("topic"), values.get("format"))
            latest_values = [
                value for value in topic_format if isinstance(value, str) and value.strip()
            ]
            return " ".join(["latest", *(value.strip() for value in latest_values)])
        priority = (
            ConfirmationPolicy.SLOT_PRIORITY.get(
                alexa_intent, ConfirmationPolicy.DEFAULT_SLOT_PRIORITY
            )
            if alexa_intent
            else ConfirmationPolicy.DEFAULT_SLOT_PRIORITY
        )
        return next(
            (
                value.strip()
                for name in priority
                if isinstance((value := values.get(name)), str) and value.strip()
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
    def _skip_confirmation(nlp: dict) -> bool:
        slots = nlp.get("slots") or {}
        return bool(
            ConfirmationPolicy.has_pending_ambiguity(nlp)
            or (
                nlp.get("ambiguityResolution")
                and nlp.get("intent") == "publication"
            )
            or slots.get("unresolvedReferences")
            or nlp.get("directDiscoveryRequest")
            or (nlp.get("intent") == "creator" and slots.get("genericCreatorRequest"))
            or (nlp.get("intent") == "organization" and slots.get("genericOrganizationRequest"))
            or (
                nlp.get("intent") == "publication"
                and slots.get("genericPublicationRequest")
            )
        )

    @staticmethod
    def _clarification(nlp: dict, raw: str | None) -> dict | None:
        if ConfirmationPolicy.requires_clarification(nlp, raw):
            return {
                "speech": "Sorry, I didn't catch that. Please say your request again.",
                "reprompt": "Please say your request again.",
            }
        return None

    @staticmethod
    def _eligible(
        nlp: dict | None,
        *,
        request_type: str | None,
        alexa_intent: str | None,
        validation_failed: bool,
    ) -> bool:
        if validation_failed:
            return False
        return bool(
            request_type == "IntentRequest"
            and alexa_intent
            and isinstance(nlp, dict)
            and nlp.get("intent") in ConfirmationPolicy.RESOLVED_INTENTS
            and (not nlp.get("status") or nlp.get("status") == "resolved")
        )

    @staticmethod
    def decide(
        nlp: dict | None,
        *,
        request_type: str | None,
        alexa_intent: str | None,
        raw_utterance: str | None,
        validation_failed: bool,
    ) -> ConfirmationDecision:
        if not ConfirmationPolicy._eligible(
            nlp,
            request_type=request_type,
            alexa_intent=alexa_intent,
            validation_failed=validation_failed,
        ):
            return ConfirmationDecision()
        resolved_nlp: dict = nlp if isinstance(nlp, dict) else {}
        if ConfirmationPolicy._skip_confirmation(resolved_nlp):
            return ConfirmationDecision(kind="clear")
        clarification = ConfirmationPolicy._clarification(resolved_nlp, raw_utterance)
        confirm_text = ConfirmationPolicy.confirmation_speech(resolved_nlp)
        if clarification or not confirm_text:
            return ConfirmationDecision(
                kind="clarify",
                clarification=clarification
                or {
                    "speech": "Sorry, I didn't catch that. Please say your request again.",
                    "reprompt": "Please say your request again.",
                },
            )
        search_params = ConfirmationPolicy.search_params(resolved_nlp) or {}
        search_params["confirmText"] = confirm_text
        resolution = search_params.get("resolution")
        if isinstance(resolution, dict):
            resolution["confirmationLabel"] = confirm_text
        alternatives = resolved_nlp.get("alternatives")
        search_params["alternatives"] = alternatives if isinstance(alternatives, list) else []
        search_params["ambiguityResolution"] = bool(resolved_nlp.get("ambiguityResolution"))
        if search_params["ambiguityResolution"]:
            entities = resolved_nlp.get("entities")
            entity_values = entities if isinstance(entities, list) else []
            search_params["ambiguityCandidateName"] = next(
                (
                    str(entity.get("canonicalValue") or "").strip()
                    for entity in entity_values
                    if isinstance(entity, dict) and entity.get("canonicalValue")
                ),
                confirm_text,
            )
        return ConfirmationDecision(kind="confirm", pending=search_params)
