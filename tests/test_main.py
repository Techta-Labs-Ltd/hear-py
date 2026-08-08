from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import main
from src.models import ResolverResult, ResolverUnavailable


@pytest.mark.asyncio
async def test_resolver_healthcheck_reports_canonical_town(monkeypatch):
    result = ResolverResult.from_payload({
        "status": "resolved",
        "intent": "search",
        "entities": [{
            "entityType": "location",
            "entityId": "location-1",
            "canonicalValue": "Herne Bay",
            "originalText": "herne bay",
            "confidence": 1,
            "method": "exact",
            "start": 0,
            "end": 9,
            "latitude": 51.37,
            "longitude": 1.13,
            "countryCode": "gb",
        }],
        "slots": {},
        "ambiguities": [],
        "timingMs": 10,
    })
    monkeypatch.setattr(
        main,
        "resolver_client",
        SimpleNamespace(resolve=AsyncMock(return_value=result)),
    )

    assert await main._resolver_healthcheck() == {
        "ok": True,
        "service": "resolver",
        "status": "resolved",
        "canonicalValue": "Herne Bay",
    }


@pytest.mark.asyncio
async def test_resolver_healthcheck_returns_safe_failure_reason(monkeypatch):
    monkeypatch.setattr(main, "resolver_client", SimpleNamespace(
        resolve=AsyncMock(side_effect=ResolverUnavailable("resolver returned HTTP 401")),
    ))

    assert await main._resolver_healthcheck() == {
        "ok": False,
        "service": "resolver",
        "reason": "resolver returned HTTP 401",
    }
