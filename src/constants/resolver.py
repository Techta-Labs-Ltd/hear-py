from __future__ import annotations


class ResolverConstants:
    SOURCE_LOCATION_MIN_CONFIDENCE = 85
    STANDALONE_LOCATION_MIN_CONFIDENCE = 75
    CARRIERS = {
        "PlayContentIntent": "play",
        "PlayByCreatorIntent": "play from",
        "PlayByOrganizationIntent": "play from",
        "BrowseByCategoryIntent": "play",
        "PlayLocalIntent": "play local",
        "PlayRecommendationIntent": "recommend",
        "WhatsTrendingIntent": "what's trending",
    }
    RAW_SLOT_PRIORITY = {
        "TownCaptureIntent": ("townName", "selection"),
        "SetLocationIntent": ("location", "townName", "selection"),
        "PlayLocalIntent": ("localQuery", "topic", "category"),
        "PlayRecommendationIntent": ("recommendationQuery", "topic", "category"),
        "PlayByCreatorIntent": ("creatorQuery", "topic"),
        "PlayByOrganizationIntent": ("organizationQuery", "topic"),
        "PlayPublicationIntent": ("publicationSourceQuery", "topic"),
        "BrowseByCategoryIntent": ("category", "topic"),
    }
    DEFAULT_RAW_SLOT_PRIORITY = (
        "selection",
        "townName",
        "location",
        "topic",
        "category",
        "creatorQuery",
        "organizationQuery",
        "publicationSourceQuery",
        "listPickPhrase",
        "feedbackPhrase",
        "query",
    )
