from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.constants.resolver import ResolverConstants

if TYPE_CHECKING:
    from src.models.resolver import ResolvedEntity


@dataclass(frozen=True, slots=True)
class EntityRanking:
    primary: ResolvedEntity | None
    accepted: tuple[ResolvedEntity, ...]
    ambiguous: tuple[ResolvedEntity, ...]


class EntityRanker:
    @staticmethod
    def _overlaps(left: ResolvedEntity, right: ResolvedEntity) -> bool:
        return max(left.start, right.start) < min(left.end, right.end)

    @staticmethod
    def _is_source_duplicate(left: ResolvedEntity, right: ResolvedEntity) -> bool:
        return {
            left.entity_type,
            right.entity_type,
        } == {"organization", "creator"} and (
            EntityRanker._overlaps(left, right)
            or left.canonical_value.casefold() == right.canonical_value.casefold()
        )

    @staticmethod
    def collapse_ambiguity_candidates(candidates: list[dict]) -> list[dict]:
        """Collapse creator projections of an otherwise identical organisation."""
        collapsed: list[dict] = []
        for candidate in candidates:
            entity_type = str(candidate.get("type") or "").casefold()
            name = str(candidate.get("name") or "").strip()
            if not entity_type or not name:
                continue
            duplicate_index = next(
                (
                    index
                    for index, existing in enumerate(collapsed)
                    if str(existing.get("name") or "").casefold() == name.casefold()
                    and {str(existing.get("type") or "").casefold(), entity_type}
                    == {"organization", "creator"}
                ),
                None,
            )
            normalized = {**candidate, "type": entity_type, "name": name}
            if duplicate_index is None:
                collapsed.append(normalized)
            elif entity_type == "organization":
                collapsed[duplicate_index] = normalized
        return collapsed

    @classmethod
    def _method_priority(cls, entity: ResolvedEntity) -> int:
        method = entity.method.casefold()
        if method.startswith("exact"):
            return ResolverConstants.METHOD_PRIORITY["exact"]
        if method.startswith("alias"):
            return ResolverConstants.METHOD_PRIORITY["alias"]
        if method.startswith("fuzzy"):
            return ResolverConstants.METHOD_PRIORITY["fuzzy"]
        return 0

    @classmethod
    def _entity_key(cls, entity: ResolvedEntity) -> tuple[int, int, int, int, int]:
        return (
            ResolverConstants.ENTITY_TYPE_PRIORITY.get(entity.entity_type, 0),
            entity.confidence,
            cls._method_priority(entity),
            entity.end - entity.start,
            -entity.start,
        )

    @classmethod
    def _location_key(cls, entity: ResolvedEntity) -> tuple[int, int, int, int, int, int]:
        return (
            ResolverConstants.LOCATION_ROLE_PRIORITY.get(
                str(entity.location_role or "").casefold(), 0
            ),
            ResolverConstants.LOCATION_TYPE_PRIORITY.get(
                str(entity.location_type or "").casefold(), 0
            ),
            entity.confidence,
            cls._method_priority(entity),
            entity.end - entity.start,
            -entity.start,
        )

    @classmethod
    def _accepts_phonetic_bare_location(
        cls, entity: ResolvedEntity, candidates: list[ResolvedEntity]
    ) -> bool:
        return not entity.method.casefold().startswith("phonetic_bare") or not any(
            candidate.entity_type != "location" for candidate in candidates
        )

    @classmethod
    def rank(cls, entities: tuple[ResolvedEntity, ...]) -> EntityRanking:
        candidates = [
            entity
            for entity in entities
            if entity.confidence >= ResolverConstants.SECONDARY_FACET_MIN_CONFIDENCE
        ]
        candidates = [
            entity
            for entity in candidates
            if entity.entity_type != "location"
            or cls._accepts_phonetic_bare_location(entity, candidates)
        ]
        organizations = [entity for entity in candidates if entity.entity_type == "organization"]
        candidates = [
            entity
            for entity in candidates
            if entity.entity_type != "creator"
            or not any(
                cls._is_source_duplicate(entity, organization)
                for organization in organizations
            )
        ]
        accepted: list[ResolvedEntity] = []
        for candidate in candidates:
            if candidate.entity_type == "tag" and any(
                existing.entity_type == "location" and cls._overlaps(candidate, existing)
                for existing in accepted
            ):
                continue
            if candidate.entity_type == "location":
                accepted = [
                    existing
                    for existing in accepted
                    if not (
                        existing.entity_type == "tag"
                        and cls._overlaps(candidate, existing)
                    )
                ]
            accepted.append(candidate)
        locations = [entity for entity in accepted if entity.entity_type == "location"]
        if locations:
            ranked_locations = sorted(locations, key=cls._location_key, reverse=True)
            best = ranked_locations[0]
            ties = tuple(
                entity
                for entity in ranked_locations
                if cls._location_key(entity) == cls._location_key(best)
            )
            if len({entity.entity_id for entity in ties}) > 1:
                return EntityRanking(None, tuple(accepted), ties)
            accepted = [
                entity
                for entity in accepted
                if entity.entity_type != "location" or entity == best
            ]
        primary = max(accepted, key=cls._entity_key, default=None)
        return EntityRanking(primary, tuple(accepted), ())
