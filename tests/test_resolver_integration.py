from __future__ import annotations

from src.utils.browse_catalog import (
    build_catalog_from_search_result,
    catalog_search_context,
)
from src.resolver.engine import Resolver
from src.resolver.ambiguity import resolve_ambiguity_follow_up
from src.resolver.integration import (
    resolve_for_alexa,
    resolve_organization_follow_up,
)
from src.resolver.taxonomy import TaxonomyManager, TaxonomySnapshot


def test_catalog_preserves_complete_resolver_payload_across_pages():
    payload = {
        "alexaUserId": "user-1",
        "query": "reservoir",
        "filter": {
            "categorySlugs": ["news"],
            "creatorIds": ["creator-1"],
            "publishedFrom": 100,
            "publishedTo": 200,
        },
        "isLocal": True,
        "isRecommended": False,
        "sort": "latest",
        "limit": 3,
        "page": 0,
    }
    first = build_catalog_from_search_result(
        {
            "results": [{
                "id": "track-1", "title": "First",
                "audioUrl": "https://example.test/1.mp3",
            }],
            "total_hits": 6,
            "total_pages": 2,
            "_search_payload": payload,
        },
        intent="PlayContentIntent",
        q="reservoir",
    )
    context = catalog_search_context(first)
    assert context["search_payload"] == payload

    second = build_catalog_from_search_result(
        {
            "results": [{
                "id": "track-2", "title": "Second",
                "audioUrl": "https://example.test/2.mp3",
            }],
            "total_hits": 6,
            "total_pages": 2,
        },
        **context,
        page=1,
        existing_catalog=first,
        append=True,
    )
    assert second["searchPayload"] == payload
    assert [item["id"] for item in second["items"]] == ["track-1", "track-2"]


def test_unresolved_explicit_reference_is_exposed_to_alexa(monkeypatch):
    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("empty", [])
    local_resolver = Resolver(manager)
    monkeypatch.setattr("src.resolver.integration.resolver", local_resolver)

    result = resolve_for_alexa("play latest sport from david")

    assert result["slots"]["unresolvedReferences"] == [{
        "relation": "from",
        "phrase": "david",
        "expectedTypes": ["creator", "organization", "publication"],
    }]


def test_ambiguous_alias_candidates_are_exposed_to_alexa(monkeypatch):
    from src.resolver.taxonomy import TaxonomyRecord

    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("ambiguous", [
        TaxonomyRecord(
            "organization", "Barking Publisher", "org-1", aliases=("badtn",),
        ),
        TaxonomyRecord(
            "organization", "Burnley Publisher", "org-2", aliases=("badtn",),
        ),
    ])
    monkeypatch.setattr("src.resolver.integration.resolver", Resolver(manager))

    result = resolve_for_alexa("play badtn")

    assert result["slots"]["ambiguousReferences"] == [{
        "phrase": "badtn",
        "candidates": [
            {"type": "organization", "id": "org-1", "name": "Barking Publisher"},
            {"type": "organization", "id": "org-2", "name": "Burnley Publisher"},
        ],
    }]


def test_publication_ambiguity_preserves_format_sort_and_date(monkeypatch):
    from src.resolver.taxonomy import TaxonomyRecord

    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("publication-ambiguity", [
        TaxonomyRecord(
            "organization", "North Press", "org-north", aliases=("press",),
        ),
        TaxonomyRecord(
            "organization", "South Press", "org-south", aliases=("press",),
        ),
    ])
    monkeypatch.setattr("src.resolver.integration.resolver", Resolver(manager))

    initial = resolve_for_alexa(
        "play 2026-07-28 latest publication from press",
        alexa_intent="PlayPublicationIntent",
    )
    candidates = initial["slots"]["ambiguousReferences"][0]["candidates"]
    resolved = resolve_ambiguity_follow_up("north", {
        "intent": initial["intent"],
        "searchPayload": initial["slots"]["searchPlan"],
        "slots": initial["slots"],
        "candidates": candidates,
    })

    assert resolved["status"] == "resolved"
    assert resolved["searchPayload"]["sort"] == "latest"
    assert resolved["searchPayload"]["filter"]["publishedFrom"] == (
        initial["slots"]["searchPlan"]["filter"]["publishedFrom"]
    )
    assert resolved["searchPayload"]["filter"]["publishedTo"] == (
        initial["slots"]["searchPlan"]["filter"]["publishedTo"]
    )
    assert resolved["searchPayload"]["filter"] == {
        "isPublication": True,
        "organizationIds": ["org-north"],
        "publishedFrom": initial["slots"]["searchPlan"]["filter"]["publishedFrom"],
        "publishedTo": initial["slots"]["searchPlan"]["filter"]["publishedTo"],
    }


