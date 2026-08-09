from __future__ import annotations

import asyncio

import pytest

from src.services.search_queue import prefetch_search_queue_items


@pytest.mark.asyncio
async def test_prefetch_preserves_page_order():
    class HearClient:
        async def search(self, payload, *, timeout_ms=None):
            page = payload["page"]
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


@pytest.mark.asyncio
async def test_large_queue_uses_bulk_pages_without_concurrent_requests():
    class HearClient:
        def __init__(self):
            self.calls = []
            self.active = 0

        async def search(self, payload, *, timeout_ms=None):
            self.active += 1
            assert self.active == 1
            self.calls.append(dict(payload))
            await asyncio.sleep(0)
            self.active -= 1
            page = payload["page"]
            return {
                "results": [{"contentId": f"content-{page + 1}"}],
                "total_pages": 3,
                "page": page,
                "failed": False,
            }

    client = HearClient()
    items = await prefetch_search_queue_items(
        {
            "results": [{"contentId": "content-0"}],
            "page": 0,
            "total_pages": 334,
            "_search_payload": {"query": "", "page": 0, "limit": 3},
        },
        client,
        timeout_ms=1000,
    )

    assert [call["page"] for call in client.calls] == [0, 1, 2]
    assert all(call["limit"] == 100 for call in client.calls)
    assert [item["contentId"] for item in items] == [
        "content-0", "content-1", "content-2", "content-3",
    ]
