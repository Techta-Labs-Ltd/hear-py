from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.utils.search_payload import normalize_search_payload

PrincipalType = Literal[
    "linked_person",
    "linked_household",
    "anonymous_person",
    "anonymous_installation",
]

PERSISTED_FIELDS = frozenset({
    "_persistenceVersion",
    "activeDialog",
    "activePlayback",
    "answeredFeedbackKeys",
    "awaitingCommunityPlayback",
    "awaitingContinueAfterFlag",
    "awaitingFeedback",
    "awaitingFollow",
    "awaitingLocationConfirm",
    "awaitingReportDecision",
    "awaitingResume",
    "awaitingSearchConfirmation",
    "currentPlaybackSpeeds",
    "deviceCountryCode",
    "devicePostalCode",
    "excludedSuggestions",
    "feedbackAskedForToken",
    "feedbackAskedTokens",
    "feedbackCandidates",
    "publicationFeedbackProgress",
    "feedbackCategory",
    "feedbackContentId",
    "feedbackContentTitle",
    "feedbackCreator",
    "feedbackCreatorId",
    "feedbackGivenTokens",
    "feedbackHistory",
    "feedbackPromptText",
    "feedbackReminderAlertToken",
    "firstLaunchedAt",
    "followedCreators",
    "pendingFollowSource",
    "fullName",
    "givenName",
    "lastCompletedSource",
    "lastLaunchedAt",
    "lastLatestSourceOfferContentId",
    "lastOffsetMs",
    "lastToken",
    "latitude",
    "launchCount",
    "listModeActive",
    "listenerId",
    "listenerProfileResolvedAt",
    "listenerProfileSkipUntil",
    "listenerSyncedAt",
    "listeningPattern",
    "locality",
    "localityResolvedAt",
    "locationSource",
    "longitude",
    "onboardingComplete",
    "onboardingRetries",
    "onboardingStage",
    "onboardingTownAttempts",
    "onboardingTownResolverFailures",
    "pendingAmbiguity",
    "pendingFeedback",
    "pendingLatestSource",
    "pendingLocationConfirm",
    "pendingResolution",
    "pendingSuggestions",
    "playCount",
    "playHistory",
    "playbackQueue",
    "playbackSpeed",
    "preparedNextContent",
    "reportContext",
    "reportHistory",
    "suggestionIndex",
    "userAddress",
    "userCity",
    "userCountry",
    "userEmail",
    "userName",
    "userState",
})

@dataclass(frozen=True)
class IdentityContext:
    principal_type: PrincipalType
    alexa_user_id: str | None = None
    person_id: str | None = None
    device_id: str | None = None
    access_token: str | None = None
    is_linked: bool = False


class ResolverUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedEntity:
    entity_type: str
    entity_id: str
    canonical_value: str
    original_text: str
    confidence: int
    method: str
    start: int
    end: int
    latitude: float | None = None
    longitude: float | None = None
    country_code: str | None = None
    location_role: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ResolvedEntity:
        required = (
            "entityType", "entityId", "canonicalValue", "originalText",
            "confidence", "method", "start", "end",
        )
        if any(key not in payload for key in required):
            raise ResolverUnavailable("resolver entity contract is invalid")
        try:
            confidence = payload["confidence"]
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, int)
                or not 1 <= confidence <= 100
            ):
                raise ValueError("confidence must be an integer from 1 to 100")
            return cls(
                entity_type=str(payload["entityType"]),
                entity_id=str(payload["entityId"]),
                canonical_value=str(payload["canonicalValue"]),
                original_text=str(payload["originalText"]),
                confidence=confidence,
                method=str(payload["method"]),
                start=int(payload["start"]),
                end=int(payload["end"]),
                latitude=_optional_float(payload.get("latitude")),
                longitude=_optional_float(payload.get("longitude")),
                country_code=_optional_string(payload.get("countryCode")),
                location_role=_optional_string(payload.get("locationRole")),
            )
        except (TypeError, ValueError) as exc:
            raise ResolverUnavailable("resolver entity contract is invalid") from exc

    def to_payload(self) -> dict[str, Any]:
        return {
            "entityType": self.entity_type,
            "entityId": self.entity_id,
            "canonicalValue": self.canonical_value,
            "originalText": self.original_text,
            "confidence": self.confidence,
            "method": self.method,
            "start": self.start,
            "end": self.end,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "countryCode": self.country_code,
            "locationRole": self.location_role,
        }


