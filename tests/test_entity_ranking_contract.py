"""Executable fixtures for HEAR_ALEXA_ENTITY_RANKING_CONTRACT.md section 12."""

from __future__ import annotations

import itertools

import pytest

from src.constants.resolver import ResolverConstants
from src.models.entity_ranker import EntityRanker
from src.models.resolver import ResolvedEntity, ResolverResult, ResolverUnavailable


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
    county: str | None = None,
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
        county=county,
    )


def _payload(entity: ResolvedEntity) -> dict:
    return {
        "entityType": entity.entity_type,
        "entityId": entity.entity_id,
        "canonicalValue": entity.canonical_value,
        "originalText": entity.original_text,
        "confidence": entity.confidence,
        "method": entity.method,
        "start": entity.start,
        "end": entity.end,
        "locationRole": entity.location_role,
        "locationType": entity.location_type,
        "county": entity.county,
    }


def _normalized(*entities: ResolvedEntity, intent: str = "search", residual: str = "") -> dict:
    result = ResolverResult.from_payload(
        {
            "status": "resolved",
            "intent": intent,
            "entities": [_payload(entity) for entity in entities],
            "slots": {
                "residualQuery": residual,
                "latest": False,
                "isRecommended": False,
                "isPublication": False,
                "publishedFrom": None,
                "publishedTo": None,
            },
            "ambiguities": [],
            "timingMs": 1,
        }
    )
    return result.to_alexa_payload(original_utterance="fixture")


def _types(ranking) -> list[str]:
    return sorted(entity.entity_type for entity in ranking.accepted)


def test_k01_priority_is_exactly_the_contract_order():
    assert ResolverConstants.ENTITY_TYPE_PRIORITY == {
        "organization": 600,
        "location": 500,
        "category": 400,
        "tag": 300,
        "publication": 200,
        "creator": 100,
    }


@pytest.mark.parametrize(
    ("winner", "loser"),
    list(itertools.combinations(["organization", "location", "category", "tag", "publication", "creator"], 2)),
)
def test_k01_competing_interpretations_follow_type_priority(winner, loser):
    if {winner, loser} in ({"category", "tag"},):
        pytest.skip("category and tag are an explicit compatibility exception (K09)")
    ranking = EntityRanker.rank(
        (_entity(loser, "low", start=0, end=8), _entity(winner, "high", start=0, end=8))
    )
    assert ranking.primary is not None
    assert ranking.primary.entity_type == winner


def test_k02_below_threshold_organisation_does_not_win_by_type():
    ranking = EntityRanker.rank(
        (
            _entity("organization", "weak", confidence=ResolverConstants.SECONDARY_FACET_MIN_CONFIDENCE - 1),
            _entity("creator", "valid", confidence=95),
        )
    )
    assert ranking.primary is not None
    assert ranking.primary.entity_id == "valid"
    assert _types(ranking) == ["creator"]


def test_k03_same_source_as_organisation_and_creator_keeps_the_organisation():
    ranking = EntityRanker.rank((_entity("creator", "york"), _entity("organization", "york")))
    assert _types(ranking) == ["organization"]


def test_k05_semantic_intent_is_organisation_raw_intent_unchanged():
    payload = _normalized(
        _entity("creator", "york"), _entity("organization", "york"), intent="creator"
    )
    assert payload["semanticIntent"] == "organization"
    assert payload["resolverIntent"] == "creator"


def test_k06_source_name_words_beat_a_matching_topic():
    ranking = EntityRanker.rank(
        (_entity("tag", "news", start=5, end=9), _entity("organization", "york-news", start=0, end=17))
    )
    assert _types(ranking) == ["organization"]


def test_k07_town_inside_an_organisation_name_is_not_a_location():
    # "York Talking News": York is part of the source name, not a place request.
    ranking = EntityRanker.rank(
        (
            _entity("location", "york", start=0, end=4, location_type="city"),
            _entity("organization", "york-talking-news", start=0, end=17),
        )
    )
    assert _types(ranking) == ["organization"]


def test_k08_organisation_and_separately_requested_topic_both_survive():
    # "play sport from York Talking News"
    ranking = EntityRanker.rank(
        (
            _entity("category", "sport", start=5, end=10),
            _entity("organization", "york-talking-news", start=16, end=33),
        )
    )
    assert _types(ranking) == ["category", "organization"]
    assert ranking.primary.entity_type == "organization"


def test_k09_category_and_tag_for_the_same_topic_are_both_kept():
    ranking = EntityRanker.rank(
        (_entity("tag", "sport", start=0, end=5), _entity("category", "sport", start=0, end=5))
    )
    assert _types(ranking) == ["category", "tag"]
    assert ranking.primary.entity_type == "category"


@pytest.mark.parametrize("order", [0, 1])
def test_k10_location_beats_a_geographic_tag_on_the_same_word(order):
    entities = [
        _entity("tag", "yorkshire", start=0, end=9),
        _entity("location", "yorkshire", start=0, end=9, location_type="county"),
    ]
    ranking = EntityRanker.rank(tuple(entities if order else reversed(entities)))
    assert _types(ranking) == ["location"]


def test_k11_location_category_and_tag_on_separate_phrases_all_survive():
    # "play sport #football near Sevenoaks"
    ranking = EntityRanker.rank(
        (
            _entity("category", "sport", start=5, end=10),
            _entity("tag", "football", start=11, end=19),
            _entity("location", "sevenoaks", start=25, end=34, location_type="town"),
        )
    )
    assert _types(ranking) == ["category", "location", "tag"]
    assert ranking.primary.entity_type == "location"


