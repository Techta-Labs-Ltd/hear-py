from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.resolver.engine import Resolver
from src.resolver.payload import build_hear_payload
from src.resolver.taxonomy import TaxonomyManager, TaxonomyRecord, TaxonomySnapshot
from src.resolver.temporal import parse_temporal


@pytest.fixture(scope="module")
def resolver():
    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("test-1", [
        TaxonomyRecord("category", "sports", slug="sports", aliases=("sport",)),
        TaxonomyRecord("category", "news", slug="news"),
        TaxonomyRecord("category", "politics", slug="politics"),
        TaxonomyRecord("category", "technology", slug="technology"),
        TaxonomyRecord(
            "category",
            "sound-recording",
            slug="sound-recording",
            aliases=("sound", "recording", "sound recording", "audio"),
        ),
        TaxonomyRecord("creator", "David Beard", entity_id="creator-david",
                       aliases=("David", "Dave Beard")),
        TaxonomyRecord(
            "creator",
            "North London Talking Newspaper",
            entity_id="creator-north-london",
        ),
        TaxonomyRecord("organization", "Havering Residents Association",
                       entity_id="org-hra", aliases=("HRA",)),
        TaxonomyRecord(
            "organization",
            "Burnley and District Talking Newspaper",
            entity_id="org-burnley",
            aliases=("Burnley",),
        ),
        TaxonomyRecord(
            "organization", "Renfrewshire Sound",
            entity_id="org-renfrewshire-sound", aliases=("sound",),
        ),
        TaxonomyRecord(
            "organization", "Sound News Milton Keynes",
            entity_id="org-sound-news", aliases=("sound",),
        ),
        TaxonomyRecord("publication", "Morning Briefing",
                       entity_id="publication-morning"),
        TaxonomyRecord("tag", "breaking-news", slug="breaking-news",
                       aliases=("breaking news",)),
        TaxonomyRecord("location", "Lagos", aliases=("lagos",),
                       metadata={"city": "Lagos", "countryCode": "ng"}),
        TaxonomyRecord("location", "Havering", aliases=("havering",),
                       metadata={"city": "Havering", "countryCode": "gb"}),
        TaxonomyRecord("location", "Burnley", aliases=("burnley",),
                       metadata={"city": "Burnley", "countryCode": "gb"}),
        TaxonomyRecord("location", "Swindon", aliases=("swindon",),
                       metadata={"city": "Swindon", "countryCode": "gb"}),
    ])
    return Resolver(manager)


def test_builds_exact_structured_payload(resolver):
    plan = resolver.resolve(
        "find me the latest sport track from david about arsenal",
        "USER_ID",
    )
    assert build_hear_payload(plan) == {
        "alexaUserId": "USER_ID",
        "isLocal": False,
        "isRecommended": False,
        "limit": 20,
        "page": 0,
        "query": "arsenal",
        "sort": "latest",
        "filter": {
            "categorySlugs": ["sports"],
            "creatorIds": ["creator-david"],
        },
    }


@pytest.mark.parametrize(
    "utterance",
    ["play recording", "play a track", "play audio", "play sound"],
)
def test_reserved_content_nouns_do_not_create_taxonomy_filters(
    resolver, utterance,
):
    plan = resolver.resolve(utterance)
    assert plan.category_slugs == []
    assert plan.tags == []
    assert plan.query == ""
    assert plan.ambiguous_references == []


def test_multi_word_sound_recording_remains_a_category_filter(resolver):
    plan = resolver.resolve("play the latest sound recording")
    assert plan.category_slugs == ["sound-recording"]
    assert plan.query == ""
    assert plan.sort == "latest"


def test_misspelled_multi_word_sound_recording_is_fuzzy_category(resolver):
    plan = resolver.resolve("play the latest sound recoridng in burnley")
    assert plan.category_slugs == ["sound-recording"]
    assert plan.city == "Burnley"
    assert plan.organization_ids == []
    assert plan.query == ""
    assert plan.ambiguous_references == []


