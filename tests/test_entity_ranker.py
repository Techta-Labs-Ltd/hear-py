from __future__ import annotations

from src.models.entity_ranker import EntityRanker
from src.models.resolver import ResolvedEntity


def _entity(
    entity_type: str,
    entity_id: str,
    *,
    start: int = 0,
    end: int = 8,
    confidence: int = 100,
    method: str = "exact",
    location_role: str | None = None,
    location_type: str | None = None,
) -> ResolvedEntity:
    return ResolvedEntity(
        entity_type=entity_type,
        entity_id=entity_id,
        canonical_value=entity_id,
        original_text=entity_id,
        confidence=confidence,
        method=method,
        start=start,
        end=end,
        location_role=location_role,
        location_type=location_type,
    )


def test_organization_replaces_duplicate_creator_source():
    ranking = EntityRanker.rank(
        (
            _entity("creator", "wakefield", method="bare_match"),
            _entity("organization", "wakefield"),
        )
    )

    assert ranking.primary is not None
    assert ranking.primary.entity_type == "organization"
    assert [entity.entity_type for entity in ranking.accepted] == ["organization"]


def test_category_and_tag_remain_compatible_filters():
    ranking = EntityRanker.rank(
        (
            _entity("category", "sports"),
            _entity("tag", "sport"),
        )
    )

    assert [entity.entity_type for entity in ranking.accepted] == ["category", "tag"]


def test_location_wins_over_overlapping_tag():
    ranking = EntityRanker.rank(
        (
            _entity("tag", "york"),
            _entity("location", "york", location_type="city"),
        )
    )

    assert ranking.primary is not None
    assert ranking.primary.entity_type == "location"
    assert [entity.entity_type for entity in ranking.accepted] == ["location"]


def test_source_location_outranks_local_location():
    ranking = EntityRanker.rank(
        (
            _entity("location", "local", location_role="local", location_type="city"),
            _entity("location", "source", location_role="source", location_type="city"),
        )
    )

    assert [entity.entity_id for entity in ranking.accepted] == ["source"]


def test_town_location_outranks_county_location():
    ranking = EntityRanker.rank(
        (
            _entity("location", "county", location_type="county"),
            _entity("location", "town", location_type="town"),
        )
    )

    assert [entity.entity_id for entity in ranking.accepted] == ["town"]


def test_equivalent_distinct_locations_are_ambiguous():
    ranking = EntityRanker.rank(
        (
            _entity("location", "north"),
            _entity("location", "south"),
        )
    )

    assert ranking.primary is None
    assert [entity.entity_id for entity in ranking.ambiguous] == ["north", "south"]
