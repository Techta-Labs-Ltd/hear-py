from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import main
from src.models.resolver import ResolverResult, ResolverUnavailable


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
    assert await main._application.resolver_healthcheck(deps=deps) == {
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
    assert await main._application.resolver_healthcheck(deps=deps) == {
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
    application._dependencies = SimpleNamespace(events=SimpleNamespace(consume=consume))
    event = {
        "Records": [
            {"messageId": "message-1", "body": "{}"},
            {"messageId": "message-2", "body": "{}"},
        ]
    }

    result = application.handle(event, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "message-2"}]}
    consume.assert_awaited_once_with(event["Records"])


async def _running_loop():
    return asyncio.get_running_loop()
