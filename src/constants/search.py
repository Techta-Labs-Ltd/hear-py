from __future__ import annotations


class SearchConstants:
    ALLOWED_SEARCH_SORTS = frozenset({"recommended", "nearest", "popular", "latest", "trending"})
    SEARCH_FILTER_KEYS = (
        "contentIds",
        "creatorIds",
        "organizationIds",
        "publicationIds",
        "categorySlugs",
        "tags",
        "city",
        "countryCode",
        "isPublication",
        "latitude",
        "longitude",
        "publishedFrom",
        "publishedTo",
    )
    SEARCH_SOURCE_FILTERS = {
        "creator": "creatorIds",
        "organization": "organizationIds",
        "publication": "publicationIds",
    }
    SEARCH_SOURCE_NAMES = {
        "creator": "creatorName",
        "organization": "organizationName",
        "publication": "publicationName",
    }
    SEARCH_API_FIELDS = ("alexaUserId", "filter", "isLocal", "isRecommended")
    SEARCH_DATE_FILTER_KEYS = ("publishedFrom", "publishedTo")
