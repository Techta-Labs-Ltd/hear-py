from __future__ import annotations


class ResolverConstants:
    SECONDARY_FACET_MIN_CONFIDENCE = 75
    SOURCE_LOCATION_MIN_CONFIDENCE = 75
    STANDALONE_LOCATION_MIN_CONFIDENCE = 75
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