@pytest.mark.parametrize(
    ("utterance", "query", "categories", "creators", "organizations", "city",
     "local", "recommended", "sort"),
    [
        ("play sport", "", ["sports"], [], [], None, False, False, "relevance"),
        ("play sport from david", "", ["sports"], ["creator-david"], [], None, False, False, "relevance"),
        ("play david's latest news", "", ["news"], ["creator-david"], [], None, False, False, "latest"),
        ("give me news about havering council", "council", ["news"], [], [], "Havering", False, False, "relevance"),
        ("play something in havering", "", [], [], [], "Havering", False, False, "relevance"),
        ("play havering residents association", "", [], [], ["org-hra"], None, False, False, "relevance"),
        ("play yesterday's news", "", ["news"], [], [], None, False, False, "relevance"),
        ("play news about the reservoir from david", "reservoir", ["news"], ["creator-david"], [], None, False, False, "relevance"),
        ("play something around lagos about traffic", "traffic", [], [], [], "Lagos", False, False, "relevance"),
        ("play local news", "", ["news"], [], [], None, True, False, "relevance"),
        ("play news near me", "", ["news"], [], [], None, True, False, "relevance"),
        ("recommend some news", "", ["news"], [], [], None, False, True, "recommended"),
        ("recommend sports from david", "", ["sports"], ["creator-david"], [], None, False, True, "recommended"),
        ("give me something i would like", "", [], [], [], None, False, True, "recommended"),
        ("find politics in lagos", "", ["politics"], [], [], "Lagos", False, False, "relevance"),
        ("play breaking news", "", [], [], [], None, False, False, "relevance"),
        ("play local politics from hra", "", ["politics"], [], ["org-hra"], None, True, False, "relevance"),
        ("play the latest local news from david", "", ["news"], ["creator-david"], [], None, True, False, "latest"),
    ],
)
def test_required_utterance_shapes(
    resolver, utterance, query, categories, creators, organizations, city,
    local, recommended, sort,
):
    plan = resolver.resolve(utterance)
    assert plan.query == query
    assert plan.category_slugs == categories
    assert plan.creator_ids == creators
    assert plan.organization_ids == organizations
    assert plan.city == city
    assert plan.is_local is local
    assert plan.is_recommended is recommended
    assert plan.sort == sort


def test_temporal_from_monday_is_not_a_creator(resolver):
    plan = resolver.resolve("play sport from monday")
    assert plan.temporal is not None
    assert plan.creator_ids == []
    assert plan.query == ""


@pytest.mark.parametrize("relation", ["in", "near", "around"])
def test_location_relations_prefer_city_over_same_named_organization(
    resolver, relation,
):
    plan = resolver.resolve(f"play recordings {relation} burnley")
    assert plan.city == "Burnley"
    assert plan.country_code == "gb"
    assert plan.organization_ids == []


def test_from_relation_prefers_organization_over_same_named_city(resolver):
    plan = resolver.resolve("play recordings from burnley")
    assert plan.organization_ids == ["org-burnley"]
    assert plan.city is None


def test_from_relation_recovers_a_misspelled_city(resolver):
    plan = resolver.resolve("play me the latest news from swidon")

    assert plan.category_slugs == ["news"]
    assert plan.city == "Swindon"
    assert plan.country_code == "gb"
    assert plan.query == ""
    assert plan.unresolved_references == []


def test_scoped_fuzzy_creator_fallback(resolver):
    plan = resolver.resolve("play news from david beerd")
    assert plan.creator_ids == ["creator-david"]
    assert plan.query == ""
    assert any(entity.method == "fuzzy" for entity in plan.entities)


def test_requested_utterance_routes_david_to_creator(resolver):
    plan = resolver.resolve("play me the latest sport track from david")
    assert plan.creator_ids == ["creator-david"]
    assert plan.category_slugs == ["sports"]
    assert plan.sort == "latest"
    assert plan.query == ""


@pytest.mark.parametrize(
    ("utterance", "query"),
    [
        ("play from north london talking newspapr", ""),
        ("play from nort london talkin newspaper", ""),
        ("play from north londen talking newspaper about elections", "elections"),
        ("play from north london talking newspapr elections", "elections"),
    ],
)
def test_four_word_creator_fuzzy_capture(resolver, utterance, query):
    plan = resolver.resolve(utterance)
    assert plan.creator_ids == ["creator-north-london"]
    assert plan.query == query
    assert plan.unresolved_references == []
    assert any(
        entity.entity_id == "creator-north-london" and entity.method == "fuzzy"
        for entity in plan.entities
    )


