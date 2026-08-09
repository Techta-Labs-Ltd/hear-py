from __future__ import annotations

import asyncio

import pytest

from src.services.search_queue import prefetch_search_queue_items


@pytest.mark.asyncio
async def test_prefetch_preserves_page_order_when_requests_finish_out_of_order():
    class HearClient:
        async def search(self, payload, *, timeout_ms=None):
            page = payload["page"]
            await asyncio.sleep((4 - page) * 0.001)
            return {
                "results": [{"contentId": f"content-{page}"}],
                "failed": False,
            }

    items = await prefetch_search_queue_items(
        {
            "results": [{"contentId": "content-0"}],
            "page": 0,
            "total_pages": 4,
            "_search_payload": {"query": "news", "page": 0},
        },
        HearClient(),
        timeout_ms=1000,
    )

    assert [item["contentId"] for item in items] == [
        "content-0", "content-1", "content-2", "content-3",
    ]


@pytest.mark.asyncio
async def test_prefetch_returns_first_page_when_later_pages_exceed_budget():
    class HearClient:
        async def search(self, payload, *, timeout_ms=None):
            await asyncio.sleep(1)
            return {"results": [{"contentId": "late"}], "failed": False}

    items = await prefetch_search_queue_items(
        {
            "results": [{"contentId": "content-0"}],
            "page": 0,
            "total_pages": 10,
            "_search_payload": {"query": "news", "page": 0},
        },
        HearClient(),
        timeout_ms=10,
    )

    assert items == [{"contentId": "content-0"}]
