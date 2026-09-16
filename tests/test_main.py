from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import main
from src.models.resolver import ResolverResult, ResolverUnavailable
from src.utils.deadline import RequestDeadline


@pytest.mark.asyncio
async def test_resolver_healthcheck_reports_canonical_town():
    result = ResolverResult.from_payload(
        {
            "status": "resolved",
            "intent": "search",
            "entities": [
                {
                    "entityType": "location",
                    "entityId": "location-1",
                    "canonicalValue": "Herne Bay",
                    "originalText": "herne bay",
                    "confidence": 100,
                    "method": "exact",
                    "start": 0,
                    "end": 9,
                    "latitude": 51.37,
                    "longitude": 1.13,
                    "countryCode": "gb",
                }
            ],
            "slots": {},
            "ambiguities": [],
            "timingMs": 10,
        }
    )
    deps = SimpleNamespace(resolver=SimpleNamespace(resolve=AsyncMock(return_value=result)))
    assert await main._application.resolver_healthcheck(container=deps) == {
        "ok": True,
        "service": "resolver",
        "status": "resolved",
        "canonicalValue": "Herne Bay",
    }


@pytest.mark.asyncio
async def test_resolver_healthcheck_returns_safe_failure_reason():
    deps = SimpleNamespace(
        resolver=SimpleNamespace(
            resolve=AsyncMock(side_effect=ResolverUnavailable("resolver returned HTTP 401"))
        )
    )
    assert await main._application.resolver_healthcheck(container=deps) == {
        "ok": False,
        "service": "resolver",
        "reason": "resolver returned HTTP 401",
    }


def test_lambda_runtime_reuses_one_event_loop():
    runtime = main.LambdaRuntime()
    first_loop = runtime.run(_running_loop())
    second_loop = runtime.run(_running_loop())
    assert first_loop is second_loop


def test_outbound_lambda_returns_partial_batch_response():
    application = main.OutboundLambdaApplication()
    consume = AsyncMock(return_value={"batchItemFailures": [{"itemIdentifier": "message-2"}]})
    application._events = SimpleNamespace(consume=consume)
    event = {
        "Records": [
            {"messageId": "message-1", "body": "{}"},
            {"messageId": "message-2", "body": "{}"},
        ]
    }

    result = application.handle(event, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "message-2"}]}
    consume.assert_awaited_once()
    assert consume.await_args.args == (event["Records"],)
    assert isinstance(consume.await_args.kwargs["deadline"], RequestDeadline)


def test_notification_lambda_returns_sqs_partial_batch_response():
    application = main.NotificationLambdaApplication()
    consume = AsyncMock(return_value={"batchItemFailures": [{"itemIdentifier": "message-2"}]})
    application._delivery = SimpleNamespace(consume=consume)
    event = {
        "Records": [
            {"messageId": "message-1", "body": "{}"},
            {"messageId": "message-2", "body": "{}"},
        ]
    }

    result = application.handle(event, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "message-2"}]}
    consume.assert_awaited_once()
    assert consume.await_args.args == (event["Records"],)
    assert isinstance(consume.await_args.kwargs["deadline"], RequestDeadline)


def test_workers_build_only_their_delivery_graph(monkeypatch):
    def fail_if_full_container_is_built(*_args, **_kwargs):
        raise AssertionError("worker constructed the full application container")

    monkeypatch.setattr(main, "ApplicationContainer", fail_if_full_container_is_built)

    assert main.OutboundLambdaApplication().events() is not None
    assert main.NotificationLambdaApplication().delivery() is not None


async def _running_loop():
    return asyncio.get_running_loop()
