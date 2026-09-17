from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from src.models.entity_ranker import EntityRanker
from src.utils.filters import SearchFilterUtils


class ResolverUnavailable(RuntimeError):
    pass


class UtteranceResolver(Protocol):
    async def resolve_utterance(
        self,
        utterance: str,
        *,
        alexa_user_id: str | None = None,
        listener_id: str | None = None,
        prefer_location: bool = False,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        ...


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
            "requestedLocation": bool(
                nlp.get("requestedLocation")
                or slots.get("city")
                or slots.get("placeName")
            ),
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
    county: str | None = None
    location_type: str | None = None

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
                county=ResolverResult._optional_string(payload.get("county")),
                location_type=ResolverResult._optional_string(payload.get("locationType")),
            )
        except (TypeError, ValueError) as exc:
            raise ResolverUnavailable("resolver entity contract is invalid") from exc

    def to_payload(self) -> dict[str, Any]:
        payload = {
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
        if self.county is not None:
            payload["county"] = self.county
        if self.location_type is not None:
            payload["locationType"] = self.location_type
        return payload


@dataclass(frozen=True)
class ResolverResult:
    status: str
    intent: str
    entities: tuple[ResolvedEntity, ...]
    slots: dict[str, Any]
    ambiguities: tuple[dict[str, Any], ...]
    timing_ms: float
    resolution_id: str | None = None

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
                resolution_id=ResolverResult._optional_string(payload.get("resolutionId")),
            )
        except (TypeError, ValueError) as exc:
            raise ResolverUnavailable("resolver response contract is invalid") from exc

    def entity_ranking(self):
        return EntityRanker.rank(self.entities)

    def ranked_entities(self) -> tuple[ResolvedEntity, ...]:
        ranking = self.entity_ranking()
        return () if ranking.ambiguous else ranking.accepted

    def entities_of_type(self, entity_type: str) -> tuple[ResolvedEntity, ...]:
        return tuple(entity for entity in self.ranked_entities() if entity.entity_type == entity_type)
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
                    {
                        "phrase": str(ambiguity.get("phrase") or ""),
                        "candidates": EntityRanker.collapse_ambiguity_candidates(candidates),
                    }
                )
                continue
            candidate = ResolverResult._ambiguity_candidate(ambiguity)
            if candidate:
                flat_candidates.append(candidate)
                flat_phrase = flat_phrase or str(ambiguity.get("phrase") or "").strip()
        if flat_candidates:
            ambiguities.append(
                {
                    "phrase": flat_phrase or ResolverResult._fallback_query(original_utterance),
                    "candidates": EntityRanker.collapse_ambiguity_candidates(flat_candidates),
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
        sources: list[ResolvedEntity] = []
        for entity_type, (ids_key, name_key) in facet_slots.items():
            entities = self.entities_of_type(entity_type)
            sources.extend(entities)
            if entities:
                slots[ids_key] = [entity.entity_id for entity in entities]
                slots[name_key] = entities[0].canonical_value
                filters[ids_key] = list(slots[ids_key])
        categories = self.entities_of_type("category")
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
        tags = self.entities_of_type("tag")
        if tags:
            slots["tags"] = [entity.entity_id for entity in tags]
            slots["tagNames"] = [entity.canonical_value for entity in tags]
            filters["tags"] = list(slots["tags"])
        return filters, tuple(sources)
    def _ranking_ambiguity_payload(self) -> list[dict]:
        ranking = self.entity_ranking()
        if not ranking.ambiguous:
            return []
        return [
            {
                "phrase": ranking.ambiguous[0].original_text,
                "candidates": [
                    {
                        "type": entity.entity_type,
                        "id": entity.entity_id,
                        "name": entity.canonical_value,
                    }
                    for entity in ranking.ambiguous
                ],
            }
        ]

    @staticmethod
    def _overlaps_source(location: ResolvedEntity, sources: tuple[ResolvedEntity, ...]) -> bool:
        return any(
            max(location.start, source.start) < min(location.end, source.end)
            for source in sources
        )

    def _location_payload(
        self,
        slots: dict,
        filters: dict,
        sources: tuple[ResolvedEntity, ...],
        prefer_location: bool,
    ) -> dict:
        keys = (
            "city",
            "placeName",
            "countryCode",
            "latitude",
            "longitude",
            "isLocal",
            "county",
            "locationType",
        )
        for key in keys:
            slots.pop(key, None)
        locations = self.entities_of_type("location")
        if not prefer_location:
            locations = tuple(
                location
                for location in locations
                if not self._overlaps_source(location, sources)
            )
        if not locations:
            return {"match": None, "candidates": []}
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
        if location.county is not None:
            match["county"] = location.county
        if location.location_type is not None:
            match["locationType"] = location.location_type
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
        if location.county is not None:
            slots["county"] = location.county
        if location.location_type is not None:
            slots["locationType"] = location.location_type
        filters.update(
            {
                key: value
                for key, value in {
                    "city": location.canonical_value,
                    "countryCode": location.country_code,
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "county": location.county,
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
        defaults: dict[str, object] = {
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
        ranking = self.entity_ranking()
        ambiguities = self._ambiguity_payload(original_utterance)
        ambiguities.extend(self._ranking_ambiguity_payload())
        if ambiguities:
            filters: dict[str, Any] = {}
            resolution = {"match": None, "candidates": []}
        else:
            filters, sources = self._facet_payload(slots)
            resolution = self._location_payload(
                slots, filters, sources, prefer_location
            )
        slots["ambiguousReferences"] = list(ambiguities)
        if ranking.accepted or ambiguities:
            slots["residualQuery"] = ""
        search_plan = self._search_plan(slots, filters, original_utterance)
        if self.resolution_id:
            search_plan["resolutionId"] = self.resolution_id
        slots["searchPlan"] = search_plan
        accepted = () if ambiguities else ranking.accepted
        entities = [entity.to_payload() for entity in accepted]
        semantic_intent = ranking.primary.entity_type if ranking.primary else self.intent
        intent = "search" if self.intent in {"tag", "location"} else self.intent
        primary = ranking.primary.to_payload() if ranking.primary and not ambiguities else None
        secondary = [
            entity.to_payload()
            for entity in accepted
            if ranking.primary is None or entity != ranking.primary
        ]
        return {
            "status": "ambiguous" if ambiguities else self.status,
            "intent": intent,
            "resolverIntent": self.intent,
            "semanticIntent": semantic_intent,
            "resolutionId": self.resolution_id,
            "primaryEntity": primary,
            "secondaryEntities": secondary,
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
