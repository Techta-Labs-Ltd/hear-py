from __future__ import annotations

import logging
from typing import Any

from config import settings
from src.services.queue import read_playback_queue
from src.services.store import get_store, update_store
from src.utils.normalize_content_item import is_playable_content_item
from src.utils.skill_request import get_user_id

logger = logging.getLogger(__name__)


def initial_search_queue_items(search_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only the API page already loaded for immediate playback."""
    return [item for item in (search_result.get("results") or []) if isinstance(item, dict)]


def search_queue_pagination(search_result: dict[str, Any]) -> dict[str, Any]:
    """Build persisted lazy-pagination arguments for ``init_queue``."""
    payload = search_result.get("_search_payload")
    return {
        "search_payload": dict(payload) if isinstance(payload, dict) else None,
        "current_page": int(search_result.get("page") or 0),
        "total_pages": search_result.get("total_pages"),
        "page_limit": (
            payload.get("limit") if isinstance(payload, dict) else None
        ),
    }


async def load_next_search_queue_page(handler_input, hear_client) -> bool:
    """Append one server page when playback reaches the loaded queue boundary."""
    queue = read_playback_queue(get_store(handler_input))
    pagination = queue.get("pagination") if queue else None
    if not queue or not isinstance(pagination, dict):
        return False

    current_page = int(pagination.get("currentPage") or 0)
    total_pages = int(pagination.get("totalPages") or 0)
    if total_pages <= 0 or current_page + 1 >= total_pages:
        return False

    payload = dict(pagination.get("searchPayload") or {})
    next_page = current_page + 1
    payload.update({
        "page": next_page,
        "limit": int(pagination.get("limit") or payload.get("limit") or 3),
    })
    user_id = get_user_id(handler_input)
    if user_id:
        payload["alexaUserId"] = user_id

    result = await hear_client.search(payload)
    if result.get("failed"):
        logger.warning(
            "Hear: lazy queue page failed page=%s totalPages=%s",
            next_page,
            total_pages,
        )
        return False

    existing_ids = list(queue["orderedContentIds"])
    previous_count = len(existing_ids)
    seen = set(existing_ids)
    page_items = [
        item for item in (result.get("results") or [])
        if isinstance(item, dict)
    ]
    for item in page_items:
        content_id = item.get("contentId") or item.get("id")
        if content_id and str(content_id) not in seen:
            seen.add(str(content_id))
            existing_ids.append(str(content_id))

    queue["orderedContentIds"] = existing_ids
    pagination["currentPage"] = int(result.get("page") or next_page)
    if isinstance(result.get("total_pages"), (int, float)):
        pagination["totalPages"] = int(result["total_pages"])
    queue["pagination"] = pagination

    store = get_store(handler_input)
    catalog = dict(store.get("browseCatalog") or {})
    catalog_items = list(catalog.get("items") or [])
    cached_ids = {
        str(item.get("contentId") or item.get("id"))
        for item in catalog_items
        if isinstance(item, dict) and (item.get("contentId") or item.get("id"))
    }
    for item in page_items:
        content_id = item.get("contentId") or item.get("id")
        if content_id and str(content_id) not in cached_ids and is_playable_content_item(item):
            cached_ids.add(str(content_id))
            catalog_items.append(item)
    if catalog:
        cache_limit = max(1, int(settings.HEAR_BROWSE_MAX_CATALOG or 50))
        if len(catalog_items) > cache_limit:
            catalog_items = catalog_items[-cache_limit:]
        catalog.update({
            "items": catalog_items,
            "currentPage": pagination["currentPage"],
            "totalPages": pagination["totalPages"],
        })

    update_store(handler_input, {
        "playbackQueue": queue,
        "browseCatalog": catalog or store.get("browseCatalog"),
    })
    logger.info(
        "Hear: lazy queue page loaded page=%s totalPages=%s loadedContentIds=%s",
        pagination["currentPage"],
        pagination["totalPages"],
        len(existing_ids),
    )
    return len(existing_ids) > previous_count
