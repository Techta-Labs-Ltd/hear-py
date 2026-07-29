from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.handlers.intents.launch import TownCaptureHandler
from src.middleware.pipeline import REQUEST_INTERCEPTORS
from src.nlp import NlpInterceptor
from src.runtime import AttrDict
from src.services.storage.persistence import DEFAULT_STORE, get_store


def _town_request(mock_handler_input, value: str):
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "TownCaptureIntent",
            "slots": {
                "townName": {
                    "name": "townName",
                    "value": value,
                },
            },
        },
    })
    store = {**DEFAULT_STORE, "onboardingStage": "ask_town"}
    mock_handler_input.attributes_manager.request_attributes["_store"] = store
    return mock_handler_input


@pytest.mark.asyncio
async def test_misspelled_bare_town_is_owned_by_onboarding(mock_handler_input):
    handler_input = _town_request(mock_handler_input, "swidon")
    await NlpInterceptor().process(handler_input)

    assert TownCaptureHandler().can_handle(handler_input)
    await TownCaptureHandler().handle(handler_input)

    store = get_store(handler_input)
    assert store["pendingLocationConfirm"]["city"] == "Swindon"
    assert store["awaitingLocationConfirm"] is True


def test_generic_search_confirmation_interceptor_is_not_registered():
    assert all(
        interceptor.__name__ != "ConfirmationMiddleware"
        for interceptor in REQUEST_INTERCEPTORS
    )


@pytest.mark.asyncio
async def test_unresolved_creator_name_falls_back_to_search_query(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.intents.play import discover_content_via_search

    handler_input = _town_request(mock_handler_input, "swidon")
    handler_input.attributes_manager.request_attributes["_nlp"] = {
        "intent": "category",
        "slots": {
            "category": "sports",
            "latest": True,
            "residualQuery": "david",
            "unresolvedReferences": [{
                "relation": "from",
                "phrase": "david",
                "expectedTypes": ["creator", "organization", "publication"],
            }],
        },
    }
    search = AsyncMock(return_value={
        "failed": False,
        "results": [],
        "total_hits": 0,
    })
    monkeypatch.setattr("src.handlers.intents.play.search", search)

    await discover_content_via_search(
        handler_input,
        {"q": "", "intent": "category"},
    )

    payload = search.await_args.args[0]
    assert payload["query"] == "david"
    assert payload["filter"]["categorySlugs"] == ["sports"]
    assert payload["sort"] == "latest"


@pytest.mark.asyncio
async def test_organization_handler_reads_its_declared_alexa_slot(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.intents.play import PlayByOrganizationHandler

    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayByOrganizationIntent",
            "slots": {
                "organizationQuery": {
                    "name": "organizationQuery",
                    "value": "tnf",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
    }
    discover = AsyncMock(return_value={
        "failed": False,
        "results": [],
        "total_hits": 0,
    })
    monkeypatch.setattr(
        "src.handlers.intents.play.discover_content_via_search", discover,
    )

    await PlayByOrganizationHandler().handle(mock_handler_input)

    assert discover.await_args_list[0].args[1] == {
        "q": "tnf",
        "intent": "organization",
    }


@pytest.mark.asyncio
async def test_resolved_organization_uses_residual_topic_without_reprompting(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.intents.play import PlayByOrganizationHandler

    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            # Alexa may initially select the creator carrier phrase; local NLP
            # redirects it to the organization handler.
            "name": "PlayByCreatorIntent",
            "slots": {
                "creatorQuery": {
                    "name": "creatorQuery",
                    "value": "heatwave from ytn",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes.update({
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_nlp": {
            "intent": "organization",
            "slots": {
                "organizationIds": ["org-ytn"],
                "organizationName": "York Talking News",
                "residualQuery": "heatwave",
                "latest": False,
            },
        },
    })
    discover = AsyncMock(return_value={
        "failed": False,
        "results": [],
        "total_hits": 0,
    })
    monkeypatch.setattr(
        "src.handlers.intents.play.discover_content_via_search", discover,
    )

    await PlayByOrganizationHandler().handle(mock_handler_input)

    assert discover.await_args_list[0].args[1] == {
        "q": "heatwave",
        "intent": "organization",
    }


@pytest.mark.asyncio
async def test_generic_talking_newspaper_request_prompts_and_persists_context(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.intents.play import PlayByOrganizationHandler

    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayByOrganizationIntent",
            "slots": {
                "organizationQuery": {
                    "name": "organizationQuery",
                    "value": "talking news paper",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes.update({
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_nlp": {
            "intent": "organization",
            "slots": {"genericOrganizationRequest": True},
        },
    })
    discover = AsyncMock()
    monkeypatch.setattr(
        "src.handlers.intents.play.discover_content_via_search", discover,
    )

    await PlayByOrganizationHandler().handle(mock_handler_input)

    assert get_store(mock_handler_input)["awaitingOrganizationName"] is True
    discover.assert_not_awaited()


@pytest.mark.asyncio
async def test_talking_newspaper_follow_up_forces_organization_resolution(
    monkeypatch,
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayContentIntent",
            "slots": {
                "topic": {"name": "topic", "value": "ynt"},
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingOrganizationName": True,
    }
    resolved = {
        "intent": "organization",
        "confidence": "high",
        "slots": {
            "organizationIds": ["org-ytn"],
            "organizationName": "York Talking News",
            "residualQuery": "",
        },
    }
    monkeypatch.setattr(
        "src.nlp.resolve_organization_follow_up",
        lambda utterance: resolved,
    )

    await NlpInterceptor().process(mock_handler_input)

    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "organization"
    assert nlp["slots"]["organizationIds"] == ["org-ytn"]
    assert nlp["slots"]["organizationQuery"] == "ynt"
    assert nlp["slots"]["organizationFollowUp"] is True


@pytest.mark.asyncio
async def test_location_follow_up_yes_executes_community_search(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.intents.system import YesIntentHandler

    handler_input = _town_request(mock_handler_input, "Manchester")
    store = get_store(handler_input)
    store.update({
        "userCity": "Manchester",
        "locality": "Manchester",
        "onboardingComplete": True,
        "onboardingStage": None,
        "awaitingCommunityPlayback": True,
    })
    handler_input.attributes_manager.request_attributes["_store"] = store
    discover = AsyncMock(return_value={
        "failed": False,
        "results": [{
            "contentId": "content-1",
            "title": "Manchester update",
            "spokenTitle": "Manchester update",
            "audioUrl": "https://cdn.hear.media/content-1.mp3",
        }],
    })
    play = AsyncMock(return_value={"response": "playing"})
    monkeypatch.setattr(
        "src.handlers.intents.system.discover_content_via_search",
        discover,
    )
    monkeypatch.setattr(
        "src.handlers.intents.system.auto_play_first_from_search",
        play,
    )

    response = await YesIntentHandler()._handle_community_play_yes(
        handler_input,
        store,
    )

    assert response == {"response": "playing"}
    assert get_store(handler_input)["awaitingCommunityPlayback"] is False
    nlp = handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["slots"]["city"] == "Manchester"
    assert nlp["slots"]["isLocal"] is True
