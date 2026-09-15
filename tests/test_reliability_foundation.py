from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from config import settings
from src.application import Application
from src.clients.resolver import ResolverClient, ResolverOptions
from src.constants.state import StateSchema
from src.database.persistence import MemoryPersistenceAdapter
from src.models.user import User
from src.services.events import OutboundEventService
from src.utils.events import EventUtils


@pytest.mark.parametrize("stage", ["staging", "production", " PRODUCTION "])
def test_deployed_memory_driver_is_rejected(monkeypatch, stage):
    monkeypatch.setattr(settings, "STAGE", stage)
    monkeypatch.setattr(settings, "HEAR_PERSISTENCE_DRIVER", "memory")
    with pytest.raises(RuntimeError, match="durable"):
        Application.build_persistence_adapter()


def test_unknown_persistence_driver_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "HEAR_PERSISTENCE_DRIVER", "dynmodb")
    with pytest.raises(ValueError, match="driver"):
        Application.build_persistence_adapter()


@pytest.mark.parametrize(
    "identity",
    [
        {"listener_id": "listener-1"},
        {"alexa_user_id": "user-1"},
        {"listener_id": "listener-1", "alexa_user_id": "user-1"},
    ],
)
@pytest.mark.asyncio
async def test_personal_resolver_requests_never_use_shared_cache(identity):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "resolved",
                "intent": "search",
                "entities": [],
                "slots": {},
                "ambiguities": [],
                "timingMs": 1,
            },
        )

    client = ResolverClient(ResolverOptions(api_key="test", transport=httpx.MockTransport(respond)))
    await client.resolve("local news", **identity)
    await client.resolve("local news", **identity)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_anonymous_resolver_cache_owns_independent_results():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "status": "resolved",
                "intent": "search",
                "slots": {"query": "news"},
                "entities": [],
                "ambiguities": [],
                "timingMs": 1,
            },
        )

    client = ResolverClient(ResolverOptions(api_key="test", transport=httpx.MockTransport(respond)))
    first = await client.resolve("news")
    first.slots["query"] = "corrupted"
    second = await client.resolve("news")
    assert second.slots["query"] == "news"
    assert len(calls) == 1


def test_hydrated_defaults_and_snapshots_do_not_share_nested_values(mock_handler_input):
    one = User.merge_persisted({})
    two = User.merge_persisted({})
    one["pendingSuggestions"].append({"id": "one"})
    assert two["pendingSuggestions"] == []
    assert StateSchema.default_for("pendingSuggestions") == []
    User.hydrate(mock_handler_input, {"pendingSuggestions": [{"id": "saved"}]})
    snapshot = User.snapshot(mock_handler_input)
    snapshot["pendingSuggestions"][0]["id"] = "changed"
    assert User.snapshot(mock_handler_input)["pendingSuggestions"] == [{"id": "saved"}]


@pytest.mark.asyncio
async def test_memory_adapter_copies_nested_values_on_write_and_read():
    adapter = MemoryPersistenceAdapter()
    envelope = {"context": {"System": {"user": {"userId": "one"}}}}
    state = {"pendingSuggestions": [{"id": "saved"}]}
    await adapter.save_attributes(envelope, state)
    state["pendingSuggestions"][0]["id"] = "external mutation"
    first = await adapter.get_attributes(envelope)
    assert first["pendingSuggestions"] == [{"id": "saved"}]
    first["pendingSuggestions"].clear()
    assert (await adapter.get_attributes(envelope))["pendingSuggestions"] == [{"id": "saved"}]


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "{}",
        "[]",
        "null",
        '{"schemaVersion": 99}',
        '{"event": "feedback.given", "data": {}}',
    ],
)
@pytest.mark.asyncio
async def test_invalid_worker_records_are_failed_and_never_delivered(body):
    webhook = SimpleNamespace(send=AsyncMock(return_value=True))
    result = await OutboundEventService(webhook=webhook).consume(
        [{"messageId": "bad", "body": body}]
    )
    assert result == {"batchItemFailures": [{"itemIdentifier": "bad"}]}
    webhook.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_exception_fails_one_record_and_continues():
    envelope = EventUtils.envelope(
        "feedback.given", {"alexaUserId": "user", "clientEventId": "event"}
    )
    webhook = SimpleNamespace(send=AsyncMock(side_effect=[RuntimeError("offline"), True]))
    records = [
        {"messageId": message, "body": json.dumps(envelope)} for message in ["first", "second"]
    ]
    result = await OutboundEventService(webhook=webhook).consume(records)
    assert result == {"batchItemFailures": [{"itemIdentifier": "first"}]}
    assert webhook.send.await_count == 2


@pytest.mark.asyncio
async def test_missing_sqs_identifier_fails_the_batch_before_delivery():
    webhook = SimpleNamespace(send=AsyncMock(return_value=True))
    with pytest.raises(ValueError, match="messageId"):
        await OutboundEventService(webhook=webhook).consume([{"body": "{}"}])
    webhook.send.assert_not_awaited()
