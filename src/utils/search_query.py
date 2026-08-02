"""Normalization for the search query field shared by all search payloads."""
from __future__ import annotations


def normalize_search_query(value: object) -> str:
    """Serialize an absent query as an empty string without changing user text."""
    return "" if value is None else str(value)
