from __future__ import annotations


def clone_browse_menu_item(item) -> dict | None:
    if not isinstance(item, dict):
        return item
    content_id = item.get("contentId") or item.get("id")
    return {
        "id": content_id,
        "contentId": content_id,
        "title": item.get("title"),
        "displayTitle": item.get("displayTitle"),
        "spokenTitle": item.get("spokenTitle"),
        "creator": item.get("creator") or item.get("creatorName"),
        "creatorName": item.get("creatorName") or item.get("creator"),
        "creatorId": item.get("creatorId"),
        "organizationId": item.get("organizationId"),
        "organizationName": item.get("organizationName"),
        "publicationId": item.get("publicationId"),
        "publicationTitle": item.get("publicationTitle"),
        "isPublication": bool(item.get("isPublication")),
        "trackIndex": item.get("trackIndex"),
        "trackCount": item.get("trackCount"),
        "category": item.get("category"),
        "type": item.get("type"),
        "summary": item.get("summary") or None,
        "audioUrl": item.get("audioUrl") or None,
        "playbackSpeeds": item.get("playbackSpeeds") or item.get("playback_speed") or [],
        "durationMs": item.get("durationMs"),
        "durationSecs": item.get("durationSecs"),
        "tracks": item.get("tracks") or None,
    }


def _score_category_match(item: dict, preferred_lower: list) -> int:
    """Score an item based on how well its category matches preferred categories."""
    if not preferred_lower:
        return 0
    raw = item.get("category") or (isinstance(item.get("categories"), list) and item["categories"][0] if item.get("categories") else None) or ""
    cat = str(raw).lower()
    best = 0
    for i, p in enumerate(preferred_lower):
        if p and cat == p:
            best = max(best, (len(preferred_lower) - i) * 3)
    return best


def _score_locality_match(item: dict, locality: str | None) -> int:
    """Score an item based on locality match."""
    if not locality:
        return 0
    loc = item.get("locality") or item.get("city") or ""
    if not loc:
        return 0
    return 4 if str(loc).lower() == str(locality).lower() else 0


def sort_queue_items_by_listening_preferences(items: list, listening_pattern: dict | None, locality: str | None) -> list:
    """Sort queue items by the user's listening preferences and locality."""
    lst = [
        x for x in (items or [])
        if isinstance(x, dict) and (x.get("contentId") or x.get("id"))
    ]
    preferred_lower = [
        k.replace("category:", "").lower()
        for k, v in sorted(
            [(k, v) for k, v in (listening_pattern or {}).items() if k.startswith("category:")],
            key=lambda x: x[1], reverse=True,
        )[:8]
    ]
    lst.sort(key=lambda item: _score_category_match(item, preferred_lower) + _score_locality_match(item, locality), reverse=True)
    return lst


def merge_browse_items_preserve_order(prev_items: list, raw_items: list) -> list:
    """Merge two item lists, preserving order and deduplicating."""
    seen: set = set()
    out: list = []
    for item in (prev_items or []):
        item_id = item.get("contentId") or item.get("id") if isinstance(item, dict) else None
        if item_id and item_id not in seen:
            seen.add(item_id)
            out.append(item)
    for item in (raw_items or []):
        item_id = item.get("contentId") or item.get("id") if isinstance(item, dict) else None
        if item_id and item_id not in seen:
            seen.add(item_id)
            out.append(item)
    return out


def is_same_browse_session(prev: dict | None, catalog: dict | None, intent: str | None) -> bool:
    if not prev or not isinstance(prev.get("items"), list) or not prev["items"]:
        return False
    next_intent = (catalog.get("intent") if catalog else None) or intent or "general"
    if prev.get("intent") != next_intent:
        return False
    if str(prev.get("q") or "") != str((catalog or {}).get("q") or ""):
        return False
    if str(prev.get("categorySlug") or "") != str((catalog or {}).get("categorySlug") or ""):
        return False
    return True


