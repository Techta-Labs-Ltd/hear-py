from __future__ import annotations

import re
from dataclasses import dataclass

from src.resolver.taxonomy import taxonomy_manager


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class LocationMatch:
    city: str
    country_code: str | None
    latitude: float | None
    longitude: float | None
    confidence: float
    method: str

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "locality": self.city,
            "countryCode": self.country_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "confidence": self.confidence,
            "method": self.method,
        }


def _resolved_entity_payload(entity) -> dict:
    metadata = entity.metadata or {}
    return LocationMatch(
        city=str(metadata.get("city") or entity.canonical_value),
        country_code=metadata.get("countryCode") or metadata.get("country_code"),
        latitude=_number(metadata.get("latitude", metadata.get("lat"))),
        longitude=_number(metadata.get("longitude", metadata.get("lng"))),
        confidence=float(entity.confidence),
        method=str(entity.method),
    ).to_dict()


def resolve_location_phrase(phrase: str, taxonomy_view=None) -> dict:
    """Resolve a town against the request's pinned taxonomy view."""
    snapshot = taxonomy_view or taxonomy_manager.snapshot
    normalized = _normalize(phrase)
    if not normalized:
        return {"match": None, "candidates": []}
    exact = [
        entity for entity in snapshot.exact(normalized)
        if entity.entity_type == "location" and entity.start == 0 and entity.end == len(normalized)
    ]
    if len(exact) == 1:
        return {"match": _resolved_entity_payload(exact[0]), "candidates": []}
    ambiguity = [
        reference for reference in snapshot.ambiguous(normalized)
        if reference.start == 0 and reference.end == len(normalized)
    ]
    if ambiguity:
        return {
            "match": None,
            "candidates": [
                {
                    "city": candidate.canonical_value,
                    "locality": candidate.canonical_value,
                    "countryCode": None,
                    "latitude": None,
                    "longitude": None,
                    "confidence": 1.0,
                    "method": "exact-ambiguous",
                }
                for candidate in ambiguity[0].candidates
                if candidate.entity_type == "location"
            ][:3],
        }
    fuzzy = snapshot.fuzzy_match(normalized, "location", minimum_score=86)
    if fuzzy is None:
        return {"match": None, "candidates": []}
    return {"match": _resolved_entity_payload(fuzzy), "candidates": []}
