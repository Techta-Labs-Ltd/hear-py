from __future__ import annotations
from config import settings
from src.services.store import get_store, update_store
from src.utils.normalize_content_item import (
    pick_content_credit,
    content_title_for_speech,
)
from src.utils.session_queue import (
    sort_queue_items_by_listening_preferences,
    merge_browse_items_preserve_order,
    is_same_browse_session,
    clone_browse_menu_item,
)
from src.utils.search_query import normalize_search_query


class BrowseCatalogManager:
    __slots__ = ()

    @staticmethod
    def _item_snapshot(item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        credit = pick_content_credit(item)
        spoken = content_title_for_speech(item)
        content_id = item.get("contentId") or item.get("id")
        return {
            "id": content_id,
            "contentId": content_id,
            "title": item.get("title"),
            "displayTitle": spoken or item.get("displayTitle"),
            "spokenTitle": spoken,
            "creator": credit or item.get("creator") or item.get("creatorName"),
            "creatorName": item.get("creatorName") or item.get("creator") or credit,
            "creatorId": item.get("creatorId"),
            "organizationId": item.get("organizationId"),
            "organizationName": item.get("organizationName"),
            "publicationId": item.get("publicationId"),
            "publicationTitle": item.get("publicationTitle"),
            "type": item.get("type"),
            "isPublication": bool(item.get("isPublication")),
            "trackIndex": item.get("trackIndex"),
            "trackCount": item.get("trackCount"),
            "summary": item.get("summary") or None,
            "category": item.get("category") or None,
            "audioUrl": item.get("audioUrl"),
            "playbackSpeeds": item.get("playbackSpeeds") or [],
            "durationMs": item.get("durationMs"),
        }

    @staticmethod
    def set_catalog(
        handler_input,
        catalog: dict | None,
        *,
        intent: str | None = None,
        category: str | None = None,
    ) -> dict:
        store = get_store(handler_input)
        raw_items = catalog.get("items", []) if catalog else []
        prev = store.get("browseCatalog")
        same_session = is_same_browse_session(prev, catalog, intent) if prev else False
        has_fresh_spoken_menu = isinstance(catalog.get("spokenMenu"), list) and len(catalog.get("spokenMenu") or []) > 0 if catalog else False

        if same_session:
            sorted_items = merge_browse_items_preserve_order(prev.get("items", []), raw_items) if prev else raw_items
        else:
            sorted_items = raw_items if has_fresh_spoken_menu else sort_queue_items_by_listening_preferences(
                raw_items, store.get("listeningPattern"), store.get("locality")
            )

        browse_ids = [
            i.get("contentId") or i.get("id")
            for i in sorted_items
            if i.get("contentId") or i.get("id")
        ]
        cap = min(len(sorted_items), settings.HEAR_BROWSE_MAX_CATALOG or 50)
        capped = sorted_items[:cap]
        snapshot = [s for s in (BrowseCatalogManager._item_snapshot(i) for i in capped) if s is not None]
        queue_cap = min(len(capped), settings.HEAR_QUEUE_PREFETCH_LIMIT or 20)
        browse_queue_items = [clone_browse_menu_item(i) for i in capped[:queue_cap]] if queue_cap else None

        clean = {
            "intent": (catalog.get("intent") if catalog else None) or intent or "general",
            "q": normalize_search_query(catalog.get("q")) if catalog else "",
            "categorySlug": catalog.get("categorySlug") or None if catalog else None,
            "tags": catalog.get("tags") or None if catalog else None,
            "limit": (catalog.get("limit") if catalog else None) or settings.search_page_limit,
            "currentPage": (catalog.get("currentPage") if catalog else None) or 0,
            "totalHits": (catalog.get("totalHits") if catalog else None) or len(capped),
            "totalPages": (catalog.get("totalPages") if catalog else None) or 0,
            "spokenOffset": (catalog.get("spokenOffset") if catalog else None) or 0,
            "items": capped,
            "spokenMenu": (catalog.get("spokenMenu") if catalog else None) or [],
        }
        return update_store(handler_input, {
            "browseCatalog": clean,
            "launchBrowseIds": browse_ids or None,
            "pendingDiscoveryIntent": intent or clean.get("intent") or None,
            "pendingDiscoveryCategory": category or None,
            "pendingBrowseItems": snapshot or None,
            "browseQueueItems": browse_queue_items,
        })

    @staticmethod
    def get_catalog(store: dict) -> dict | None:
        if isinstance(store, dict):
            bc = store.get("browseCatalog")
            if bc and isinstance(bc.get("items"), list) and bc["items"]:
                return bc
            pbi = store.get("pendingBrowseItems")
            if isinstance(pbi, list) and pbi:
                return {
                    "intent": store.get("pendingDiscoveryIntent") or "general",
                    "q": "",
                    "categorySlug": None,
                    "tags": None,
                    "limit": settings.search_page_limit,
                    "currentPage": 0,
                    "totalHits": len(pbi),
                    "totalPages": 1,
                    "spokenOffset": 0,
                    "items": pbi,
                }
        return None


_browse = BrowseCatalogManager()
set_browse_catalog = _browse.set_catalog
get_browse_catalog = _browse.get_catalog