@dataclass(frozen=True)
class ResolverResult:
    status: str
    intent: str
    entities: tuple[ResolvedEntity, ...]
    slots: dict[str, Any]
    ambiguities: tuple[dict[str, Any], ...]
    timing_ms: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ResolverResult:
        required = ("status", "intent", "entities", "slots", "ambiguities", "timingMs")
        if any(key not in payload for key in required):
            raise ResolverUnavailable("resolver response contract is invalid")
        if not isinstance(payload["entities"], list):
            raise ResolverUnavailable("resolver entities must be a list")
        if not isinstance(payload["slots"], dict):
            raise ResolverUnavailable("resolver slots must be an object")
        if not isinstance(payload["ambiguities"], list):
            raise ResolverUnavailable("resolver ambiguities must be a list")
        try:
            return cls(
                status=str(payload["status"]),
                intent=str(payload["intent"]),
                entities=tuple(ResolvedEntity.from_payload(item) for item in payload["entities"]),
                slots=dict(payload["slots"]),
                ambiguities=tuple(dict(item) for item in payload["ambiguities"]),
                timing_ms=float(payload["timingMs"]),
            )
        except (TypeError, ValueError) as exc:
            raise ResolverUnavailable("resolver response contract is invalid") from exc

    def entities_of_type(self, entity_type: str) -> tuple[ResolvedEntity, ...]:
        return tuple(entity for entity in self.entities if entity.entity_type == entity_type)

    def fully_matched_entities_of_type(
        self, entity_type: str,
    ) -> tuple[ResolvedEntity, ...]:
        """Return resolver facets with the maximum 1-100 confidence score."""
        return tuple(
            entity
            for entity in self.entities_of_type(entity_type)
            if entity.confidence == 100
        )

    def to_alexa_payload(self, *, prefer_location: bool = False) -> dict[str, Any]:
        slots = dict(self.slots)
        ambiguities = []
        for ambiguity in self.ambiguities:
            candidates = []
            for candidate in ambiguity.get("candidates") or []:
                name = str(
                    candidate.get("name")
                    or candidate.get("canonicalValue")
                    or ""
                ).strip()
                entity_id = candidate.get("id") or candidate.get("entityId")
                entity_type = candidate.get("type") or candidate.get("entityType")
                if name and entity_id and entity_type:
                    candidates.append({
                        "type": str(entity_type),
                        "id": str(entity_id),
                        "name": name,
                    })
            if candidates:
                ambiguities.append({
                    "phrase": str(ambiguity.get("phrase") or ""),
                    "candidates": candidates,
                })
        filters: dict[str, Any] = {}
        facet_slots = {
            "creator": ("creatorIds", "creatorName"),
            "organization": ("organizationIds", "organizationName"),
            "publication": ("publicationIds", "publicationName"),
        }
        for entity_type, (ids_key, name_key) in facet_slots.items():
            discovered = self.fully_matched_entities_of_type(entity_type)
            if discovered:
                slots[ids_key] = [entity.entity_id for entity in discovered]
                slots[name_key] = discovered[0].canonical_value
                filters[ids_key] = list(slots[ids_key])

        categories = self.fully_matched_entities_of_type("category")
        if categories:
            category_slugs = [entity.entity_id for entity in categories]
            slots["category"] = categories[0].entity_id
            slots["categoryName"] = categories[0].canonical_value
            slots["categorySlugs"] = category_slugs
            filters["categorySlugs"] = category_slugs
        tags = self.fully_matched_entities_of_type("tag")
        if not categories and len(tags) >= 2:
            slots["tags"] = [entity.entity_id for entity in tags]
            slots["tagNames"] = [entity.canonical_value for entity in tags]
            filters["tags"] = list(slots["tags"])

        source_entities = tuple(
            entity
            for entity_type in facet_slots
            for entity in self.fully_matched_entities_of_type(entity_type)
        )
        location_slot_keys = (
            "city", "placeName", "countryCode", "latitude", "longitude",
            "isLocal",
        )
        for key in location_slot_keys:
            slots.pop(key, None)
        all_locations = (
            ()
            if self.intent == "category"
            else self.fully_matched_entities_of_type("location")
        )
        locations = all_locations if prefer_location else tuple(
            location
            for location in all_locations
            if not any(
                max(location.start, source.start) < min(location.end, source.end)
                for source in source_entities
            )
        )
        resolution = {"match": None, "candidates": []}
        if locations:
            location = locations[0]
            match = {
                "city": location.canonical_value,
                "locality": location.canonical_value,
                "countryCode": location.country_code,
                "latitude": location.latitude,
                "longitude": location.longitude,
                "confidence": location.confidence,
                "method": location.method,
            }
            resolution["match"] = match
            slots.update({
                "city": location.canonical_value,
                "placeName": location.canonical_value,
                "countryCode": location.country_code,
                "latitude": location.latitude,
                "longitude": location.longitude,
                "isLocal": True,
            })
            filters.update({
                key: value for key, value in {
                    "city": location.canonical_value,
                    "countryCode": location.country_code,
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                }.items() if value is not None
            })
        elif all_locations and source_entities:
            # A place name can also be the identifying part of a source name
            # (for example "Wakefield Talking Newspaper"). When both resolver
            # entities cover the same words, applying source AND city filters
            # incorrectly removes every catalogue result.
            for key in location_slot_keys:
                slots.pop(key, None)

        for key in ("publishedFrom", "publishedTo"):
            if slots.get(key) is not None:
                filters[key] = slots[key]
        if slots.get("isPublication") or (
            self.intent == "publication" and not slots.get("publicationIds")
        ):
            slots["isPublication"] = True
            filters["isPublication"] = True
        slots.setdefault("residualQuery", "")
        slots.setdefault("latest", slots.get("sort") == "latest")
        slots.setdefault("isRecommended", False)
        slots.setdefault("unresolvedReferences", [])
        slots["ambiguousReferences"] = list(ambiguities)
        search_plan = normalize_search_payload({
            "query": slots["residualQuery"],
            "sort": slots.get("sort"),
            "filter": filters,
        })
        slots["searchPlan"] = search_plan
        return {
            "status": self.status,
            "intent": self.intent,
            "entities": [
                entity.to_payload()
                for entity in self.entities
                if entity.confidence == 100
                and not (
                    self.intent == "category"
                    and entity.entity_type == "location"
                )
            ],
            "slots": slots,
            "ambiguities": list(ambiguities),
            "timingMs": self.timing_ms,
            "resolution": resolution,
            "confidence": "high",
            "searchPayload": search_plan,
        }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


