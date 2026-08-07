from __future__ import annotations


from config import settings
from src.utils.normalize_content_item import content_title_for_speech


def normalize_dedupe_key(item: dict) -> str | None:
    if not isinstance(item, dict):
        return None
    title = content_title_for_speech(item)
    if title:
        return f"t:{title.lower().replace(chr(9), ' ').replace(chr(10), ' ').replace(chr(13), ' ').replace('  ', ' ').strip()}"
    if item.get("id"):
        return f"id:{item['id']}"
    return None


def dedupe_search_results(items: list, existing_keys: set | None = None) -> dict:
    """Deduplicate search results, preserving order."""
    seen = set(existing_keys) if existing_keys is not None else set()
    out: list = []
    for item in (items or []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        key = normalize_dedupe_key(item)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(item)
    return {"items": out, "seenKeys": seen}


def resolve_total_pages(total_hits, page_limit, api_total_pages=None, loaded_item_count: int = 0) -> int:
    """Calculate the total number of pages from hit counts and page size."""
    if isinstance(api_total_pages, (int, float)) and api_total_pages > 0:
        return int(api_total_pages)
    hits = total_hits if isinstance(total_hits, (int, float)) else 0
    limit = page_limit if page_limit > 0 else settings.search_page_limit
    if hits > 0 and limit > 0:
        return max(1, -(-hits // limit))
    if loaded_item_count >= limit and limit > 0:
        return max(2, -(-max(hits, loaded_item_count) // limit))
    return 0


def has_more_server_pages(catalog: dict | None) -> bool:
    """Check whether the server has more pages of results."""
    if not catalog:
        return False
    total_pages = resolve_total_pages(
        catalog.get("totalHits"),
        catalog.get("limit") or settings.search_page_limit,
        catalog.get("totalPages"),
        len(catalog.get("items") or []),
    )
    current_page = catalog.get("currentPage") or 0
    return total_pages > 0 and current_page + 1 < total_pages


def build_catalog_from_search_result(
    search_result: dict | None,
    *,
    intent: str = "general",
    q: str = "",
    category_slug: str | None = None,
    tags: list | None = None,
    search_payload: dict | None = None,
    page: int = 0,
    limit: int | None = None,
    existing_catalog: dict | None = None,
    append: bool = False,
    exclude_recent=None,
    session_key: str | None = None,
) -> dict:
    """Build a browse catalog structure from a search API result."""
    page_limit = limit or settings.search_page_limit
    raw = (search_result.get("results") or []) if search_result else []
    if append and existing_catalog:
        deduped = dedupe_search_results(raw, _build_seen_keys_from_catalog(existing_catalog))
    else:
        deduped = dedupe_search_results(raw)
    effective = deduped["items"]
    if append and existing_catalog:
        items = (existing_catalog.get("items") or []) + effective
        cap = settings.HEAR_BROWSE_MAX_CATALOG or 50
        if len(items) > cap:
            items = items[:cap]
        spoken_offset = existing_catalog.get("spokenOffset") or 0
        current_page = page
    else:
        items = effective
        spoken_offset = 0
        current_page = page
    total_hits_raw = (search_result.get("total_hits") if search_result else None)
    total_hits = total_hits_raw if isinstance(total_hits_raw, (int, float)) else (
        (existing_catalog.get("totalHits") if (append and existing_catalog) else None) if (append and existing_catalog) else len(items)
    )
    total_pages = resolve_total_pages(total_hits, page_limit, (search_result.get("total_pages") if search_result else None), len(items))
    resolved_session_key = None
    if search_result and isinstance(search_result.get("session_key"), str) and search_result["session_key"]:
        resolved_session_key = search_result["session_key"]
    elif session_key or (append and existing_catalog and existing_catalog.get("sessionKey")):
        resolved_session_key = session_key or (existing_catalog.get("sessionKey") if existing_catalog else None)
    return {
        "intent": intent,
        "q": str(q) if q is not None else "",
        "categorySlug": category_slug or None,
        "tags": tags or None,
        "searchPayload": (
            dict(search_payload)
            if isinstance(search_payload, dict)
            else dict(search_result.get("_search_payload"))
            if search_result and isinstance(search_result.get("_search_payload"), dict)
            else dict(existing_catalog.get("searchPayload"))
            if append and existing_catalog and isinstance(existing_catalog.get("searchPayload"), dict)
            else None
        ),
        "limit": page_limit,
        "currentPage": current_page,
        "totalHits": total_hits,
        "totalPages": total_pages or 0,
        "spokenOffset": spoken_offset,
        "items": items,
        "sessionKey": resolved_session_key,
        "_seenKeys": list(deduped["seenKeys"]),
    }


def _build_seen_keys_from_catalog(catalog: dict | None) -> set:
    """Build a set of seen dedupe keys from a catalog."""
    seen: set = set()
    for item in (catalog.get("items") or []) if catalog else []:
        key = normalize_dedupe_key(item)
        if key:
            seen.add(key)
    return seen


def catalog_search_context(catalog: dict | None) -> dict:
    """Extract the search context from a catalog."""
    if not catalog:
        return {}
    return {
        "intent": catalog.get("intent") or "general",
        "q": catalog.get("q") or "",
        "search_payload": (
            dict(catalog["searchPayload"])
            if isinstance(catalog.get("searchPayload"), dict) else None
        ),
    }


