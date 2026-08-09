from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_MAX_PREFETCH_BUDGET_MS = 6000
_QUEUE_PREFETCH_PAGE_LIMIT = 100
_BULK_PREFETCH_THRESHOLD_PAGES = 12


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

    request_timeout_ms = min(timeout_ms or _MAX_PREFETCH_BUDGET_MS, _MAX_PREFETCH_BUDGET_MS)
    deadline = time.monotonic() + (request_timeout_ms / 1000)
    fetch_payload = dict(payload)
    pages = list(range(int(current_page) + 1, int(total_pages)))
    if int(current_page) == 0 and int(total_pages) > _BULK_PREFETCH_THRESHOLD_PAGES:
        fetch_payload["limit"] = max(
            int(fetch_payload.get("limit") or 0),
            _QUEUE_PREFETCH_PAGE_LIMIT,
        )
        pages = [0]

    page_index = 0
    while page_index < len(pages):
        page = pages[page_index]
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            logger.warning(
                "Hear: queue prefetch stopped page=%s totalPages=%s timedOut=True",
                page,
                int(total_pages),
            )
            break
        page_payload = {**fetch_payload, "page": page}
        try:
            result = await asyncio.wait_for(
                hear_client.search(
                    page_payload,
                    timeout_ms=min(remaining_ms, request_timeout_ms),
                ),
                timeout=remaining_ms / 1000,
            )
        except TimeoutError:
            logger.warning(
                "Hear: queue prefetch stopped page=%s totalPages=%s timedOut=True",
                page,
                int(total_pages),
            )
            break
        if result.get("failed"):
            logger.warning(
                "Hear: queue prefetch stopped page=%s totalPages=%s timedOut=False",
                page,
                int(total_pages),
            )
            break
        if pages == [0]:
            bulk_total_pages = result.get("total_pages")
            if isinstance(bulk_total_pages, (int, float)):
                pages.extend(range(1, int(bulk_total_pages)))
        for item in result.get("results") or []:
            if not isinstance(item, dict):
                continue
            content_id = item.get("contentId") or item.get("id")
            if not content_id or str(content_id) in seen_ids:
                continue
            seen_ids.add(str(content_id))
            queue_items.append({"contentId": str(content_id)})
        page_index += 1

    logger.info(
        "Hear: queue prefetch complete pages=%s queuedContentIds=%s",
        int(total_pages),
        len(seen_ids),
    )
    return queue_items