TRENDING_HINTS = {
    "what's trending", "whats trending", "what is trending", "what's popular",
    "what is popular", "what's hot", "what is hot", "trending", "popular",
    "what are people listening to", "what is everyone listening to", "top content",
    "show me trending", "show me what's trending", "read me the trending list",
    "what's trending right now", "what's on trend", "trending audio",
    "popular picks", "most popular right now",
}


LOCAL_HINTS = {
    "local", "nearby", "near me", "near here", "local content",
    "what's local", "whats local", "what is local", "local community",
    "community", "around me", "around here", "content near me",
    "local recordings", "nearby recordings", "local audio",
    "nearby audio", "what's happening near me", "my city", "my town",
    "from my city", "from my town", "my community", "from my community",
    "something from my community", "play community", "play community content",
    "what's happening locally", "whats happening locally", "locally",
}


BROWSE_HINTS = {
    "what's on", "whats on", "what's available", "whats available",
    "what have you got", "what's new", "whats new", "any new content",
    "what's been published", "what do you recommend", "recommend something",
    "any new episodes", "what's fresh", "whats fresh", "what dropped today",
    "let me hear what's new", "show me what you've got", "browse",
}


FEEDBACK_SKIP_HINTS = {
    "skip", "never mind", "no thanks", "ignore that", "skip feedback",
    "move on", "don't bother", "i don't want to rate", "no comment", "pass",
    "skip the rating", "carry on", "i'd rather not say", "just play the next one",
    "whatever", "doesn't matter", "skip it", "not bothered", "can't be bothered",
}


ALEXA_TO_NLP = {
    "PlayContentIntent": "general",
    "PlayLatestContentIntent": "general",
    "PlayByCreatorIntent": "creator",
    "PlayByOrganizationIntent": "organization",
    "PlayPublicationIntent": "publication",
    "WhatsTrendingIntent": "trending",
    "PlayRecommendationIntent": "trending",
    "PlayLocalIntent": "local",
    "BrowseContentIntent": "browse",
    "ShowMoreBrowseIntent": "show_more",
    "SetLocationIntent": "location_set",
    "TownCaptureIntent": "town_capture",
    "ClarifySelectionIntent": "general",
    "AMAZON.FallbackIntent": "general",
}
