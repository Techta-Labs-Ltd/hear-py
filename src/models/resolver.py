from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from src.constants.resolver import ResolverConstants
from src.utils.filters import SearchFilterUtils


class ResolverUnavailable(RuntimeError):
    pass


class ResolutionBuilder:
    __slots__ = ()

    @staticmethod
    def build(nlp: dict, confirmation_label: str, *, now: int | None = None) -> dict:
        timestamp = int(time.time()) if now is None else int(now)
        slots = nlp.get("slots") or {}
        payload = nlp.get("searchPayload") or slots.get("searchPlan") or {}
        return {
            "requestId": nlp.get("requestId") or str(uuid.uuid4()),
            "originalUtterance": nlp.get("originalUtterance") or "",
            "normalizedUtterance": nlp.get("normalizedUtterance") or "",
            "corrections": list(nlp.get("corrections") or []),
            "intent": nlp.get("intent") or "general",
            "confirmationLabel": confirmation_label,
            "searchPayload": SearchFilterUtils.normalize_search_payload(payload),
            "resolvedEntities": list(nlp.get("entities") or []),
            "alternatives": list(nlp.get("alternatives") or []),
            "createdAt": timestamp,
            "expiresAt": timestamp + 300,
        }


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
            "entityType",
            "entityId",
            "canonicalValue",
            "originalText",
            "confidence",
            "method",
            "start",
            "end",
        )
        if any((key not in payload for key in required)):
            raise ResolverUnavailable("resolver entity contract is invalid")
        try:
            confidence = payload["confidence"]
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, int)
                or (not 1 <= confidence <= 100)
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
                latitude=ResolverResult._optional_float(payload.get("latitude")),
                longitude=ResolverResult._optional_float(payload.get("longitude")),
                country_code=ResolverResult._optional_string(payload.get("countryCode")),
                location_role=ResolverResult._optional_string(payload.get("locationRole")),
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
        if any((key not in payload for key in required)):
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
                entities=tuple((ResolvedEntity.from_payload(item) for item in payload["entities"])),
                slots=dict(payload["slots"]),
                ambiguities=tuple((dict(item) for item in payload["ambiguities"])),
                timing_ms=float(payload["timingMs"]),
            )
        except (TypeError, ValueError) as exc:
            raise ResolverUnavailable("resolver response contract is invalid") from exc

    def entities_of_type(self, entity_type: str) -> tuple[ResolvedEntity, ...]:
        return tuple((entity for entity in self.entities if entity.entity_type == entity_type))

    def fully_matched_entities_of_type(self, entity_type: str) -> tuple[ResolvedEntity, ...]:
        """Return resolver facets with the maximum 1-100 confidence score."""
        return tuple(
            (entity for entity in self.entities_of_type(entity_type) if entity.confidence == 100)
        )

    def selected_entities_of_type(self, entity_type: str) -> tuple[ResolvedEntity, ...]:
        entities = self.entities_of_type(entity_type)
        if self.status == "resolved" and self.intent == entity_type:
            return entities
        return tuple(entity for entity in entities if entity.confidence == 100)

    @staticmethod
    def _ambiguity_candidate(candidate: dict) -> dict | None:
        entity_type = candidate.get("type") or candidate.get("entityType")
        entity_id = candidate.get("id") or candidate.get("entityId")
        name = str(candidate.get("name") or candidate.get("canonicalValue") or "").strip()
        if not entity_type or not entity_id or not name:
            return None
        return {"type": str(entity_type), "id": str(entity_id), "name": name}

    def _ambiguity_payload(self, original_utterance: str = "") -> list[dict]:
        ambiguities = []
        flat_candidates = []
        flat_phrase = ""
        for ambiguity in self.ambiguities:
            candidates = [
                normalized
                for candidate in ambiguity.get("candidates") or []
                if (normalized := ResolverResult._ambiguity_candidate(candidate))
            ]
            if candidates:
                ambiguities.append(
                    {"phrase": str(ambiguity.get("phrase") or ""), "candidates": candidates}
                )
                continue
            candidate = ResolverResult._ambiguity_candidate(ambiguity)
            if candidate:
                flat_candidates.append(candidate)
                flat_phrase = flat_phrase or str(ambiguity.get("phrase") or "").strip()
        if flat_candidates:
            matching_intent = [
                candidate
                for candidate in flat_candidates
                if candidate.get("type") == self.intent
            ]
            candidates = matching_intent or flat_candidates
            ambiguities.append(
                {
                    "phrase": flat_phrase or ResolverResult._fallback_query(original_utterance),
                    "candidates": candidates,
                }
            )
        return ambiguities

    def _facet_payload(self, slots: dict) -> tuple[dict, tuple[ResolvedEntity, ...]]:
        filters: dict[str, Any] = {}
        facet_slots = {
            "creator": ("creatorIds", "creatorName"),
            "organization": ("organizationIds", "organizationName"),
            "publication": ("publicationIds", "publicationName"),
        }
        sources = []
        for entity_type, (ids_key, name_key) in facet_slots.items():
            discovered = self.selected_entities_of_type(entity_type)
            sources.extend(discovered)
            if discovered:
                slots[ids_key] = [entity.entity_id for entity in discovered]
                slots[name_key] = discovered[0].canonical_value
                filters[ids_key] = list(slots[ids_key])
        categories = self.selected_entities_of_type("category")
        if categories:
            category_slugs = [entity.entity_id for entity in categories]
            slots.update(
                {
                    "category": categories[0].entity_id,
                    "categoryName": categories[0].canonical_value,
                    "categorySlugs": category_slugs,
                }
            )
            filters["categorySlugs"] = category_slugs
        tags = self.selected_entities_of_type("tag")
        if not categories and tags:
            slots["tags"] = [entity.entity_id for entity in tags]
            slots["tagNames"] = [entity.canonical_value for entity in tags]
            filters["tags"] = list(slots["tags"])
        return filters, tuple(sources)

    @staticmethod
    def _overlaps_source(location: ResolvedEntity, sources: tuple[ResolvedEntity, ...]) -> bool:
        return any(
            max(location.start, source.start) < min(location.end, source.end) for source in sources
        )

    def _credible_source_locations(self) -> tuple[ResolvedEntity, ...]:
        locations = self.entities_of_type("location")
        source_locations = tuple(
            entity
            for entity in locations
            if str(entity.location_role or "").casefold() == "source"
            and entity.confidence >= ResolverConstants.SOURCE_LOCATION_MIN_CONFIDENCE
        )
        if source_locations:
            return source_locations
        return tuple(
            entity
            for entity in locations
            if entity.confidence == 100
            and entity.location_role
            and entity.location_role.casefold() != "unspecified"
        )

    @staticmethod
    def _preferred_search_location(
        locations: tuple[ResolvedEntity, ...],
    ) -> ResolvedEntity | None:
        unique: dict[tuple[str, str], ResolvedEntity] = {}
        for location in locations:
            key = (
                str(location.country_code or "").casefold(),
                location.canonical_value.casefold(),
            )
            current = unique.get(key)
            if current is None or location.confidence > current.confidence:
                unique[key] = location
        candidates = tuple(unique.values())
        exact = tuple(location for location in candidates if location.confidence == 100)
        preferred = exact or candidates
        return preferred[0] if len(preferred) == 1 else None

    def _location_payload(
        self,
        slots: dict,
        filters: dict,
        sources: tuple[ResolvedEntity, ...],
        prefer_location: bool,
    ) -> dict:
        keys = ("city", "placeName", "countryCode", "latitude", "longitude", "isLocal")
        for key in keys:
            slots.pop(key, None)
        if self.intent == "category":
            all_locations = ()
        elif self.intent == "location":
            all_locations = self.selected_entities_of_type("location")
        elif prefer_location:
            all_locations = self.fully_matched_entities_of_type("location")
        else:
            all_locations = self._credible_source_locations()
        locations = (
            all_locations
            if prefer_location
            else tuple(
                location
                for location in all_locations
                if not ResolverResult._overlaps_source(location, sources)
            )
        )
        if not locations:
            return {"match": None, "candidates": []}
        location = (
            locations[0]
            if prefer_location or self.intent == "location"
            else ResolverResult._preferred_search_location(locations)
        )
        if location is None:
            return {"match": None, "candidates": []}
        match = {
            "city": location.canonical_value,
            "locality": location.canonical_value,
            "countryCode": location.country_code,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "confidence": location.confidence,
            "method": location.method,
        }
        slots.update(
            {
                "city": location.canonical_value,
                "placeName": location.canonical_value,
                "countryCode": location.country_code,
                "latitude": location.latitude,
                "longitude": location.longitude,
                "isLocal": True,
            }
        )
        filters.update(
            {
                key: value
                for key, value in {
                    "city": location.canonical_value,
                    "countryCode": location.country_code,
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                }.items()
                if value is not None
            }
        )
        return {"match": match, "candidates": []}

    def _search_plan(self, slots: dict, filters: dict, original_utterance: str) -> dict:
        for key in ("publishedFrom", "publishedTo"):
            if slots.get(key) is not None:
                filters[key] = slots[key]
        if slots.get("isPublication") or (
            self.intent == "publication" and not slots.get("publicationIds")
        ):
            slots["isPublication"] = True
            filters["isPublication"] = True
        defaults = {
            "residualQuery": "",
            "latest": slots.get("sort") == "latest",
            "isRecommended": False,
            "unresolvedReferences": [],
        }
        for key, value in defaults.items():
            slots.setdefault(key, value)
        if (
            not filters
            and not str(slots.get("residualQuery") or "").strip()
            and self.intent in {"search", "tag", "location"}
        ):
            fallback_query = ResolverResult._fallback_query(original_utterance)
            if fallback_query:
                slots["residualQuery"] = fallback_query
        return SearchFilterUtils.normalize_search_payload(
            {
                "query": slots["residualQuery"],
                "sort": slots.get("sort"),
                "filter": filters,
            }
        )

    def to_alexa_payload(
        self, *, prefer_location: bool = False, original_utterance: str = ""
    ) -> dict[str, Any]:
        slots = dict(self.slots)
        ambiguities = self._ambiguity_payload(original_utterance)
        filters, sources = self._facet_payload(slots)
        resolution = self._location_payload(slots, filters, sources, prefer_location)
        slots["ambiguousReferences"] = list(ambiguities)
        search_plan = self._search_plan(slots, filters, original_utterance)
        slots["searchPlan"] = search_plan
        accepted_entities = {
            (entity.entity_type, entity.entity_id)
            for entity_type in ("creator", "organization", "publication", "category", "tag")
            for entity in self.selected_entities_of_type(entity_type)
            if (
                entity.entity_type != "tag"
                or not self.selected_entities_of_type("category")
            )
        }
        if resolution.get("match"):
            accepted_entities.update(
                (entity.entity_type, entity.entity_id)
                for entity in self.entities_of_type("location")
                if entity.canonical_value == resolution["match"].get("city")
            )
        entities = [
            entity.to_payload()
            for entity in self.entities
            if (entity.entity_type, entity.entity_id) in accepted_entities
        ]
        intent = "search" if self.intent in {"tag", "location"} else self.intent
        return {
            "status": "ambiguous" if ambiguities else self.status,
            "intent": intent,
            "resolverIntent": self.intent,
            "entities": entities,
            "slots": slots,
            "ambiguities": list(ambiguities),
            "timingMs": self.timing_ms,
            "resolution": resolution,
            "confidence": "high",
            "searchPayload": search_plan,
        }

    @staticmethod
    def _fallback_query(original_utterance: str) -> str:
        query = str(original_utterance or "").strip()
        for _ in range(4):
            stripped = SearchFilterUtils.strip_conversational_topic_prefix(query)
            if stripped == query:
                break
            query = stripped
        return SearchFilterUtils.strip_search_sort_prefix(query)

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return None if value is None else str(value)
