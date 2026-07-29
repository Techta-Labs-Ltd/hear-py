from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from src.resolver.taxonomy import bundled_location_records


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


class LocationResolver:
    """Resolve manual town phrases only against bundled location records."""

    def __init__(self) -> None:
        records = bundled_location_records()
        self._choices: dict[str, object] = {}
        for record in records:
            city = str(record.metadata.get("city") or record.canonical).strip()
            for value in (city, record.canonical, *record.aliases):
                normalized = _normalize(value)
                if normalized:
                    self._choices.setdefault(normalized, record)

    def resolve(self, phrase: str) -> dict:
        normalized = _normalize(phrase)
        if not normalized:
            return {"match": None, "candidates": []}
        exact = self._choices.get(normalized)
        if exact is not None:
            return {"match": self._match(exact, 1.0, "exact").to_dict(), "candidates": []}
        ranked = process.extract(
            normalized,
            self._choices.keys(),
            scorer=fuzz.WRatio,
            limit=8,
        )
        unique: list[tuple[object, float]] = []
        identities: set[tuple] = set()
        for _, score, index in ranked:
            record = self._choices[list(self._choices.keys())[index]]
            identity = (
                record.metadata.get("city") or record.canonical,
                record.metadata.get("country_code") or record.metadata.get("countryCode"),
                record.metadata.get("lat"),
                record.metadata.get("lng"),
            )
            if identity not in identities:
                identities.add(identity)
                unique.append((record, score))
        if not unique or unique[0][1] < 86:
            return {"match": None, "candidates": []}
        if len(unique) > 1 and unique[0][1] - unique[1][1] < 3:
            return {
                "match": None,
                "candidates": [
                    self._match(record, score / 100, "fuzzy").to_dict()
                    for record, score in unique[:3]
                ],
            }
        return {
            "match": self._match(unique[0][0], unique[0][1] / 100, "fuzzy").to_dict(),
            "candidates": [],
        }

    @staticmethod
    def _match(record, confidence: float, method: str) -> LocationMatch:
        metadata = record.metadata
        return LocationMatch(
            city=str(metadata.get("city") or record.canonical),
            country_code=metadata.get("countryCode") or metadata.get("country_code"),
            latitude=_number(metadata.get("lat")),
            longitude=_number(metadata.get("lng")),
            confidence=round(confidence, 3),
            method=method,
        )


location_resolver = LocationResolver()


def resolve_location_phrase(phrase: str) -> dict:
    return location_resolver.resolve(phrase)
