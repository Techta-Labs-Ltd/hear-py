from __future__ import annotations

import re

from config import settings
from src.utils.normalize_content_item import content_title_for_speech, pick_menu_credit
from src.utils.normalize_content_item import normalize_content_items, is_playable_content_item


def normalize_dedupe_key(item: dict) -> str | None:
    if not isinstance(item, dict):
        return None
    title = content_title_for_speech(item)
    if title:
        return f"t:{title.lower().replace(chr(9), ' ').replace(chr(10), ' ').replace(chr(13), ' ').replace('  ', ' ').strip()}"
    if item.get("id"):
        return f"id:{item['id']}"
    return None


def _filter_playable_items(items: list) -> list:
    """Filter a list to only playable content items."""
    return [i for i in (items or []) if is_playable_content_item(i)]


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


def empty_browse_catalog() -> dict:
    """Create an empty browse catalog structure."""
    return {
        "intent": "general",
        "q": "",
        "categorySlug": None,
        "tags": None,
        "limit": settings.search_page_limit,
        "currentPage": 0,
        "totalHits": 0,
        "totalPages": 0,
        "spokenOffset": 0,
        "items": [],
    }


def browse_speak_window() -> int:
    """Get the number of items to speak in a single browse utterance."""
    return settings.HEAR_BROWSE_SPEAK_WINDOW or 3


def has_more_to_speak(catalog: dict | None) -> bool:
    """Check whether there are more items to speak in the catalog."""
    if not catalog:
        return False
    items = catalog.get("items") or []
    offset = catalog.get("spokenOffset") or 0
    if offset < len(items):
        return True
    return has_more_server_pages(catalog)


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


def slice_speak_window(catalog: dict | None) -> dict:
    """Slice the current speak window from the catalog items."""
    items = (catalog.get("items") or []) if catalog else []
    offset = (catalog.get("spokenOffset") or 0) if catalog else 0
    window = browse_speak_window()
    return {
        "slice": items[offset:offset + window],
        "startIndex": offset,
        "nextOffset": min(offset + window, len(items)),
    }


def build_catalog_from_search_result(search_result: dict | None, *, intent: str = "general", q: str = "", category_slug: str | None = None, tags: list | None = None, page: int = 0, limit: int | None = None, existing_catalog: dict | None = None, append: bool = False, exclude_recent=None, session_key: str | None = None) -> dict:
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
    return {"intent": catalog.get("intent") or "general", "q": catalog.get("q") or ""}


def prepare_catalog_for_launch_resume(catalog: dict | None) -> dict | None:
    """Normalize and deduplicate a catalog for resuming after a launch."""
    if not catalog or not isinstance(catalog.get("items"), list):
        return catalog
    items = normalize_content_items(catalog["items"])
    deduped_result = dedupe_search_results(items)
    items = deduped_result["items"]
    spoken_menu = merge_spoken_menu_entries([], items, 0)
    return {
        **catalog,
        "items": items,
        "totalHits": len(items) or catalog.get("totalHits") or 0,
        "spokenMenu": spoken_menu,
        "spokenOffset": 0,
    }


def publisher_name_is_locality(publisher_name: str | None, store: dict | None) -> bool:
    """Check whether a publisher name matches the user's locality."""
    if not publisher_name:
        return False
    pub = str(publisher_name).strip().lower()
    if not pub:
        return False
    store = store or {}
    candidates = [store.get("locality"), store.get("userCity"), store.get("city")]
    return any(str(c or "").strip().lower() == pub for c in candidates)


def filter_recently_heard_items(items: list, *, content_ids: list | None = None, recording_ids: list | None = None) -> list:
    id_set = set(content_ids or [])
    return [
        item for item in (items or [])
        if isinstance(item, dict) and item.get("id")
        and item["id"] not in id_set
    ]


def merge_spoken_menu_entries(existing: list, items: list, start_index: int = 0) -> list:
    """Build a merged list of spoken menu entries for browse output."""
    by_pos: dict = {}
    for e in (existing or []):
        if isinstance(e, dict) and e.get("position"):
            by_pos[e["position"]] = e
    for i, item in enumerate(items or []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        position = start_index + i + 1
        credit = pick_menu_credit(item)
        title = content_title_for_speech(item)
        label = title or (f"a recording by {credit}" if credit else "a local recording")
        by_pos[position] = {"position": position, "id": item["id"], "label": label, "credit": credit or None}
    return sorted(by_pos.values(), key=lambda e: e["position"])