def test_short_creator_alias_does_not_swallow_trailing_topic(resolver):
    plan = resolver.resolve("play from david football")
    assert plan.creator_ids == ["creator-david"]
    assert plan.query == "football"
    assert plan.unresolved_references == []


def test_ambiguous_four_word_creator_is_not_guessed():
    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("ambiguous", [
        TaxonomyRecord(
            "creator", "East London Talking Newspaper", entity_id="creator-east",
        ),
        TaxonomyRecord(
            "creator", "West London Talking Newspaper", entity_id="creator-west",
        ),
    ])
    plan = Resolver(manager).resolve("play from londn talking newspaper")
    assert plan.creator_ids == []
    assert plan.query == "londn talking newspaper"
    assert [item.phrase for item in plan.unresolved_references] == [
        "londn talking newspaper",
    ]


def test_shared_acronym_returns_named_disambiguation_candidates():
    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("ambiguous-alias", [
        TaxonomyRecord(
            "organization",
            "Barking and Dagenham Talking Newspaper",
            entity_id="org-barking",
            aliases=("badtn",),
        ),
        TaxonomyRecord(
            "organization",
            "Brentwood and District Talking Newspaper",
            entity_id="org-brentwood",
            aliases=("badtn",),
        ),
        TaxonomyRecord(
            "organization",
            "Burnley and District Talking Newspaper",
            entity_id="org-burnley",
            aliases=("badtn",),
        ),
    ])
    plan = Resolver(manager).resolve("play badtn")
    assert plan.query == ""
    assert plan.organization_ids == []
    assert plan.unresolved_references == []
    assert len(plan.ambiguous_references) == 1
    assert [
        candidate.canonical_value
        for candidate in plan.ambiguous_references[0].candidates
    ] == [
        "Barking and Dagenham Talking Newspaper",
        "Brentwood and District Talking Newspaper",
        "Burnley and District Talking Newspaper",
    ]


def test_low_confidence_name_is_left_as_query(resolver):
    plan = resolver.resolve("play news from damian")
    assert plan.creator_ids == []
    assert plan.query == "damian"
    assert len(plan.unresolved_references) == 1
    assert plan.unresolved_references[0].phrase == "damian"
    assert plan.unresolved_references[0].expected_types == (
        "creator", "organization", "publication",
    )


@pytest.mark.parametrize(
    ("utterance", "category", "query"),
    [
        ("play spoort", "sports", ""),
        ("play tecnology", "technology", ""),
        ("play failed news", "news", "failed"),
        ("play feld news", "news", "feld"),
        ("play socer", None, "socer"),
        ("play nuse", None, "nuse"),
    ],
)
def test_misspelled_keywords_are_resolved_only_when_unambiguous(
    resolver, utterance, category, query,
):
    plan = resolver.resolve(utterance)
    assert plan.category_slugs == ([category] if category else [])
    assert plan.query == query


def test_temporal_boundaries_are_timezone_aware():
    now = datetime(2026, 7, 29, 15, 30, tzinfo=ZoneInfo("Europe/London"))
    value = parse_temporal("play news last week", "Europe/London", now)
    assert value is not None
    assert datetime.fromtimestamp(value.start_timestamp, ZoneInfo("Europe/London")).isoformat() == (
        "2026-07-20T00:00:00+01:00"
    )
    assert datetime.fromtimestamp(value.end_timestamp, ZoneInfo("Europe/London")).isoformat() == (
        "2026-07-27T00:00:00+01:00"
    )


def test_on_monday_is_one_calendar_day():
    now = datetime(2026, 7, 29, 15, 30, tzinfo=ZoneInfo("Europe/London"))
    value = parse_temporal("play news on monday", "Europe/London", now)
    assert value is not None
    assert value.end_timestamp - value.start_timestamp == 86400
