from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

RESOLVER_URL = "https://resolver.hear.media"
DEFAULT_COUNTRY_CODE = "gb"
DEFAULT_TIMEOUT_MS = 2000


class ResolverUnavailable(RuntimeError):
    """The resolver did not return a usable response."""


@dataclass(frozen=True)
class ResolvedEntity:
    entity_type: str
    entity_id: str
    canonical_value: str
    original_text: str
    confidence: float
    method: str
    start: int
    end: int
    latitude: float | None = None
    longitude: float | None = None
    country_code: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ResolvedEntity:
        required = (
            "entityType", "entityId", "canonicalValue", "originalText",
            "confidence", "method", "start", "end",
        )
        if any(key not in payload for key in required):
            raise ResolverUnavailable("resolver entity contract is invalid")
        try:
            return cls(
                entity_type=str(payload["entityType"]),
                entity_id=str(payload["entityId"]),
                canonical_value=str(payload["canonicalValue"]),
                original_text=str(payload["originalText"]),
                confidence=float(payload["confidence"]),
                method=str(payload["method"]),
                start=int(payload["start"]),
                end=int(payload["end"]),
                latitude=_optional_float(payload.get("latitude")),
                longitude=_optional_float(payload.get("longitude")),
                country_code=_optional_string(payload.get("countryCode")),
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

    def to_alexa_payload(self) -> dict[str, Any]:
        """Map canonical backend entities to the existing Alexa search contract."""
        slots = dict(self.slots)
        filters: dict[str, Any] = {}
        facet_slots = {
            "creator": ("creatorIds", "creatorName"),
            "organization": ("organizationIds", "organizationName"),
            "publication": ("publicationIds", "publicationName"),
        }
        for entity_type, (ids_key, name_key) in facet_slots.items():
            discovered = self.entities_of_type(entity_type)
            if discovered:
                slots[ids_key] = [entity.entity_id for entity in discovered]
                slots[name_key] = discovered[0].canonical_value
                filters[ids_key] = list(slots[ids_key])

        categories = self.entities_of_type("category")
        if categories:
            slots["category"] = categories[0].entity_id
            slots["categoryName"] = categories[0].canonical_value
            filters["categorySlugs"] = [entity.entity_id for entity in categories]
        tags = self.entities_of_type("tag")
        if tags:
            slots["tags"] = [entity.entity_id for entity in tags]
            slots["tagNames"] = [entity.canonical_value for entity in tags]
            filters["tags"] = list(slots["tags"])

        locations = self.entities_of_type("location")
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

        for key in ("publishedFrom", "publishedTo"):
            if slots.get(key) is not None:
                filters[key] = slots[key]
        if slots.get("isPublication") or self.intent == "publication":
            slots["isPublication"] = True
            filters["isPublication"] = True
        slots.setdefault("residualQuery", "")
        slots.setdefault("latest", slots.get("sort") == "latest")
        slots.setdefault("isRecommended", False)
        slots.setdefault("unresolvedReferences", [])
        # Entity discovery is authoritative. Overlapping creator/publication/
        # category/tag matches are independent facets, not client-made ambiguity.
        slots["ambiguousReferences"] = []
        search_plan = {
            "query": slots["residualQuery"],
            "sort": slots.get("sort") or "relevance",
            "filter": filters,
        }
        slots["searchPlan"] = search_plan
        return {
            "status": self.status,
            "intent": self.intent,
            "entities": [entity.to_payload() for entity in self.entities],
            "slots": slots,
            "ambiguities": list(self.ambiguities),
            "timingMs": self.timing_ms,
            "resolution": resolution,
            "confidence": "high",
            "searchPayload": search_plan,
        }


class ResolverClient:
    def __init__(
        self,
        *,
        host: str,
        api_key: str,
        default_country: str = "gb",
        timeout_ms: int = 2000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._default_country = default_country
        self._timeout = httpx.Timeout(max(timeout_ms, 1) / 1000.0)
        self._transport = transport

    async def resolve(
        self,
        utterance: str,
        *,
        alexa_user_id: str | None = None,
        timezone: str = "Europe/London",
        country_code: str | None = None,
    ) -> ResolverResult:
        body: dict[str, Any] = {
            "utterance": utterance,
            "timezone": timezone,
            "country_code": country_code or self._default_country,
        }
        if alexa_user_id:
            body["alexaUserId"] = alexa_user_id
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._host}/resolve",
                    json=body,
                    headers={"x-api-key": self._api_key},
                )
            if not 200 <= response.status_code < 300:
                raise ResolverUnavailable(f"resolver returned HTTP {response.status_code}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise ResolverUnavailable("resolver response must be an object")
            return ResolverResult.from_payload(payload)
        except ResolverUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Resolver request failed error=%s", type(exc).__name__)
            raise ResolverUnavailable("resolver request failed") from exc


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _configured_client() -> ResolverClient:
    return ResolverClient(
        host=RESOLVER_URL,
        api_key=settings.HEAR_API_KEY,
        default_country=DEFAULT_COUNTRY_CODE,
        timeout_ms=DEFAULT_TIMEOUT_MS,
    )


async def resolve_utterance(
    utterance: str,
    *,
    alexa_user_id: str | None = None,
    timezone: str = "Europe/London",
    country_code: str | None = None,
) -> dict[str, Any]:
    result = await _configured_client().resolve(
        utterance,
        alexa_user_id=alexa_user_id,
        timezone=timezone,
        country_code=country_code,
    )
    return result.to_alexa_payload()
