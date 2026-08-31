from __future__ import annotations

from config import settings
from src.utils.content import ContentUtils


class BrowseUtils:
    @staticmethod
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

    @staticmethod
    def _score_category_match(item: dict, preferred_lower: list) -> int:
        """Score an item based on how well its category matches preferred categories."""
        if not preferred_lower:
            return 0
        raw = (
            item.get("category")
            or (
                isinstance(item.get("categories"), list) and item["categories"][0]
                if item.get("categories")
                else None
            )
            or ""
        )
        cat = str(raw).lower()
        best = 0
        for i, p in enumerate(preferred_lower):
            if p and cat == p:
                best = max(best, (len(preferred_lower) - i) * 3)
        return best

    @staticmethod
    def _score_locality_match(item: dict, locality: str | None) -> int:
        """Score an item based on locality match."""
        if not locality:
            return 0
        loc = item.get("locality") or item.get("city") or ""
        if not loc:
            return 0
        return 4 if str(loc).lower() == str(locality).lower() else 0

    @staticmethod
    def sort_queue_items_by_listening_preferences(
        items: list, listening_pattern: dict | None, locality: str | None
    ) -> list:
        """Sort queue items by the user's listening preferences and locality."""
        lst = [
            x for x in items or [] if isinstance(x, dict) and (x.get("contentId") or x.get("id"))
        ]
        preferred_lower = [
            k.replace("category:", "").lower()
            for k, v in sorted(
                [(k, v) for k, v in (listening_pattern or {}).items() if k.startswith("category:")],
                key=lambda x: x[1],
                reverse=True,
            )[:8]
        ]
        lst.sort(
            key=lambda item: (
                BrowseUtils._score_category_match(item, preferred_lower)
                + BrowseUtils._score_locality_match(item, locality)
            ),
            reverse=True,
        )
        return lst

    @staticmethod
    def merge_browse_items_preserve_order(prev_items: list, raw_items: list) -> list:
        """Merge two item lists, preserving order and deduplicating."""
        seen: set = set()
        out: list = []
        for item in prev_items or []:
            item_id = item.get("contentId") or item.get("id") if isinstance(item, dict) else None
            if item_id and item_id not in seen:
                seen.add(item_id)
                out.append(item)
        for item in raw_items or []:
            item_id = item.get("contentId") or item.get("id") if isinstance(item, dict) else None
            if item_id and item_id not in seen:
                seen.add(item_id)
                out.append(item)
        return out

    @staticmethod
    def is_same_browse_session(prev: dict | None, catalog: dict | None, intent: str | None) -> bool:
        if not prev or not isinstance(prev.get("items"), list) or (not prev["items"]):
            return False
        next_intent = (catalog.get("intent") if catalog else None) or intent or "general"
        if prev.get("intent") != next_intent:
            return False
        if str(prev.get("q") or "") != str((catalog or {}).get("q") or ""):
            return False
        if str(prev.get("categorySlug") or "") != str((catalog or {}).get("categorySlug") or ""):
            return False
        return True

    @staticmethod
    def has_active_browse_catalog(store: dict) -> bool:
        catalog = store.get("browseCatalog") if isinstance(store, dict) else None
        if isinstance(catalog, dict) and catalog.get("items"):
            return True
        pending = store.get("pendingBrowseItems") if isinstance(store, dict) else None
        return isinstance(pending, list) and bool(pending)

    @staticmethod
    def is_browse_pagination_query(query: str) -> bool:
        return str(query or "").strip().casefold() in {
            "show me more",
            "what are the next ones",
            "more",
            "more recordings",
            "more content",
            "next ones",
            "what else did you find",
            "keep going",
            "what comes next",
            "what are the next content found",
        }

    @staticmethod
    def normalize_dedupe_key(item: dict) -> str | None:
        if not isinstance(item, dict):
            return None
        title = ContentUtils.content_title_for_speech(item)
        if title:
            return f"t:{title.lower().replace(chr(9), ' ').replace(chr(10), ' ').replace(chr(13), ' ').replace('  ', ' ').strip()}"
        if item.get("id"):
            return f"id:{item['id']}"
        return None

    @staticmethod
    def dedupe_search_results(items: list, existing_keys: set | None = None) -> dict:
        """Deduplicate search results, preserving order."""
        seen = set(existing_keys) if existing_keys is not None else set()
        out: list = []
        for item in items or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            key = BrowseUtils.normalize_dedupe_key(item)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            out.append(item)
        return {"items": out, "seenKeys": seen}

    @staticmethod
    def resolve_total_pages(
        total_hits, page_limit, api_total_pages=None, loaded_item_count: int = 0
    ) -> int:
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

    @staticmethod
    def has_more_server_pages(catalog: dict | None) -> bool:
        """Check whether the server has more pages of results."""
        if not catalog:
            return False
        total_pages = BrowseUtils.resolve_total_pages(
            catalog.get("totalHits"),
            catalog.get("limit") or settings.search_page_limit,
            catalog.get("totalPages"),
            len(catalog.get("items") or []),
        )
        current_page = catalog.get("currentPage") or 0
        return total_pages > 0 and current_page + 1 < total_pages

    @staticmethod
    def _catalog_items(raw: list, existing: dict | None, append: bool) -> tuple[list, dict, int]:
        seen = BrowseUtils._build_seen_keys_from_catalog(existing) if append and existing else None
        deduped = BrowseUtils.dedupe_search_results(raw, seen)
        if not append or not existing:
            return deduped["items"], deduped, 0
        items = (existing.get("items") or []) + deduped["items"]
        cap = settings.HEAR_BROWSE_MAX_CATALOG or 50
        return items[:cap], deduped, existing.get("spokenOffset") or 0

    @staticmethod
    def _catalog_search_payload(
        result: dict | None,
        configured: dict | None,
        existing: dict | None,
        append: bool,
    ) -> dict | None:
        candidates = (
            configured,
            result.get("_search_payload") if result else None,
            existing.get("searchPayload") if append and existing else None,
        )
        return next((dict(value) for value in candidates if isinstance(value, dict)), None)

    @staticmethod
    def _catalog_session_key(
        result: dict | None,
        configured: str | None,
        existing: dict | None,
        append: bool,
    ) -> str | None:
        remote = result.get("session_key") if result else None
        if isinstance(remote, str) and remote:
            return remote
        return configured or (existing.get("sessionKey") if append and existing else None)

    @staticmethod
    def build_catalog_from_search_result(search_result: dict | None, **options) -> dict:
        existing = options.get("existing_catalog")
        append = bool(options.get("append"))
        query = options.get("q", "")
        raw = search_result.get("results") or [] if search_result else []
        items, deduped, spoken_offset = BrowseUtils._catalog_items(raw, existing, append)
        page_limit = options.get("limit") or settings.search_page_limit
        remote_total = search_result.get("total_hits") if search_result else None
        total_hits = (
            remote_total
            if isinstance(remote_total, (int, float))
            else existing.get("totalHits")
            if append and existing
            else len(items)
        )
        total_pages = BrowseUtils.resolve_total_pages(
            total_hits,
            page_limit,
            search_result.get("total_pages") if search_result else None,
            len(items),
        )
        return {
            "intent": options.get("intent", "general"),
            "q": str(query) if query is not None else "",
            "categorySlug": options.get("category_slug") or None,
            "tags": options.get("tags") or None,
            "searchPayload": BrowseUtils._catalog_search_payload(
                search_result, options.get("search_payload"), existing, append
            ),
            "limit": page_limit,
            "currentPage": options.get("page", 0),
            "totalHits": total_hits,
            "totalPages": total_pages or 0,
            "spokenOffset": spoken_offset,
            "items": items,
            "sessionKey": BrowseUtils._catalog_session_key(
                search_result, options.get("session_key"), existing, append
            ),
            "_seenKeys": list(deduped["seenKeys"]),
        }

    @staticmethod
    def _build_seen_keys_from_catalog(catalog: dict | None) -> set:
        """Build a set of seen dedupe keys from a catalog."""
        seen: set = set()
        for item in catalog.get("items") or [] if catalog else []:
            key = BrowseUtils.normalize_dedupe_key(item)
            if key:
                seen.add(key)
        return seen

    @staticmethod
    def catalog_search_context(catalog: dict | None) -> dict:
        """Extract the search context from a catalog."""
        if not catalog:
            return {}
        return {
            "intent": catalog.get("intent") or "general",
            "q": catalog.get("q") or "",
            "search_payload": dict(catalog["searchPayload"])
            if isinstance(catalog.get("searchPayload"), dict)
            else None,
        }
