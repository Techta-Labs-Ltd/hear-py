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
    def _evidence_key(cls, entity: ResolvedEntity) -> tuple[int, ...]:
        """Evidence for choosing between same-type candidates; position is never evidence."""
        if entity.entity_type == "location":
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
            )
        return (entity.confidence, cls._method_priority(entity), entity.end - entity.start)

    @classmethod
    def _entity_key(cls, entity: ResolvedEntity) -> tuple[int, ...]:
        return (
            ResolverConstants.ENTITY_TYPE_PRIORITY.get(entity.entity_type, 0),
            *cls._evidence_key(entity),
            # Only orders compatible, independently accepted entities; a
            # genuine competing tie is reported as ambiguity, never decided here.
            -entity.start,
        )

    @classmethod
    def _location_key(cls, entity: ResolvedEntity) -> tuple[int, ...]:
        return cls._evidence_key(entity)

    @staticmethod
    def _compatible(left: ResolvedEntity, right: ResolvedEntity) -> bool:
        # Contract 5.2: a category and a tag for the same topic are both kept.
        return {left.entity_type, right.entity_type} == {"category", "tag"}

    @classmethod
    def _outranks(cls, left: ResolvedEntity, right: ResolvedEntity) -> bool:
        """Whether ``left`` wins the words it shares with ``right``."""
        left_priority = ResolverConstants.ENTITY_TYPE_PRIORITY.get(left.entity_type, 0)
        right_priority = ResolverConstants.ENTITY_TYPE_PRIORITY.get(right.entity_type, 0)
        if left_priority != right_priority:
            return left_priority > right_priority
        return cls._evidence_key(left) > cls._evidence_key(right)

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
        # Contract 5.1/5.2: candidates claiming the same words compete, and the
        # stronger meaning owns them (organisation over a town or topic inside
        # its name, location over a geographic tag, ...). Compatible pairs and
        # non-overlapping phrases are never erased. Pairwise comparison keeps
        # the result independent of input order and of overlap chains.
        accepted = [
            entity
            for entity in candidates
            if not any(
                other is not entity
                and cls._overlaps(entity, other)
                and not cls._compatible(entity, other)
                and cls._outranks(other, entity)
                for other in candidates
            )
        ]
        tied = tuple(
            sorted(
                {
                    entity
                    for entity in accepted
                    for other in accepted
                    if other is not entity
                    and entity.entity_type == other.entity_type
                    and entity.entity_id != other.entity_id
                    and cls._overlaps(entity, other)
                    and cls._evidence_key(entity) == cls._evidence_key(other)
                },
                key=lambda entity: (entity.start, entity.entity_id),
            )
        )
        if tied:
            return EntityRanking(None, tuple(accepted), tied)
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
