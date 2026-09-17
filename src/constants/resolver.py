from __future__ import annotations


class ResolverConstants:
    ENTITY_TYPE_PRIORITY = {
        "organization": 600,
        "location": 500,
        "category": 400,
        "tag": 300,
        "publication": 200,
        "creator": 100,
    }
    LOCATION_ROLE_PRIORITY = {
        "source": 400,
        "target": 400,
        "local": 300,
        "near": 300,
        "unspecified": 200,
    }
    LOCATION_TYPE_PRIORITY = {
        "town": 500,
        "city": 500,
        "village": 500,
        "locality": 500,
        "county": 400,
        "region": 300,
        "country": 200,
    }
    METHOD_PRIORITY = {"exact": 300, "alias": 200, "fuzzy": 100}
    SECONDARY_FACET_MIN_CONFIDENCE = 75
    PUBLICATION_SORTS = frozenset({"latest", "trending"})
    CARRIERS = {
        "ChooseSourceKindIntent": "play",
        "PlayContentIntent": "play",
        "SearchContentIntent": "play",
        "SearchCreatorIntent": "play something by",
        "PlayByOrganizationIntent": "play from",
        "SearchOrganizationIntent": "play from",
        "SelectOrganizationIntent": "play from",
        "SelectPublicationSourceIntent": "play publication from",
        "SearchPublicationIntent": "play publication from",
        "BrowseByCategoryIntent": "play",
        "PlayLocalIntent": "play local",
        "PlayRecommendationIntent": "play",
        "WhatsTrendingIntent": "play",
    }
    RAW_SLOT_PRIORITY = {
        "ChooseSourceKindIntent": ("sourceKind", "publicationSort"),
        "OpenDiscoveryIntent": ("searchQuery",),
        "CarrierlessDiscoveryIntent": ("discoveryQuery", "topic"),
        "TownCaptureIntent": ("townName", "selection"),
        "SetLocationIntent": ("location", "townName", "selection"),
        "PlayLocalIntent": ("cityQuery", "localQuery", "topic", "category"),
        "PlayRecommendationIntent": ("recommendationQuery", "topic", "category"),
        "SearchContentIntent": ("searchQuery",),
        "SearchCreatorIntent": ("searchQuery",),
        "SearchOrganizationIntent": ("searchQuery",),
        "SearchPublicationIntent": ("searchQuery",),
        "SearchLocationIntent": ("searchQuery",),
        "SelectCreatorCityIntent": ("cityQuery",),
        "PlayByOrganizationIntent": ("organizationQuery", "topic"),
        "SelectOrganizationIntent": ("organizationQuery",),
        "SelectPublicationSourceIntent": ("publicationSourceQuery",),
        "PlayPublicationIntent": ("publicationSourceQuery", "topic"),
        "BrowseByCategoryIntent": ("category", "topic"),
    }
    DEFAULT_RAW_SLOT_PRIORITY = (
        "selection",
        "townName",
        "location",
        "cityQuery",
        "topic",
        "category",
        "creatorQuery",
        "organizationQuery",
        "publicationSourceQuery",
        "listPickPhrase",
        "feedbackPhrase",
        "query",
    )
    CREATOR_LOCATION_SLOTS = (
        "cityQuery",
        "localQuery",
        "townName",
    )
