"""Value objects produced by the local Hear search resolver."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResolvedEntity:
    entity_type: str
    entity_id: str | None
    canonical_value: str
    original_text: str
    confidence: float
    method: str
    start: int
    end: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TemporalRange:
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    original_text: str | None = None
    start: int = -1
    end: int = -1


@dataclass(frozen=True)
class UnresolvedReference:
    relation: str
    phrase: str
    expected_types: tuple[str, ...]
    start: int
    end: int


@dataclass(frozen=True)
class AmbiguousCandidate:
    entity_type: str
    entity_id: str | None
    canonical_value: str


@dataclass(frozen=True)
class AmbiguousReference:
    phrase: str
    candidates: tuple[AmbiguousCandidate, ...]
    start: int
    end: int


@dataclass
class SearchPlan:
    alexa_user_id: str = ""
    query: str = ""
    category_slugs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    creator_ids: list[str] = field(default_factory=list)
    organization_ids: list[str] = field(default_factory=list)
    publication_ids: list[str] = field(default_factory=list)
    city: str | None = None
    country_code: str | None = None
    is_local: bool = False
    is_recommended: bool = False
    sort: str = "relevance"
    page: int = 0
    limit: int = 20
    temporal: TemporalRange | None = None
    confidence: float = 1.0
    entities: list[ResolvedEntity] = field(default_factory=list)
    unresolved_references: list[UnresolvedReference] = field(default_factory=list)
    ambiguous_references: list[AmbiguousReference] = field(default_factory=list)
    normalized_text: str = ""
    taxonomy_revision: str = "bundled"
    timing_ms: dict[str, float] = field(default_factory=dict)