def test_resolved_organization_keeps_a_spoken_display_name(monkeypatch):
    from src.resolver.taxonomy import TaxonomyRecord

    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("tnf", [
        TaxonomyRecord(
            "category", "sport", slug="sport",
        ),
        TaxonomyRecord(
            "organization",
            "Talking News Federation",
            "org-tnf",
            aliases=("tnf",),
        ),
    ])
    monkeypatch.setattr("src.resolver.integration.resolver", Resolver(manager))

    result = resolve_for_alexa("play me latest sport from tnf")

    assert result["slots"]["category"] == "sport"
    assert result["slots"]["organizationIds"] == ["org-tnf"]
    assert result["slots"]["organizationName"] == "Talking News Federation"


def test_resolved_city_routes_as_local_even_without_near_me_language(monkeypatch):
    from src.resolver.taxonomy import TaxonomyRecord

    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("city", [
        TaxonomyRecord(
            "location",
            "Birmingham",
            aliases=("birmingham",),
            metadata={"city": "Birmingham", "countryCode": "gb"},
        ),
    ])
    monkeypatch.setattr("src.resolver.integration.resolver", Resolver(manager))

    result = resolve_for_alexa("birmingham city")

    assert result["intent"] == "local"
    assert result["slots"]["city"] == "Birmingham"
    assert result["slots"]["residualQuery"] == ""


def test_prompted_short_organization_typo_uses_unique_taxonomy_alias(monkeypatch):
    from src.resolver.taxonomy import TaxonomyRecord

    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("ytn", [
        TaxonomyRecord(
            "organization",
            "York Talking News",
            "org-ytn",
            aliases=("ytn",),
        ),
    ])
    monkeypatch.setattr("src.resolver.integration.resolver", Resolver(manager))

    result = resolve_organization_follow_up("ynt")

    assert result["intent"] == "organization"
    assert result["slots"]["organizationIds"] == ["org-ytn"]
    assert result["slots"]["organizationName"] == "York Talking News"
    assert result["slots"]["residualQuery"] == ""


def test_prompted_spoken_organization_initialism_is_compacted(monkeypatch):
    from src.resolver.taxonomy import TaxonomyRecord

    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("ytn-spoken", [
        TaxonomyRecord(
            "organization",
            "York Talking News",
            "org-ytn",
            aliases=("ytn",),
        ),
    ])
    monkeypatch.setattr("src.resolver.integration.resolver", Resolver(manager))

    result = resolve_organization_follow_up("Y. T. N.")

    assert result["slots"]["organizationIds"] == ["org-ytn"]
    assert result["slots"]["organizationName"] == "York Talking News"


def test_ambiguity_follow_up_marks_unique_candidate_for_confirmation():
    candidates = [
        {"type": "organization", "id": "org-bromley", "name": "Bromley TN"},
        {"type": "organization", "id": "org-neston", "name": "Ellesmere Port and Neston TN"},
        {"type": "organization", "id": "org-north", "name": "The Northumbrian"},
    ]

    resolved = resolve_ambiguity_follow_up("neston", {
        "intent": "organization",
        "candidates": candidates,
        "slots": {},
        "searchPayload": {"query": "", "filter": {}, "sort": "latest"},
    })

    assert resolved["status"] == "resolved"
    assert resolved["ambiguityResolution"] is True
    assert resolved["searchPayload"]["filter"] == {
        "organizationIds": ["org-neston"],
    }


def test_unrelated_ambiguity_reply_is_not_treated_as_a_candidate():
    candidates = [
        {"type": "organization", "id": "org-bromley", "name": "Bromley TN"},
        {"type": "organization", "id": "org-neston", "name": "Neston TN"},
        {"type": "organization", "id": "org-north", "name": "The Northumbrian"},
    ]

    unresolved = resolve_ambiguity_follow_up("banana weather", {
        "intent": "organization",
        "candidates": candidates,
        "slots": {},
        "searchPayload": {"query": "", "filter": {}},
    })

    assert unresolved["status"] == "ambiguous"
    assert unresolved["followUpMatched"] is False