def test_k12_indirect_overlap_chain_keeps_compatible_endpoints():
    # A overlaps B and B overlaps C, but A and C are compatible with each other.
    ranking = EntityRanker.rank(
        (
            _entity("category", "a", start=0, end=6),
            _entity("tag", "b", start=4, end=12),
            _entity("location", "c", start=10, end=16, location_type="town"),
        )
    )
    assert "category" in _types(ranking)
    assert "location" in _types(ranking)


def test_k13_input_order_does_not_change_the_result():
    entities = [
        _entity("category", "sport", start=5, end=10),
        _entity("tag", "football", start=11, end=19),
        _entity("location", "sevenoaks", start=25, end=34, location_type="town"),
        _entity("creator", "someone", start=40, end=47),
    ]
    outcomes = {
        (
            EntityRanker.rank(tuple(order)).primary.entity_id,
            tuple(sorted(e.entity_id for e in EntityRanker.rank(tuple(order)).accepted)),
        )
        for order in itertools.permutations(entities)
    }
    assert len(outcomes) == 1


def test_k14_equally_plausible_same_type_candidates_are_ambiguous():
    ranking = EntityRanker.rank(
        (
            _entity("organization", "otley-news", start=0, end=10),
            _entity("organization", "otley-voice", start=0, end=10),
        )
    )
    assert ranking.primary is None
    assert sorted(e.entity_id for e in ranking.ambiguous) == ["otley-news", "otley-voice"]


def test_k14_position_never_breaks_a_genuine_tie():
    # Same evidence, different phrase positions: earliest must not silently win.
    ranking = EntityRanker.rank(
        (
            _entity("creator", "first", start=0, end=5),
            _entity("creator", "second", start=10, end=15),
        )
    )
    assert ranking.primary is None or len(ranking.accepted) == 2


def test_k15_explicit_location_role_beats_unspecified():
    ranking = EntityRanker.rank(
        (
            _entity("location", "unspecified", location_role="unspecified", location_type="town", confidence=95),
            _entity("location", "source", location_role="source", location_type="town", confidence=90),
        )
    )
    assert [e.entity_id for e in ranking.accepted] == ["source"]


def test_k16_city_beats_county_for_the_same_place():
    ranking = EntityRanker.rank(
        (
            _entity("location", "county", location_role="unspecified", location_type="county"),
            _entity("location", "city", location_role="unspecified", location_type="city"),
        )
    )
    assert [e.entity_id for e in ranking.accepted] == ["city"]


def test_k17_county_beats_region():
    ranking = EntityRanker.rank(
        (
            _entity("location", "region", location_role="unspecified", location_type="region"),
            _entity("location", "county", location_role="unspecified", location_type="county"),
        )
    )
    assert [e.entity_id for e in ranking.accepted] == ["county"]


def test_k19_equally_plausible_different_locations_are_ambiguous():
    ranking = EntityRanker.rank(
        (
            _entity("location", "newport-wales", location_role="unspecified", location_type="town"),
            _entity("location", "newport-iow", location_role="unspecified", location_type="town"),
        )
    )
    assert ranking.primary is None
    assert len(ranking.ambiguous) == 2


def test_k20_location_metadata_survives_ranking():
    ranking = EntityRanker.rank(
        (_entity("location", "otley", location_type="town", county="West Yorkshire"),)
    )
    assert ranking.primary.county == "West Yorkshire"
    assert ranking.primary.location_type == "town"


def test_k21_location_beside_an_accepted_category_is_kept():
    ranking = EntityRanker.rank(
        (
            _entity("category", "sport", start=0, end=5),
            _entity("location", "leeds", start=9, end=14, location_type="city"),
        )
    )
    assert _types(ranking) == ["category", "location"]


def test_k22_valid_no_match_keeps_meaningful_residual():
    payload = _normalized(residual="roman empire")
    assert payload["slots"]["residualQuery"] == "roman empire"


def test_k23_accepted_organisation_clears_residual():
    payload = _normalized(_entity("organization", "cue-and-review"), residual="que and review")
    assert payload["slots"]["residualQuery"] == ""


def test_k24_accepted_category_and_tag_clear_leftover_text():
    payload = _normalized(
        _entity("category", "sport", start=0, end=5),
        _entity("tag", "sport", start=0, end=5),
        residual="update",
    )
    assert payload["slots"]["residualQuery"] == ""


def test_k25_unresolved_ambiguity_clears_residual():
    payload = _normalized(
        _entity("organization", "otley-news", start=0, end=10),
        _entity("organization", "otley-voice", start=0, end=10),
        residual="weekly",
    )
    assert payload["status"] == "ambiguous"
    assert payload["slots"]["residualQuery"] == ""


def test_k26_nothing_accepted_and_no_residual_stays_empty():
    payload = _normalized(residual="")
    assert payload["slots"]["residualQuery"] == ""
    assert payload["entities"] == []


def test_k27_only_rejected_candidates_keep_meaningful_residual():
    payload = _normalized(
        _entity("organization", "weak", confidence=ResolverConstants.SECONDARY_FACET_MIN_CONFIDENCE - 5),
        residual="roman empire",
    )
    assert payload["slots"]["residualQuery"] == "roman empire"


def test_k28_invalid_resolver_response_is_not_an_empty_result():
    with pytest.raises(ResolverUnavailable):
        ResolverResult.from_payload({"status": "resolved", "intent": "search", "entities": [{"entityType": "tag"}]})
