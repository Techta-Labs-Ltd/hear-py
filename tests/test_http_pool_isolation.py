from __future__ import annotations

import httpx
import pytest

from src.clients.hear import HearApiClient, HearApiOptions
from src.clients.pool import HttpPool
from src.clients.resolver import ResolverClient, ResolverOptions


@pytest.fixture
def isolated_transport(monkeypatch):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )


@pytest.mark.asyncio
async def test_pools_keep_upstream_authentication_separate(monkeypatch):
    calls = []
    original = httpx.AsyncClient

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={})

    def client(**kwargs):
        return original(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    hear = HttpPool(base_url="https://catalogue.test/api/v1", headers={"X-Api-Key": "hear-key"})
    resolver = HttpPool(base_url="https://resolver.test", headers={"X-Api-Key": "resolver-key"})
    try:
        assert hear.get() is hear.get()
        assert hear.get() is not resolver.get()
        await hear.get().post("/search")
        await resolver.get().post("/resolve")
        assert [(request.url.host, request.headers["x-api-key"]) for request in calls] == [
            ("catalogue.test", "hear-key"),
            ("resolver.test", "resolver-key"),
        ]
    finally:
        await hear.close()
        await resolver.close()
    assert hear.active_client_count() == resolver.active_client_count() == 0


def test_pool_rejects_conflicting_api_client_configuration():
    pool = HttpPool(base_url="https://catalogue.test", headers={"X-Api-Key": "one"})
    HearApiClient(HearApiOptions(base_url="https://catalogue.test/", api_key="one"), pool=pool)
    with pytest.raises(ValueError, match="configuration"):
        HearApiClient(HearApiOptions(base_url="https://catalogue.test", api_key="two"), pool=pool)
    with pytest.raises(ValueError, match="configuration"):
        ResolverClient(ResolverOptions(host="https://resolver.test", api_key="one"), pool=pool)


@pytest.mark.asyncio
async def test_caller_cannot_modify_pool_headers_or_send_them_to_another_host(isolated_transport):
    headers = {"X-Api-Key": "one"}
    pool = HttpPool(base_url="https://catalogue.test", headers=headers)
    headers["X-Api-Key"] = "two"
    pool.assert_configuration(base_url="https://catalogue.test", headers={"x-api-key": "one"})
    try:
        with pytest.raises(ValueError, match="upstream"):
            await pool.get().post("https://other.test/steal")
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_closed_client_is_replaced_within_the_same_loop(isolated_transport):
    pool = HttpPool(base_url="https://catalogue.test")
    first = pool.get()
    await first.aclose()
    second = pool.get()
    assert first is not second
    assert not second.is_closed
    await pool.close()
