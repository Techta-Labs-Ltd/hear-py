from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


async def prefetch_search_queue_items(
    search_result: dict[str, Any],
    hear_client,
    *,
    timeout_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Return queue entries for every page represented by a search result.

    The first page retains its normalized content snapshots. Later pages are
    reduced to content IDs because navigation resolves the selected recording
    on demand and DynamoDB should not retain every page's audio metadata.
    """
    first_page = list(search_result.get("results") or [])
    queue_items: list[dict[str, Any]] = list(first_page)
    seen_ids = {
        str(item.get("contentId") or item.get("id"))
        for item in first_page
        if isinstance(item, dict) and (item.get("contentId") or item.get("id"))
    }

    total_pages = search_result.get("total_pages")
    current_page = search_result.get("page", 0)
    payload = search_result.get("_search_payload")
    if (
        not isinstance(total_pages, (int, float))
        or not isinstance(current_page, (int, float))
        or int(total_pages) <= int(current_page) + 1
        or not isinstance(payload, dict)
    ):
        return queue_items

    for page in range(int(current_page) + 1, int(total_pages)):
        page_payload = {**payload, "page": page}
        result = await hear_client.search(page_payload, timeout_ms=timeout_ms)
        if result.get("failed"):
            logger.warning(
                "Hear: queue prefetch stopped page=%s totalPages=%s",
                page,
                int(total_pages),
            )
            break
        for item in result.get("results") or []:
            if not isinstance(item, dict):
                continue
            content_id = item.get("contentId") or item.get("id")
            if not content_id or str(content_id) in seen_ids:
                continue
            seen_ids.add(str(content_id))
            queue_items.append({"contentId": str(content_id)})

    logger.info(
        "Hear: queue prefetch complete pages=%s queuedContentIds=%s",
        int(total_pages),
        len(seen_ids),
    )
    return queue_items
