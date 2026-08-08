"""Canonical serialization for Hear catalogue search payloads."""
from __future__ import annotations

from src.utils.search_query import normalize_search_query

ALLOWED_SEARCH_SORTS = frozenset({
    "recommended", "nearest", "popular", "latest", "trending",
})


def normalize_search_payload(payload: dict | None) -> dict:
    """Return a search payload accepted by the Hear catalogue contract."""
    normalized = dict(payload) if isinstance(payload, dict) else {}
    query = normalized.get("query")
    normalized["query"] = normalize_search_query(
        query if query is not None else normalized.get("q")
    )
    normalized.pop("q", None)
    if normalized.get("sort") not in ALLOWED_SEARCH_SORTS:
        normalized.pop("sort", None)
    if isinstance(normalized.get("filter"), dict):
        normalized["filter"] = dict(normalized["filter"])
    return normalized
