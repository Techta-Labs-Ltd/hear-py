from __future__ import annotations

import pytest

from src.alexa.dialog import DialogStateManager
from src.alexa.direct_intents import DirectIntentPolicy
from src.alexa.resolver_runner import ResolverWorkflowRunner
from src.middleware.direct_intent import DirectIntentPhraseInterceptor


@pytest.mark.parametrize(
    ("phrase", "target", "speed"),
    (
        ("what's trending", "WhatsTrendingIntent", None),
        ("what do you recommended", "PlayRecommendationIntent", None),
        ("increase speed", "IncreaseSpeedIntent", None),
        ("decrease speed", "DecreaseSpeedIntent", None),
        ("normal speed", "SetPlaybackSpeedIntent", "normal"),
        ("feedback check", "RateContentIntent", None),
        ("check my updates", "HearNotificationsIntent", None),
        ("pause", "AMAZON.PauseIntent", None),
        ("follow this creator", "FollowCreatorIntent", None),
    ),
)
@pytest.mark.asyncio
async def test_global_interceptor_routes_direct_phrases_before_resolver(
    mock_intent_request, phrase, target, speed
):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        "onboardingComplete": True
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "SearchContentIntent"
    intent["slots"] = {"searchQuery": {"name": "searchQuery", "value": phrase}}

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    assert intent["name"] == target
    if speed:
        assert intent["slots"] == {"speed": {"name": "speed", "value": speed}}
    assert ResolverWorkflowRunner._request(mock_intent_request) is None


@pytest.mark.asyncio
async def test_global_interceptor_does_not_steal_an_active_dialog_answer(mock_intent_request):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        "onboardingComplete": True
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "SearchContentIntent"
    intent["slots"] = {"searchQuery": {"name": "searchQuery", "value": "pause"}}
    DialogStateManager.activate(mock_intent_request, "ambiguity", context={"candidates": []})

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    assert intent["name"] == "SearchContentIntent"


@pytest.mark.parametrize("intent_name", sorted(DirectIntentPolicy.BYPASS_RESOLVER_INTENTS))
def test_all_direct_command_intents_bypass_the_resolver(mock_intent_request, intent_name):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        "onboardingComplete": True
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = intent_name
    intent["slots"] = {"query": {"name": "query", "value": "anything"}}

    assert ResolverWorkflowRunner._request(mock_intent_request) is None
@pytest.mark.parametrize(
    ("source_intent", "phrase", "target_intent", "expected_slots"),
    (
        (
            "SearchOrganizationIntent",
            "play from talking",
            "ChooseSourceKindIntent",
            {"sourceKind": "talking newspaper"},
        ),
        (
            "SearchCreatorIntent",
            "a creator",
            "ChooseSourceKindIntent",
            {"sourceKind": "creator"},
        ),
        (
            "SearchContentIntent",
            "content from my local community",
            "PlayLocalIntent",
            {"localQuery": "content from my local community"},
        ),
    ),
)
@pytest.mark.asyncio
async def test_global_interceptor_routes_generic_source_patterns_only(
    mock_intent_request, source_intent, phrase, target_intent, expected_slots
):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        "onboardingComplete": True
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = source_intent
    intent["slots"] = {"searchQuery": {"name": "searchQuery", "value": phrase}}

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    assert intent["name"] == target_intent
    assert {
        name: value["value"] for name, value in intent["slots"].items()
    } == expected_slots


@pytest.mark.asyncio
async def test_global_interceptor_preserves_a_specific_source_search(mock_intent_request):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        "onboardingComplete": True
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "SearchOrganizationIntent"
    intent["slots"] = {
        "searchQuery": {"name": "searchQuery", "value": "Dorking Talking News"}
    }

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    assert intent["name"] == "SearchOrganizationIntent"