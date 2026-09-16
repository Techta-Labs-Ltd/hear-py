from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.alexa.phrase_router import PhraseRouter
from src.container import ApplicationContainer
from src.models.resolver_inputs import ResolverSlot
from src.models.resolver_workflow import ResolverWorkflow


@pytest.mark.parametrize(
    ("phrase", "intent_name", "slots"),
    (
        ("what's trending content on sport", "WhatsTrendingIntent", {"topic": "sport"}),
        ("popular picks", "WhatsTrendingIntent", {}),
        (
            "recommend me local history",
            "PlayRecommendationIntent",
            {"recommendationQuery": "local history"},
        ),
        ("play from talking", "ChooseSourceKindIntent", {"sourceKind": "talking newspaper"}),
        ("play talking", "ChooseSourceKindIntent", {"sourceKind": "talking newspaper"}),
        ("talking talking newspaper", "ChooseSourceKindIntent", {"sourceKind": "talking newspaper"}),
        ("a creator", "ChooseSourceKindIntent", {"sourceKind": "creator"}),
        ("content from my local community", "PlayLocalIntent", {"localQuery": "content from my local community"}),
        ("please increase speed", "IncreaseSpeedIntent", {}),
        ("normal speed", "SetPlaybackSpeedIntent", {"speed": "normal"}),
    ),
)
def test_phrase_router_classifies_normalized_command_families(phrase, intent_name, slots):
    route = PhraseRouter.classify(phrase)

    assert route is not None
    assert route.intent_name == intent_name
    assert {
        name: value["value"] for name, value in route.slot_map().items()
    } == slots


@pytest.mark.parametrize(
    "phrase",
    ("content on climate change", "content from Dorking News", "play history by David Beard"),
)
def test_phrase_router_preserves_meaningful_searches(phrase):
    assert PhraseRouter.classify(phrase) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase",
    ("play from talking", "talking talking newspaper", "a creator", "content from my local community"),
)
async def test_generic_source_and_local_routes_do_not_call_the_remote_resolver(
    mock_intent_request, phrase
):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        "onboardingComplete": True,
        "listenerId": "listener-1",
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "SearchContentIntent"
    route = PhraseRouter.classify(phrase)
    assert route is not None
    intent["name"] = route.intent_name
    intent["slots"] = route.slot_map()

    resolver = AsyncMock()
    container = ApplicationContainer(resolver=resolver, progressive=AsyncMock())
    await container.build_resolver_interceptor().process(mock_intent_request)

    resolver.resolve_utterance.assert_not_awaited()


def test_local_community_route_builds_a_local_discovery_result():
    route = PhraseRouter.classify("content from my local community")
    assert route is not None
    slots = {
        name: ResolverSlot(resolved=value["value"], spoken=value["value"])
        for name, value in route.slot_map().items()
    }

    result = ResolverWorkflow._local_discovery_resolution(
        route.intent_name,
        slots,
        "content from my local community",
    )

    assert result is not None
    assert result["intent"] == "local"
    assert result["localResolved"] is True