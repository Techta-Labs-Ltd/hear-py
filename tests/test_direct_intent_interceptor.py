from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.alexa.dialog import DialogStateManager
from src.alexa.direct_intents import DirectIntentPolicy
from src.alexa.resolver_runner import ResolverWorkflowRunner
from src.constants.state import StateSchema
from src.controllers.browse import BrowseNavigationHandler
from src.controllers.playback_controls import (
    FastForwardIntentHandler,
    NextIntentHandler,
    PauseIntentHandler,
    PreviousIntentHandler,
    RepeatIntentHandler,
    ResumeIntentHandler,
    RewindIntentHandler,
)
from src.controllers.system import HelpIntentHandler, HelpMoreIntentHandler
from src.middleware.dialog_validation import DialogValidationPolicy
from src.middleware.direct_intent import DirectIntentPhraseInterceptor
from src.registry import RouteRegistry


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
        ("set up my account", "SetUpAccountIntent", None),
        ("pause", "AMAZON.PauseIntent", None),
        ("help", "AMAZON.HelpIntent", None),
        ("next", "AMAZON.NextIntent", None),
        ("repeat", "AMAZON.RepeatIntent", None),
        ("restart", "AMAZON.StartOverIntent", None),
        ("start over", "AMAZON.StartOverIntent", None),
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
async def test_global_interceptor_finds_a_direct_command_in_a_secondary_slot(
    mock_intent_request,
):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        "onboardingComplete": True
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "SearchContentIntent"
    intent["slots"] = {
        "searchQuery": {"name": "searchQuery", "value": "morning news"},
        "feedbackPhrase": {"name": "feedbackPhrase", "value": "set up my account"},
    }

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    assert intent["name"] == "SetUpAccountIntent"
    assert ResolverWorkflowRunner._request(mock_intent_request) is None


@pytest.mark.parametrize(
    ("phrase", "expected_handler"),
    (
        ("help", HelpIntentHandler),
        ("pause", PauseIntentHandler),
        ("resume", ResumeIntentHandler),
        ("next", NextIntentHandler),
        ("previous recording", PreviousIntentHandler),
        ("repeat", RepeatIntentHandler),
        ("restart", RepeatIntentHandler),
        ("start over", RepeatIntentHandler),
        ("rewind", RewindIntentHandler),
        ("fast forward", FastForwardIntentHandler),
    ),
)
@pytest.mark.asyncio
async def test_gated_control_phrase_is_forwarded_to_its_handler(
    mock_intent_request, phrase, expected_handler
):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        "onboardingComplete": True
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "SearchContentIntent"
    intent["slots"] = {"searchQuery": {"name": "searchQuery", "value": phrase}}

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    handler = (
        expected_handler()
        if expected_handler is HelpIntentHandler
        else expected_handler(SimpleNamespace())
    )
    assert handler.can_handle(mock_intent_request)


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


@pytest.mark.asyncio
async def test_global_interceptor_routes_confident_control_typo_inside_active_dialog(
    mock_intent_request,
):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        "onboardingComplete": True
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "SearchContentIntent"
    intent["slots"] = {
        "searchQuery": {"name": "searchQuery", "value": "increament spede"}
    }
    DialogStateManager.activate(mock_intent_request, "ambiguity", context={"candidates": []})

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    assert intent["name"] == "IncreaseSpeedIntent"
    assert DialogValidationPolicy.dialog_validation_failure(mock_intent_request) is None


@pytest.mark.asyncio
async def test_help_dialog_routes_more_to_next_without_resolver(mock_intent_request):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        "onboardingComplete": True
    }
    DialogStateManager.activate(mock_intent_request, "help")
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "SearchContentIntent"
    intent["slots"] = {"searchQuery": {"name": "searchQuery", "value": "more"}}

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    assert intent["name"] == "AMAZON.NextIntent"
    assert ResolverWorkflowRunner._request(mock_intent_request) is None
    assert HelpMoreIntentHandler().can_handle(mock_intent_request)
    assert RouteRegistry.REQUEST_CONTROLLERS.index(HelpMoreIntentHandler) < (
        RouteRegistry.REQUEST_CONTROLLERS.index(BrowseNavigationHandler)
    )


@pytest.mark.asyncio
async def test_feedback_dialog_reroutes_report_content_to_an_unanswered_feedback_response(
    mock_intent_request,
):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingFeedback": True,
        "pendingFeedback": {"contentId": "content-1", "title": "Morning update"},
    }
    DialogStateManager.activate(
        mock_intent_request,
        "feedback",
        context={"contentId": "content-1", "title": "Morning update"},
    )
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "ReportContentIntent"
    intent["slots"] = {}

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    assert intent == {"name": "FeedbackResponseIntent", "slots": {}}
    assert DialogValidationPolicy.dialog_validation_failure(mock_intent_request) is None


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
