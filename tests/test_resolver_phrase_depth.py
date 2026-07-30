from __future__ import annotations

import pytest

from src.resolver.engine import Resolver
from src.resolver.taxonomy import TaxonomyManager, TaxonomyRecord, TaxonomySnapshot


ENTITY_CASES = (
    # entity type, relation, 1/2/3/4-word phrases, expected payload field
    ("creator", "by", (
        "Adeshina",
        "David Beard",
        "Alice Morgan Studio",
        "Independent Audio Creator Collective",
    ), "creator_ids"),
    ("organization", "from", (
        "YTN",
        "York Audio",
        "York Talking News",
        "Barking Dagenham Audio News",
    ), "organization_ids"),
    ("publication", "from", (
        "Chronicle",
        "Daily Chronicle",
        "Community Daily Chronicle",
        "Northern Community Daily Chronicle",
    ), "publication_ids"),
    ("location", "in", (
        "Burnley",
        "Milton Keynes",
        "Kingston upon Hull",
        "Ashby de la Zouch",
    ), "city"),
    ("tag", "on", (
        "weather",
        "community service",
        "visual impairment access",
        "message in a bottle",
    ), "tags"),
)


def _matrix_resolver() -> Resolver:
    records = []
    for entity_type, _relation, phrases, _field in ENTITY_CASES:
        for depth, phrase in enumerate(phrases, start=1):
            metadata = (
                {"city": phrase, "countryCode": "GB"}
                if entity_type == "location" else {}
            )
            records.append(TaxonomyRecord(
                entity_type=entity_type,
                canonical=phrase,
                entity_id=None if entity_type in {"location", "tag"} else f"{entity_type}-{depth}",
                slug=phrase.lower().replace(" ", "-") if entity_type == "tag" else None,
                metadata=metadata,
            ))
    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("phrase-depth-test", records)
    return Resolver(manager)


@pytest.mark.parametrize(
    "entity_type,relation,phrases,field",
    ENTITY_CASES,
)
def test_each_entity_type_resolves_one_to_four_word_phrases(
    entity_type,
    relation,
    phrases,
    field,
):
    resolver = _matrix_resolver()
    for depth, phrase in enumerate(phrases, start=1):
        plan = resolver.resolve(f"play the latest recording {relation} {phrase}")
        matched = [item for item in plan.entities if item.entity_type == entity_type]
        assert len(phrase.split()) == depth
        assert [item.canonical_value for item in matched] == [
            phrase.lower().replace(" ", "-") if entity_type == "tag" else phrase
        ]
        if field == "city":
            assert plan.city == phrase
        else:
            values = getattr(plan, field)
            expected = (
                [phrase.lower().replace(" ", "-")]
                if entity_type == "tag"
                else [f"{entity_type}-{depth}"]
            )
            assert values == expected


def test_production_snapshot_publication_gap_is_explicit():
    from src.resolver.taxonomy import taxonomy_manager

    publications = [
        record for record in taxonomy_manager.snapshot.records
        if record.entity_type == "publication"
    ]
    assert publications == [], (
        "Update this assertion and add real publication phrase cases when the "
        "taxonomy manifest begins publishing publication records."
    )
