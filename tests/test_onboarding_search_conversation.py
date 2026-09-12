from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.alexa.runtime import AttrDict, ResponseBuilder
from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech
from src.clients.hear import HearApiClient
from src.clients.resolver import ResolverClient, ResolverUnavailable
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.controllers.browse import BrowseNavigationHandler
from src.controllers.launch import TownCaptureHandler
from src.middleware.resolver import ResolverInterceptor
from src.models.dialog import DialogStateManager
from src.models.user import User
from src.registry import RouteRegistry


@pytest.mark.asyncio
async def test_something_else_leaves_ambiguity_and_returns_to_search(
    monkeypatch, mock_handler_input
):
    pending = {
        "candidates": [
            {"type": "publication", "id": "pub-1", "name": "First Publication"},
            {"type": "publication", "id": "pub-2", "name": "Second Publication"},
        ],
        "displayedCandidates": [
            {"type": "publication", "id": "pub-1", "name": "First Publication"},
            {"type": "publication", "id": "pub-2", "name": "Second Publication"},
        ],
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": "DismissChoicesIntent", "slots": {}}}
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    }
    mock_handler_input.response_builder = ResponseBuilder()
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    handler = BrowseNavigationHandler(deps=ApplicationContainer())

    resolve.assert_not_awaited()
    assert handler.can_handle(mock_handler_input) is True
    response = await handler.handle(mock_handler_input)

    assert "What would you like to listen to instead?" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False
    assert User.snapshot(mock_handler_input)["pendingAmbiguity"] is None
    assert User.snapshot(mock_handler_input)["activeDialog"] is None


def _town_request(mock_handler_input, value: str):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "TownCaptureIntent",
                "slots": {"townName": {"name": "townName", "value": value}},
            },
        }
    )
    store = {**StateSchema.DEFAULT_STORE, "onboardingStage": "ask_town"}
    mock_handler_input.attributes_manager.request_attributes["_store"] = store
    return mock_handler_input


def _intent_request(mock_handler_input, intent_name: str, slots: dict | None = None):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": intent_name, "slots": slots or {}},
        }
    )
    mock_handler_input.attributes_manager.get_session_attributes = lambda: {}
    return mock_handler_input


@pytest.mark.asyncio
async def test_bare_reply_during_search_confirmation_keeps_pending_resolution(
    monkeypatch, mock_handler_input
):
    from src.middleware.dialog_validation import (
        DialogValidationGateHandler,
        DialogValidationInterceptor,
    )

    _intent_request(
        mock_handler_input,
        "TownCaptureIntent",
        {"townName": {"name": "townName", "value": "seven ox"}},
    )
    old_resolution = {
        "confirmationLabel": "content in Dorking",
        "searchPayload": {"query": "", "filter": {"city": "Dorking"}},
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingSearchConfirmation": True,
        "pendingResolution": old_resolution,
        "activeDialog": {
            "type": "search_confirmation",
            "context": old_resolution,
            "expiresAt": 4102444800,
        },
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()

    DialogValidationInterceptor().process(mock_handler_input)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    response = DialogValidationGateHandler().handle(mock_handler_input)

    resolve.assert_not_awaited()
    question = "Did you want me to play content in Dorking? Please say yes or no."
    assert question in response["outputSpeech"]["ssml"]
    assert question in response["reprompt"]["outputSpeech"]["ssml"]
    store = User.snapshot(mock_handler_input)
    assert store["awaitingSearchConfirmation"] is True
    assert store["pendingResolution"] == old_resolution
    assert store["activeDialog"]["context"] == old_resolution


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slot_name", "raw"),
    [
        ("TownCaptureIntent", "townName", "seven ox"),
        ("SelectOrganizationIntent", "organizationQuery", "tnf"),
        ("SelectCreatorCityIntent", "cityQuery", "Manchester"),
        (
            "SelectPublicationSourceIntent",
            "publicationSourceQuery",
            "Local Voice",
        ),
        ("CarrierlessDiscoveryIntent", "topic", "Premier League"),
        (
            "CarrierlessDiscoveryIntent",
            "discoveryQuery",
            "Orion Meta Glasses",
        ),
        ("OpenDiscoveryIntent", "searchQuery", "dkken"),
    ],
)
async def test_typed_slot_reply_cannot_replace_pending_search_confirmation(
    monkeypatch,
    mock_handler_input,
    intent_name,
    slot_name,
    raw,
):
    from src.middleware.dialog_validation import (
        DialogValidationGateHandler,
        DialogValidationInterceptor,
    )

    _intent_request(
        mock_handler_input,
        intent_name,
        {slot_name: {"name": slot_name, "value": raw}},
    )
    pending = {
        "confirmationLabel": "content in Liverpool",
        "searchPayload": {"query": "", "filter": {"city": "Liverpool"}},
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingSearchConfirmation": True,
        "pendingResolution": pending,
        "activeDialog": {
            "type": "search_confirmation",
            "context": pending,
            "expiresAt": 4102444800,
        },
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()

    DialogValidationInterceptor().process(mock_handler_input)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    response = DialogValidationGateHandler().handle(mock_handler_input)

    resolve.assert_not_awaited()
    question = "Did you want me to play content in Liverpool? Please say yes or no."
    assert question in response["outputSpeech"]["ssml"]
    assert question in response["reprompt"]["outputSpeech"]["ssml"]
    store = User.snapshot(mock_handler_input)
    assert store["awaitingSearchConfirmation"] is True
    assert store["pendingResolution"] == pending
    assert store["activeDialog"]["context"] == pending


@pytest.mark.asyncio
async def test_external_resolver_call_sends_interpretation_progressive(mock_handler_input):
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "search",
                "slots": {"residualQuery": "gardening"},
            }
        )
    )
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "gardening"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }

    await ResolverInterceptor(
        deps=ApplicationContainer(resolver=resolver, progressive=progressive)
    ).process(mock_handler_input)

    progressive.send.assert_awaited_once_with(
        mock_handler_input,
        "One moment while I work that out for you.",
    )
    resolver.resolve_utterance.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slots", "expected_utterance"),
    [
        (
            "PlayByOrganizationIntent",
            {
                "topic": {"name": "topic", "value": "sport"},
                "organizationQuery": {
                    "name": "organizationQuery",
                    "value": "tynedale talking news",
                    "resolutions": {
                        "resolutionsPerAuthority": [
                            {
                                "status": {"code": "ER_SUCCESS_MATCH"},
                                "values": [{"value": {"name": "Tynedale Talking Newspaper"}}],
                            }
                        ]
                    },
                },
            },
            "play sport from Tynedale Talking Newspaper",
        ),
        (
            "PlayByOrganizationIntent",
            {
                "organizationQuery": {
                    "name": "organizationQuery",
                    "value": "North Moor Talking Newspaper",
                }
            },
            "play from North Moor Talking Newspaper",
        ),
        (
            "SelectOrganizationIntent",
            {
                "organizationQuery": {
                    "name": "organizationQuery",
                    "value": "tyndale",
                    "resolutions": {
                        "resolutionsPerAuthority": [
                            {
                                "status": {"code": "ER_SUCCESS_MATCH"},
                                "values": [{"value": {"name": "Tynedale Talking Newspaper"}}],
                            }
                        ]
                    },
                }
            },
            "play tyndale",
        ),
        (
            "PlayLocalIntent",
            {
                "topic": {"name": "topic", "value": "sport"},
                "cityQuery": {
                    "name": "cityQuery",
                    "value": "Herne Bay",
                },
            },
            "play sport near Herne Bay",
        ),
        (
            "PlayLocalIntent",
            {
                "cityQuery": {
                    "name": "cityQuery",
                    "value": "London",
                },
            },
            "play near London",
        ),
    ],
)
async def test_generated_slot_match_or_raw_value_always_reaches_backend_resolver(
    mock_handler_input, intent_name, slots, expected_utterance
):
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={"status": "resolved", "intent": "search", "slots": {}}
        )
    )
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": intent_name, "slots": slots},
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }

    await ResolverInterceptor(
        deps=ApplicationContainer(resolver=resolver, progressive=progressive)
    ).process(mock_handler_input)

    resolver.resolve_utterance.assert_awaited_once()
    assert resolver.resolve_utterance.await_args.args == (expected_utterance,)


@pytest.mark.asyncio
async def test_organization_follow_up_beats_incorrect_town_intent(mock_handler_input):
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "organization",
                "slots": {
                    "organizationIds": ["org-tynedale"],
                    "organizationName": "Tynedale Talking Newspaper",
                },
            }
        )
    )
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "TownCaptureIntent",
                "slots": {"townName": {"name": "townName", "value": "tyndale"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingOrganizationName": True,
    }

    await ResolverInterceptor(
        deps=ApplicationContainer(resolver=resolver, progressive=progressive)
    ).process(mock_handler_input)

    resolver.resolve_utterance.assert_awaited_once()
    assert resolver.resolve_utterance.await_args.args == ("play from tyndale",)
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "organization"
    assert nlp["alexaRawIntent"] == "TownCaptureIntent"
    assert nlp["needsRedirect"] is True
    assert nlp["slots"]["organizationFollowUp"] is True
    assert "townName" not in nlp["slots"]


def test_name_only_organization_selection_uses_domain_handler(mock_handler_input):
    from src.controllers.play import PlayByOrganizationHandler

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SelectOrganizationIntent",
                "slots": {
                    "organizationQuery": {
                        "name": "organizationQuery",
                        "value": "tyndale",
                    }
                },
            },
        }
    )
    assert PlayByOrganizationHandler(deps=ApplicationContainer()).can_handle(mock_handler_input)

@pytest.mark.asyncio
async def test_local_resolver_result_does_not_send_interpretation_progressive(
    mock_handler_input,
):
    resolver = SimpleNamespace(resolve_utterance=AsyncMock())
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "WhatsTrendingIntent", "slots": {}},
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }

    await ResolverInterceptor(
        deps=ApplicationContainer(resolver=resolver, progressive=progressive)
    ).process(mock_handler_input)

    progressive.send.assert_not_awaited()
    resolver.resolve_utterance.assert_not_awaited()


@pytest.mark.asyncio
async def test_playback_location_is_search_filter_not_saved_location(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {
                    "query": {
                        "name": "query",
                        "value": "play something from Manchester",
                    }
                },
            },
        }
    )
    original_store = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "userCity": "Swindon",
        "locality": "Swindon",
        "latitude": 51.5558,
        "longitude": -1.7797,
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = original_store
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "location_set",
                "searchPayload": {
                    "query": "",
                    "filter": {
                        "city": "Manchester",
                        "latitude": 53.4808,
                        "longitude": -2.2426,
                    },
                },
                "slots": {
                    "city": "Manchester",
                    "locality": "Manchester",
                    "latitude": 53.4808,
                    "longitude": -2.2426,
                    "isLocal": True,
                },
            }
        ),
    )
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "general"
    assert nlp["searchPayload"]["filter"]["city"] == "Manchester"
    store = User.snapshot(mock_handler_input)
    assert store["userCity"] == "Swindon"
    assert store["locality"] == "Swindon"
    assert store["latitude"] == 51.5558
    assert store["longitude"] == -1.7797


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slot_name"),
    [
        ("TownCaptureIntent", "townName"),
        ("SetLocationIntent", "location"),
    ],
)
async def test_idle_bare_city_misclassification_routes_to_discovery_without_saving(
    mock_handler_input, intent_name, slot_name
):
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "location_set",
                "searchPayload": {
                    "query": "",
                    "filter": {"city": "Swindon"},
                },
                "slots": {"city": "Swindon", "isLocal": True},
            }
        )
    )
    container = ApplicationContainer(
        resolver=resolver,
        progressive=SimpleNamespace(send=AsyncMock(return_value=True)),
    )
    handler_input = _intent_request(
        mock_handler_input,
        intent_name,
        {slot_name: {"name": slot_name, "value": "Swindon"}},
    )
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "userCity": "York",
        "locality": "York",
    }

    await ResolverInterceptor(deps=container).process(handler_input)

    resolver.resolve_utterance.assert_awaited_once_with(
        "play Swindon",
        alexa_user_id="amzn1.ask.account.TEST",
        timeout_ms=5000,
    )
    nlp = handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "general"
    assert nlp["alexaRawIntent"] == intent_name
    assert nlp["needsRedirect"] is True
    assert nlp["searchPayload"]["filter"] == {"city": "Swindon"}
    store = User.snapshot(handler_input)
    assert store["userCity"] == "York"
    assert store["locality"] == "York"
    assert store["onboardingStage"] is None


@pytest.mark.asyncio
async def test_idle_unresolved_location_slot_still_reaches_resolver(mock_handler_input):
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "location_set",
                "searchPayload": {"query": "", "filter": {"city": "Swindon"}},
                "slots": {"city": "Swindon", "isLocal": True},
            }
        )
    )
    container = ApplicationContainer(
        resolver=resolver,
        progressive=SimpleNamespace(send=AsyncMock(return_value=True)),
    )
    handler_input = _intent_request(
        mock_handler_input,
        "TownCaptureIntent",
        {
            "townName": {
                "name": "townName",
                "value": "swidon",
                "resolutions": {
                    "resolutionsPerAuthority": [{"status": {"code": "ER_SUCCESS_NO_MATCH"}}]
                },
            }
        },
    )
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }

    await ResolverInterceptor(deps=container).process(handler_input)

    resolver.resolve_utterance.assert_awaited_once_with(
        "play swidon",
        alexa_user_id="amzn1.ask.account.TEST",
        timeout_ms=5000,
    )
    nlp = handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "general"
    assert nlp["searchPayload"]["filter"] == {"city": "Swindon"}


@pytest.mark.asyncio
async def test_idle_typed_source_match_sends_spoken_words_to_general_resolver(
    mock_handler_input,
):
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "general",
                "searchPayload": {"query": "", "filter": {"city": "Liverpool"}},
                "slots": {"city": "Liverpool", "isLocal": True},
            }
        )
    )
    container = ApplicationContainer(
        resolver=resolver,
        progressive=SimpleNamespace(send=AsyncMock(return_value=True)),
    )
    handler_input = _intent_request(
        mock_handler_input,
        "SelectOrganizationIntent",
        {
            "organizationQuery": {
                "name": "organizationQuery",
                "value": "Liverpool",
                "resolutions": {
                    "resolutionsPerAuthority": [
                        {
                            "status": {"code": "ER_SUCCESS_MATCH"},
                            "values": [{"value": {"name": "Liverpool Talking Newspaper"}}],
                        }
                    ]
                },
            }
        },
    )
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }

    await ResolverInterceptor(deps=container).process(handler_input)

    resolver.resolve_utterance.assert_awaited_once_with(
        "play Liverpool",
        alexa_user_id="amzn1.ask.account.TEST",
        timeout_ms=5000,
    )
    nlp = handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "general"
    assert nlp["alexaRawIntent"] == "SelectOrganizationIntent"
    assert nlp["needsRedirect"] is True
    assert nlp["searchPayload"]["filter"] == {"city": "Liverpool"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "matches", "expected"),
    [
        ("ER_SUCCESS_MATCH", ["Talking News Federation"], "Talking News Federation"),
        ("ER_SUCCESS_NO_MATCH", [], "New Local Voice"),
        ("ER_ERROR_TIMEOUT", [], "New Local Voice"),
    ],
)
async def test_carrierless_discovery_uses_canonical_or_captured_resolver_input(
    mock_handler_input,
    status,
    matches,
    expected,
):
    spoken = "tnf" if matches else "New Local Voice"
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={"status": "resolved", "intent": "general", "slots": {}}
        )
    )
    container = ApplicationContainer(
        resolver=resolver,
        progressive=SimpleNamespace(send=AsyncMock(return_value=True)),
    )
    handler_input = _intent_request(
        mock_handler_input,
        "CarrierlessDiscoveryIntent",
        {
            "discoveryQuery": {
                "name": "discoveryQuery",
                "value": spoken,
                "resolutions": {
                    "resolutionsPerAuthority": [
                        {
                            "status": {"code": status},
                            "values": [{"value": {"name": match}} for match in matches],
                        }
                    ]
                },
            }
        },
    )
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }

    await ResolverInterceptor(deps=container).process(handler_input)

    resolver.resolve_utterance.assert_awaited_once_with(
        expected,
        alexa_user_id="amzn1.ask.account.TEST",
        timeout_ms=5000,
    )


@pytest.mark.asyncio
async def test_active_location_change_owns_city_misclassified_as_local_search(
    mock_handler_input,
):
    resolver = SimpleNamespace(resolve_utterance=AsyncMock())
    container = ApplicationContainer(resolver=resolver)
    handler_input = _intent_request(
        mock_handler_input,
        "PlayLocalIntent",
        {"cityQuery": {"name": "cityQuery", "value": "Swindon"}},
    )
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "onboardingStage": "ask_town",
    }

    await ResolverInterceptor(deps=container).process(handler_input)

    resolver.resolve_utterance.assert_not_awaited()
    nlp = handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "town_capture"
    assert nlp["slots"] == {"townName": "Swindon", "placeName": "Swindon"}
    assert TownCaptureHandler(deps=container).can_handle(handler_input) is True


@pytest.mark.asyncio
async def test_explicit_location_change_command_opens_location_capture(mock_handler_input):
    resolver = SimpleNamespace(resolve_utterance=AsyncMock())
    handler_input = _intent_request(mock_handler_input, "SetLocationIntent")
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }

    await ResolverInterceptor(deps=ApplicationContainer(resolver=resolver)).process(handler_input)

    resolver.resolve_utterance.assert_not_awaited()
    nlp = handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "location_set"
    assert nlp["slots"] == {}


@pytest.mark.asyncio
async def test_explicit_one_turn_location_change_keeps_mutation_route(mock_handler_input):
    resolver = SimpleNamespace(resolve_utterance=AsyncMock())
    handler_input = _intent_request(
        mock_handler_input,
        "SearchLocationIntent",
        {"searchQuery": {"name": "searchQuery", "value": "Swindon"}},
    )
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }

    await ResolverInterceptor(deps=ApplicationContainer(resolver=resolver)).process(handler_input)

    resolver.resolve_utterance.assert_not_awaited()
    nlp = handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "location_set"
    assert nlp["slots"] == {"townName": "Swindon"}


@pytest.mark.asyncio
async def test_misspelled_bare_town_is_owned_by_onboarding(monkeypatch, mock_handler_input):
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(
            return_value={
                "status": "resolved",
                "resolution": {"match": {"city": "Swindon"}, "candidates": []},
            }
        ),
    )
    handler_input = _town_request(mock_handler_input, "swidon")
    await ResolverInterceptor(deps=ApplicationContainer()).process(handler_input)
    assert TownCaptureHandler(deps=ApplicationContainer()).can_handle(handler_input)
    await TownCaptureHandler(deps=ApplicationContainer()).handle(handler_input)
    store = User.snapshot(handler_input)
    assert store["pendingLocationConfirm"]["city"] == "Swindon"
    assert store["awaitingLocationConfirm"] is True
    assert store["onboardingStage"] == "await_location_confirm"
    assert store["_requiresReliableSave"] is True
    session = handler_input.attributes_manager.set_session_attributes.call_args.args[0]
    assert session["onboardingStage"] == "await_location_confirm"
    assert session["awaitingLocationConfirm"] is True
    handler_input.response_builder.speak.return_value.reprompt.return_value.set_should_end_session.assert_called_once_with(
        False
    )


@pytest.mark.asyncio
async def test_city_entity_resolution_sends_canonical_town_to_resolver(
    monkeypatch, mock_handler_input
):
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "resolution": {"match": {"city": "Herne Bay"}, "candidates": []},
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    handler_input = _town_request(mock_handler_input, "arn bay")
    slot = handler_input.request_envelope.request.intent.slots["townName"]
    slot["resolutions"] = {
        "resolutionsPerAuthority": [
            {
                "status": {"code": "ER_SUCCESS_MATCH"},
                "values": [{"value": {"name": "Herne Bay"}}],
            }
        ]
    }
    await ResolverInterceptor(deps=ApplicationContainer()).process(handler_input)
    await TownCaptureHandler(deps=ApplicationContainer()).handle(handler_input)
    assert handler_input.attributes_manager.request_attributes["_nlp"]["slots"] == {
        "townName": "Herne Bay",
        "placeName": "Herne Bay",
    }
    resolve.assert_awaited_once()
    assert resolve.await_args.args == ("Herne Bay",)
    assert resolve.await_args.kwargs == {
        "alexa_user_id": "amzn1.ask.account.TEST",
        "prefer_location": True,
        "timeout_ms": 5000,
    }


@pytest.mark.asyncio
async def test_unknown_city_search_query_reaches_the_location_resolver(mock_handler_input):
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "status": "resolved",
                "resolution": {
                    "match": {
                        "city": "Dorking",
                        "locality": "Dorking",
                        "countryCode": "GB",
                        "latitude": 51.2323,
                        "longitude": -0.3338,
                    },
                    "candidates": [],
                },
            }
        )
    )
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))
    container = ApplicationContainer(resolver=resolver, progressive=progressive)
    handler_input = _intent_request(
        mock_handler_input,
        "SearchLocationIntent",
        {"searchQuery": {"name": "searchQuery", "value": "dorking"}},
    )
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingStage": "ask_town",
    }

    await ResolverInterceptor(deps=container).process(handler_input)

    nlp = handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "town_capture"
    assert nlp["slots"] == {"townName": "dorking", "placeName": "dorking"}
    assert TownCaptureHandler(deps=container).can_handle(handler_input) is True

    await TownCaptureHandler(deps=container).handle(handler_input)

    resolver.resolve_utterance.assert_awaited_once_with(
        "dorking",
        alexa_user_id="amzn1.ask.account.TEST",
        prefer_location=True,
        timeout_ms=5000,
    )
    store = User.snapshot(handler_input)
    assert store["onboardingStage"] == "await_location_confirm"
    assert store["pendingLocationConfirm"]["city"] == "Dorking"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage",
    ["ask_permission", "ask_town", "await_location_confirm"],
)
async def test_next_intent_skips_every_location_onboarding_stage(mock_handler_input, stage):
    from src.middleware.onboarding_gate import OnboardingGateHandler

    resolver = SimpleNamespace(resolve_utterance=AsyncMock())
    container = ApplicationContainer(resolver=resolver)
    handler_input = _intent_request(mock_handler_input, "AMAZON.NextIntent")
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingStage": stage,
        "awaitingLocationConfirm": stage == "await_location_confirm",
        "pendingLocationConfirm": (
            {"city": "Dorking"} if stage == "await_location_confirm" else None
        ),
    }
    gate = OnboardingGateHandler(deps=container)

    assert gate.can_handle(handler_input) is True
    await gate.handle(handler_input)

    resolver.resolve_utterance.assert_not_awaited()
    store = User.snapshot(handler_input)
    assert store["onboardingComplete"] is True
    assert store["onboardingStage"] is None
    assert store["awaitingLocationConfirm"] is False
    assert store["pendingLocationConfirm"] is None
    assert store["awaitingProfilePermission"] is True


@pytest.mark.asyncio
async def test_next_intent_skips_optional_profile_setup(mock_handler_input):
    from src.middleware.onboarding_gate import OnboardingGateHandler

    listener_sync = SimpleNamespace(sync_for_launch=AsyncMock(return_value=None))
    container = ApplicationContainer(listener_sync=listener_sync)
    handler_input = _intent_request(mock_handler_input, "AMAZON.NextIntent")
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingProfilePermission": True,
    }
    gate = OnboardingGateHandler(deps=container)

    assert gate.can_handle(handler_input) is True
    await gate.handle(handler_input)

    store = User.snapshot(handler_input)
    assert store["awaitingProfilePermission"] is False
    assert store["listenerType"] == "guest"
    listener_sync.sync_for_launch.assert_awaited_once_with(handler_input)


@pytest.mark.asyncio
async def test_onboarding_treats_creator_misclassification_as_town(monkeypatch, mock_handler_input):
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "creator",
            "resolution": {
                "match": {
                    "city": "Gloucester",
                    "locality": "Gloucester",
                    "countryCode": "gb",
                    "latitude": 51.8653,
                    "longitude": -2.2458,
                },
                "candidates": [],
            },
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SearchCreatorIntent",
                "slots": {"searchQuery": {"name": "searchQuery", "value": "Gloucester"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingStage": "ask_town",
    }
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "town_capture"
    assert nlp["slots"]["townName"] == "Gloucester"
    assert TownCaptureHandler(deps=ApplicationContainer()).can_handle(mock_handler_input)
    await TownCaptureHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    store = User.snapshot(mock_handler_input)
    assert store["onboardingStage"] == "await_location_confirm"
    assert store["pendingLocationConfirm"]["city"] == "Gloucester"
    assert store["onboardingTownAttempts"] == 0
    resolve.assert_awaited_once_with(
        "Gloucester",
        alexa_user_id="amzn1.ask.account.TEST",
        prefer_location=True,
        timeout_ms=5000,
    )


def test_manual_town_reprompt_exposes_skip_command():

    assert "say skip" in Speech.REPROMPT_ASK_TOWN.casefold()


@pytest.mark.asyncio
async def test_onboarding_gate_preserves_city_phrase_misclassified_as_search(
    mock_handler_input,
):
    from src.middleware.onboarding_gate import OnboardingGateHandler

    handler_input = _town_request(mock_handler_input, "ammm ba")
    handler_input.request_envelope.request.intent.name = "PlayContentIntent"
    handler_input.request_envelope.request.intent.slots = {
        "topic": {"name": "topic", "value": "ammm ba"}
    }
    handler_input.attributes_manager.get_session_attributes = lambda: {}
    handler_input.attributes_manager.request_attributes["_nlp"] = {
        "status": "resolved",
        "intent": "search",
        "entities": [],
        "slots": {
            "residualQuery": "ammm ba",
            "latest": False,
            "isRecommended": False,
            "isPublication": False,
            "sort": "relevance",
        },
    }
    gate = OnboardingGateHandler(deps=ApplicationContainer())
    assert gate.can_handle(handler_input) is True
    await gate.handle(handler_input)
    speech = handler_input.response_builder.speak.call_args.args[0]
    assert "couldn't find ammm ba as a city" in speech.casefold()
    handler_input.response_builder.speak.return_value.reprompt.return_value.set_should_end_session.assert_called_once_with(
        False
    )


@pytest.mark.asyncio
async def test_town_intent_remains_owned_when_resolver_calls_it_search(
    monkeypatch, mock_handler_input
):
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "search",
            "entities": [],
            "resolution": {"match": None, "candidates": []},
            "slots": {"residualQuery": "ammm ba"},
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    handler_input = _town_request(mock_handler_input, "ammm ba")
    handler_input.attributes_manager.request_attributes["_nlp"] = {
        "status": "resolved",
        "intent": "search",
        "entities": [],
        "slots": {"residualQuery": "ammm ba"},
    }
    handler = TownCaptureHandler(deps=ApplicationContainer())
    assert handler.can_handle(handler_input) is True
    await handler.handle(handler_input)
    speech = handler_input.response_builder.speak.call_args.args[0]
    assert "couldn't find ammm ba as a city" in speech.casefold()
    handler_input.response_builder.speak.return_value.reprompt.return_value.add_directive.return_value.set_should_end_session.assert_called_once_with(
        False
    )


@pytest.mark.asyncio
async def test_unknown_city_names_city_and_keeps_session_open(monkeypatch, mock_handler_input):
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(
            return_value={
                "status": "resolved",
                "resolution": {"match": None, "candidates": []},
            }
        ),
    )
    handler_input = _town_request(mock_handler_input, "nottinghamshire place")
    await TownCaptureHandler(deps=ApplicationContainer()).handle(handler_input)
    speech = handler_input.response_builder.speak.call_args.args[0]
    assert "couldn't find nottinghamshire place as a city" in speech.casefold()
    retry_builder = handler_input.response_builder.speak.return_value.reprompt.return_value
    retry_builder.add_directive.assert_called_once_with(
        {"type": "Dialog.ElicitSlot", "slotToElicit": "townName"}
    )
    retry_builder.add_directive.return_value.set_should_end_session.assert_called_once_with(False)
    assert User.snapshot(handler_input)["onboardingStage"] == "ask_town"


@pytest.mark.asyncio
async def test_town_slot_fallback_resolves_without_nlp_attrs(monkeypatch, mock_handler_input):
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(
            return_value={
                "status": "resolved",
                "resolution": {"match": {"city": "Swindon"}, "candidates": []},
            }
        ),
    )
    handler_input = _town_request(mock_handler_input, "swidon")
    await TownCaptureHandler(deps=ApplicationContainer()).handle(handler_input)
    store = User.snapshot(handler_input)
    assert store["pendingLocationConfirm"]["city"] == "Swindon"
    assert store["awaitingLocationConfirm"] is True


@pytest.mark.asyncio
async def test_town_resolver_failure_retries_once_without_closing_session(
    monkeypatch, mock_handler_input
):
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(side_effect=ResolverUnavailable("taxonomy_sync_unavailable")),
    )
    handler_input = _town_request(mock_handler_input, "york")
    await TownCaptureHandler(deps=ApplicationContainer()).handle(handler_input)
    store = User.snapshot(handler_input)
    speech = handler_input.response_builder.speak.call_args.args[0]
    assert "try the city name again" in speech
    retry_builder = handler_input.response_builder.speak.return_value.reprompt.return_value
    retry_builder.add_directive.assert_called_once_with(
        {"type": "Dialog.ElicitSlot", "slotToElicit": "townName"}
    )
    retry_builder.add_directive.return_value.set_should_end_session.assert_called_once_with(False)
    assert store["onboardingStage"] == "ask_town"
    assert store["onboardingTownResolverFailures"] == 1


@pytest.mark.asyncio
async def test_repeated_town_resolver_failure_continues_without_location(
    monkeypatch, mock_handler_input
):
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(side_effect=ResolverUnavailable("taxonomy_sync_unavailable")),
    )
    handler_input = _town_request(mock_handler_input, "herne bay")
    handler_input.attributes_manager.request_attributes["_store"][
        "onboardingTownResolverFailures"
    ] = 1
    await TownCaptureHandler(deps=ApplicationContainer()).handle(handler_input)
    store = User.snapshot(handler_input)
    speech = handler_input.response_builder.speak.call_args.args[0]
    assert "continue without your location" in speech
    handler_input.response_builder.speak.return_value.reprompt.return_value.set_should_end_session.assert_called_once_with(
        False
    )
    assert store["onboardingComplete"] is True
    assert store["onboardingStage"] is None


def test_search_confirmation_runs_after_local_nlp_resolution():
    names = [interceptor.__name__ for interceptor in RouteRegistry.REQUEST_INTERCEPTORS]
    assert "ConfirmationMiddleware" in names
    assert names.index("ConfirmationMiddleware") > names.index("ResolverInterceptor")


def test_resolved_confirmation_repeats_full_search_request():
    assert (
        SearchSpeech.resolved_search_request_label(
            {
                "latest": True,
                "tags": ["community-services"],
                "residualQuery": "",
                "organizationIds": ["org-ytn"],
            },
            "York Talking News",
        )
        == "the latest community services from York Talking News"
    )


def test_confirmation_never_uses_from_without_source_filter():
    assert (
        SearchSpeech.resolved_search_request_label(
            {"category": "sport", "residualQuery": "adeshina"}, "sport from adeshina"
        )
        == "sport adeshina"
    )


def test_publication_filter_uses_natural_source_wording():
    assert (
        SearchSpeech.resolved_search_request_label(
            {
                "latest": True,
                "category": "sport",
                "publicationIds": ["publication-1"],
                "publicationName": "London Weekly Review",
                "city": "London",
            },
            "London Weekly Review",
        )
        == "the latest sport from London Weekly Review in London"
    )


def test_bare_publication_confirmation_speaks_its_name_directly():
    assert (
        SearchSpeech.resolved_search_request_label(
            {
                "publicationIds": ["publication-1"],
                "publicationName": "Weekend product podcast",
                "residualQuery": "",
                "isPublication": False,
            }
        )
        == "Weekend product podcast"
    )


def test_publication_format_is_spoken_with_creator_source():
    assert (
        SearchSpeech.resolved_search_request_label(
            {
                "isPublication": True,
                "latest": True,
                "creatorIds": ["creator-1"],
                "creatorName": "Adeshina Ayomide",
            }
        )
        == "the latest publication from Adeshina Ayomide"
    )


def test_epoch_month_filter_is_spoken_in_readable_calendar_format():
    assert (
        SearchSpeech.resolved_search_request_label(
            {
                "latest": True,
                "searchPlan": {
                    "filter": {"publishedFrom": 1780272000, "publishedTo": 1782864000},
                    "sort": "latest",
                },
            }
        )
        == "the latest content published in June 2026"
    )


@pytest.mark.asyncio
async def test_publication_intent_reconstructs_sort_and_source_for_resolver(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "requestId": "publication-request",
            "locale": "en-GB",
            "intent": {
                "name": "PlayPublicationIntent",
                "slots": {
                    "publicationSort": {"name": "publicationSort", "value": "latest"},
                    "publicationSourceQuery": {
                        "name": "publicationSourceQuery",
                        "value": "tnf",
                    },
                },
            },
        }
    )
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "organization",
            "slots": {
                "isPublication": True,
                "latest": True,
                "organizationIds": ["org-tnf"],
                "organizationName": "Talking News Federation",
                "residualQuery": "",
                "searchPlan": {
                    "query": "",
                    "filter": {"isPublication": True, "organizationIds": ["org-tnf"]},
                    "sort": "latest",
                },
            },
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    assert resolve.await_args.args == ("play latest publication from tnf",)


@pytest.mark.asyncio
async def test_publication_intent_keeps_alexa_date_out_of_resolver_text(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "requestId": "dated-publication-request",
            "locale": "en-GB",
            "intent": {
                "name": "PlayPublicationIntent",
                "slots": {
                    "dateQuery": {"name": "dateQuery", "value": "2026-08-02"},
                    "publicationSourceQuery": {
                        "name": "publicationSourceQuery",
                        "value": "wtn",
                    },
                },
            },
        }
    )
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "organization",
            "slots": {"searchPlan": {}},
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    assert resolve.await_args.args == ("play publication from wtn",)
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    date_filter = nlp["slots"]["searchPlan"]["filter"]
    assert set(date_filter) == {"publishedFrom", "publishedTo"}
    assert date_filter["publishedFrom"] < date_filter["publishedTo"]
    assert nlp["slots"]["temporalOriginal"] == "2 August 2026"


@pytest.mark.asyncio
async def test_publication_intent_rejects_out_of_catalog_sort_text(monkeypatch, mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "requestId": "invalid-publication-sort-request",
            "locale": "en-GB",
            "intent": {
                "name": "PlayPublicationIntent",
                "slots": {
                    "publicationSort": {
                        "name": "publicationSort",
                        "value": "yesterday",
                        "resolutions": {
                            "resolutionsPerAuthority": [{"status": {"code": "ER_SUCCESS_NO_MATCH"}}]
                        },
                    },
                    "publicationSourceQuery": {
                        "name": "publicationSourceQuery",
                        "value": "wtn",
                    },
                },
            },
        }
    )
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "organization",
            "slots": {"searchPlan": {}},
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    assert resolve.await_args.args == ("play publication from wtn",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("date_value", "temporal_label"),
    [
        ("2026-09-04", "4 September 2026"),
        ("2026-W35", "from 24 August to 30 August 2026"),
    ],
)
async def test_content_date_is_a_filter_not_resolver_query_text(
    monkeypatch, mock_handler_input, date_value, temporal_label
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "requestId": "dated-content-request",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {
                    "topic": {"name": "topic", "value": "sport"},
                    "dateQuery": {"name": "dateQuery", "value": date_value},
                },
            },
        }
    )
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "category",
            "slots": {
                "category": "sport",
                "categorySlugs": ["sport"],
                "residualQuery": "",
                "searchPlan": {"filter": {"categorySlugs": ["sport"]}},
            },
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    assert resolve.await_args.args == ("play sport",)
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    filters = nlp["slots"]["searchPlan"]["filter"]
    assert filters["categorySlugs"] == ["sport"]
    assert filters["publishedFrom"] < filters["publishedTo"]
    assert nlp["slots"]["temporalOriginal"] == temporal_label


@pytest.mark.asyncio
async def test_publication_discovery_sends_format_and_creator_filters(
    monkeypatch, mock_handler_input
):
    from src.models.search import Search

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "PlayPublicationIntent", "slots": {}},
        }
    )
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "intent": "creator",
                "slots": {
                    "isPublication": True,
                    "creatorIds": ["creator-1"],
                    "residualQuery": "",
                    "searchPlan": {
                        "filter": {"isPublication": True, "creatorIds": ["creator-1"]},
                        "sort": "trending",
                    },
                },
            },
        }
    )
    search = AsyncMock(return_value={"failed": False, "results": [], "total_hits": 0})
    monkeypatch.setattr(HearApiClient, "search", search)
    await Search.discover_content_via_search(mock_handler_input, deps=ApplicationContainer())
    payload = search.await_args.args[0]
    assert payload["query"] == ""
    assert payload["filter"] == {"creatorIds": ["creator-1"], "isPublication": True}
    assert payload["sort"] == "trending"


@pytest.mark.asyncio
async def test_multiple_publications_from_source_start_ambiguity_selection(
    monkeypatch, mock_handler_input
):
    from src.models.search import Search

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayByOrganizationIntent",
                "slots": {"organizationQuery": {"name": "organizationQuery", "value": "TNF"}},
            },
        }
    )
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "intent": "organization",
                "requestId": "tnf-publications",
                "originalUtterance": "play TNF",
                "slots": {
                    "organizationIds": ["org-tnf"],
                    "organizationName": "Talking News Federation",
                    "residualQuery": "",
                },
            },
        }
    )
    search = AsyncMock(
        return_value={
            "failed": False,
            "results": [
                {
                    "contentId": "track-1",
                    "audioUrl": "https://cdn.hear.media/track-1.mp3",
                },
                {
                    "contentId": "track-2",
                    "audioUrl": "https://cdn.hear.media/track-2.mp3",
                },
            ],
            "_publication_choices": [
                {
                    "type": "publication",
                    "id": "publication-buxton",
                    "name": "Buxton Talking Song",
                },
                {
                    "type": "publication",
                    "id": "publication-sermons",
                    "name": "Daily Sermons",
                },
            ],
            "total_hits": 5,
            "total_pages": 2,
            "page": 0,
        }
    )
    monkeypatch.setattr(HearApiClient, "search", search)

    result = await Search.discover_content_via_search(
        mock_handler_input, {"q": "", "intent": "organization"}, deps=ApplicationContainer()
    )

    payload = search.await_args.args[0]
    assert payload["limit"] == 3
    assert result["results"] == []
    assert "Buxton Talking Song" in result["client_message"]
    assert "Daily Sermons" in result["client_message"]
    assert "To hear more choices, say show more or next." in result["client_message"]
    pending = User.snapshot(mock_handler_input)["pendingAmbiguity"]
    assert [candidate["id"] for candidate in pending["candidates"]] == [
        "publication-buxton",
        "publication-sermons",
    ]
    assert pending["searchPayload"]["limit"] == 3
    assert pending["candidatePagination"] == {
        "kind": "publication",
        "currentPage": 0,
        "totalPages": 2,
        "totalHits": 5,
        "limit": 3,
    }
    response = Search._build_search_outcome_response(mock_handler_input, result)
    directives = response["directives"]
    assert directives[0]["type"] == "Dialog.UpdateDynamicEntities"


@pytest.mark.asyncio
async def test_discovery_preserves_all_resolved_category_filters(monkeypatch, mock_handler_input):
    from src.models.search import Search

    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "intent": "category",
                "slots": {
                    "category": "history",
                    "categorySlugs": ["history", "politics"],
                    "residualQuery": "",
                    "searchPlan": {
                        "query": "",
                        "filter": {"categorySlugs": ["history", "politics"]},
                    },
                },
            },
        }
    )
    search = AsyncMock(return_value={"failed": False, "results": [], "total_hits": 0})
    monkeypatch.setattr(HearApiClient, "search", search)
    await Search.discover_content_via_search(mock_handler_input, deps=ApplicationContainer())
    assert search.await_args.args[0]["filter"]["categorySlugs"] == [
        "history",
        "politics",
    ]


@pytest.mark.asyncio
async def test_unresolved_source_is_not_sent_as_a_search_query(monkeypatch, mock_handler_input):
    from src.models.search import Search

    handler_input = _town_request(mock_handler_input, "swidon")
    handler_input.attributes_manager.request_attributes["_nlp"] = {
        "intent": "category",
        "slots": {
            "category": "sports",
            "latest": True,
            "residualQuery": "david",
            "unresolvedReferences": [
                {
                    "relation": "from",
                    "phrase": "david",
                    "expectedTypes": ["creator", "organization", "publication"],
                }
            ],
        },
    }
    search = AsyncMock(return_value={"failed": False, "results": [], "total_hits": 0})
    monkeypatch.setattr(HearApiClient, "search", search)
    result = await Search.discover_content_via_search(
        handler_input, {"q": "", "intent": "category"}, deps=ApplicationContainer()
    )
    search.assert_not_awaited()
    assert "creator, organisation or publication named david" in result["client_message"]


@pytest.mark.asyncio
async def test_organization_slot_is_resolved_and_confirmed_before_search(
    monkeypatch, mock_handler_input
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayByOrganizationIntent",
                "slots": {"organizationQuery": {"name": "organizationQuery", "value": "tnf"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolution = {
        "version": 1,
        "requestId": "tnf-resolution",
        "status": "resolved",
        "intent": "organization",
        "confidence": "high",
        "confirmationLabel": "content from Talking News Federation",
        "searchPayload": {
            "query": "",
            "filter": {"organizationIds": ["org-tnf"]},
            "page": 0,
            "limit": 20,
        },
        "entities": [{"type": "organization", "canonicalValue": "Talking News Federation"}],
        "slots": {
            "organizationIds": ["org-tnf"],
            "organizationName": "Talking News Federation",
            "residualQuery": "",
        },
    }
    monkeypatch.setattr(ResolverClient, "resolve_utterance", AsyncMock(return_value=resolution))
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    IntentDispatchGateHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    store = User.snapshot(mock_handler_input)
    assert store["awaitingSearchConfirmation"] is True
    assert store["pendingResolution"]["searchPayload"]["filter"]["organizationIds"] == ["org-tnf"]


@pytest.mark.asyncio
async def test_resolved_organization_requires_confirmation_before_search(
    monkeypatch, mock_handler_input
):
    from src.controllers.play import PlayByOrganizationHandler

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SearchCreatorIntent",
                "slots": {
                    "searchQuery": {
                        "name": "searchQuery",
                        "value": "heatwave from ytn",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "intent": "organization",
                "slots": {
                    "organizationIds": ["org-ytn"],
                    "organizationName": "York Talking News",
                    "residualQuery": "heatwave",
                    "latest": False,
                },
            },
        }
    )
    discover = AsyncMock(return_value={"failed": False, "results": [], "total_hits": 0})
    monkeypatch.setattr("src.models.search.Search.discover_content_via_search", discover)
    await PlayByOrganizationHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    store = User.snapshot(mock_handler_input)
    assert store["awaitingSearchConfirmation"] is True
    assert store["pendingResolution"]["intent"] == "organization"
    assert store["pendingResolution"]["confirmationLabel"] == "heatwave from York Talking News"
    discover.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_organization_prompts_and_preserves_all_candidates(
    mock_handler_input,
):
    from src.controllers.play import PlayByOrganizationHandler

    candidates = [
        {"type": "organization", "id": f"org-{index}", "name": name}
        for index, name in enumerate(
            (
                "Wakefield Talking Newspaper",
                "Walsall Talking Newspaper",
                "Warrington Talking Newspaper",
                "Wirral Talking Newspaper",
            )
        )
    ]
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayByOrganizationIntent",
                "slots": {"organizationQuery": {"name": "organizationQuery", "value": "wtn"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "requestId": "ambiguous-wtn",
                "intent": "organization",
                "originalUtterance": "play wtn",
                "searchPayload": {"query": "", "page": 0, "limit": 20},
                "slots": {
                    "residualQuery": "",
                    "ambiguousReferences": [{"phrase": "wtn", "candidates": candidates}],
                },
            },
        }
    )
    await PlayByOrganizationHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    store = User.snapshot(mock_handler_input)
    assert store["activeDialog"]["type"] == "ambiguity"
    assert store["pendingAmbiguity"]["candidates"] == candidates
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "more than one match" in spoken
    assert "couldn't match" not in spoken
    assert "To hear more choices, say show more or next." in spoken
    directive = mock_handler_input.response_builder.add_directive.call_args.args[0]
    assert directive["type"] == "Dialog.UpdateDynamicEntities"
    assert directive["types"][0]["name"] == "HEAR_CLARIFICATION"


@pytest.mark.asyncio
async def test_ambiguity_response_without_original_slot_reprompts_candidates(
    monkeypatch, mock_handler_input
):
    """A bare ambiguity follow-up must not become the generic TN prompt."""
    from src.controllers.play import PlayByOrganizationHandler

    candidates = [
        {
            "type": "organization",
            "id": "org-wakefield",
            "name": "Wakefield Talking Newspaper",
        },
        {
            "type": "organization",
            "id": "org-walsall",
            "name": "Walsall Talking Newspaper",
        },
        {
            "type": "organization",
            "id": "org-warrington",
            "name": "Warrington Talking Newspaper",
        },
    ]
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "PlayByOrganizationIntent", "slots": {}},
        }
    )
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "status": "ambiguous",
                "intent": "organization",
                "slots": {"ambiguousReferences": [{"phrase": "wtn", "candidates": candidates}]},
            },
        }
    )
    discover = AsyncMock(
        return_value={
            "results": [],
            "total_hits": 0,
            "failed": False,
            "client_message": "I found more than one match for that name. Did you mean Wakefield Talking Newspaper, Walsall Talking Newspaper, or Warrington Talking Newspaper?",
        }
    )
    monkeypatch.setattr("src.models.search.Search.discover_content_via_search", discover)
    await PlayByOrganizationHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "more than one match" in spoken
    assert "Which talking newspaper" not in spoken
    discover.assert_awaited_once()


@pytest.mark.asyncio
async def test_unresolved_creator_does_not_play_unrelated_fallback(monkeypatch, mock_handler_input):
    from src.models.play import PlayCreator

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SearchCreatorIntent",
                "slots": {
                    "searchQuery": {
                        "name": "searchQuery",
                        "value": "Unknown Speaker Collective",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "status": "resolved",
                "intent": "creator",
                "slots": {
                    "creatorQuery": "Unknown Speaker Collective",
                    "unresolvedReferences": [
                        {
                            "phrase": "Unknown Speaker Collective",
                            "expectedTypes": ["creator"],
                        }
                    ],
                },
            },
        }
    )
    discover = AsyncMock()
    fallback = AsyncMock()
    monkeypatch.setattr("src.models.search.Search.discover_content_via_search", discover)
    monkeypatch.setattr("src.models.search.Search._discover_content_avoiding_recent", fallback)

    await PlayCreator(deps=ApplicationContainer()).execute(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "Which city would you like me to find creators in" in spoken
    assert User.snapshot(mock_handler_input)["activeDialog"]["type"] == "creator_location"
    discover.assert_not_awaited()
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_recognized_creator_keeps_existing_playback_flow(
    monkeypatch,
    mock_handler_input,
):
    from src.models.play import PlayCreator

    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "status": "resolved",
                "intent": "creator",
                "slots": {
                    "creatorIds": ["creator-1"],
                    "creatorName": "Alex Reader",
                    "residualQuery": "latest news",
                },
            },
        }
    )
    search_result = {
        "failed": False,
        "results": [{"contentId": "track-1", "title": "Latest News"}],
        "total_hits": 1,
    }
    discover = AsyncMock(return_value=search_result)
    play = AsyncMock(return_value={"shouldEndSession": True})
    ask_creator_city = AsyncMock()
    monkeypatch.setattr("src.models.search.Search.discover_content_via_search", discover)
    monkeypatch.setattr("src.models.search.Search.auto_play_first_from_search", play)
    deps = SimpleNamespace(
        availability=SimpleNamespace(ask_creator_city=ask_creator_city),
    )

    response = await PlayCreator(deps=deps).execute(mock_handler_input)

    discover.assert_awaited_once_with(
        mock_handler_input,
        {"q": "latest news", "intent": "creator"},
        deps=deps,
    )
    play.assert_awaited_once()
    ask_creator_city.assert_not_awaited()
    assert response == {"shouldEndSession": True}


@pytest.mark.asyncio
async def test_creator_ambiguity_without_a_concrete_id_asks_for_city(mock_handler_input):
    from src.models.play import PlayCreator

    candidates = [
        {
            "type": "creator",
            "id": "creator-dalesman",
            "name": "Pendle Voice Dalesman",
        },
        {
            "type": "creator",
            "id": "creator-lancashire",
            "name": "Pendle Voice Lancashire Life",
        },
        {
            "type": "creator",
            "id": "creator-leader",
            "name": "Pendle Voice Leader and Times",
        },
    ]
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "SearchCreatorIntent", "slots": {}},
        }
    )
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "status": "ambiguous",
                "intent": "creator",
                "slots": {
                    "ambiguousReferences": [{"phrase": "pendle voice", "candidates": candidates}]
                },
            },
        }
    )
    mock_handler_input.response_builder = ResponseBuilder()

    response = await PlayCreator(deps=ApplicationContainer()).execute(mock_handler_input)

    store = User.snapshot(mock_handler_input)
    spoken = response["outputSpeech"]["ssml"]
    assert store["activeDialog"]["type"] == "creator_location"
    assert "Which city would you like me to find creators in" in spoken
    assert response["directives"] == [DialogStateManager.capture_directive("creator_location")]


def test_fallback_during_ambiguity_repeats_candidates_not_welcome(mock_handler_input):
    from src.controllers.fallback import FallbackHandler

    candidates = [
        {
            "type": "organization",
            "id": "org-wakefield",
            "name": "Wakefield Talking Newspaper",
        },
        {
            "type": "organization",
            "id": "org-walsall",
            "name": "Walsall Talking Newspaper",
        },
        {
            "type": "organization",
            "id": "org-warrington",
            "name": "Warrington Talking Newspaper",
        },
    ]
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "AMAZON.FallbackIntent", "slots": {}},
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "pendingAmbiguity": {
            "slots": {"ambiguousReferences": [{"phrase": "wtn", "candidates": candidates}]},
            "candidates": candidates,
        },
    }
    FallbackHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "Wakefield Talking Newspaper" in spoken
    assert "Walsall Talking Newspaper" in spoken
    assert "Warrington Talking Newspaper" in spoken
    assert "play followed by a topic" not in spoken


@pytest.mark.asyncio
async def test_fallback_without_raw_speech_is_not_reclassified_as_search(
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "AMAZON.FallbackIntent", "slots": {}},
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "pendingAmbiguity": {
            "slots": {"ambiguousReferences": [{"phrase": "wtn", "candidates": []}]},
            "candidates": [
                {
                    "type": "organization",
                    "id": "org-walsall",
                    "name": "Walsall Talking Newspaper",
                }
            ],
        },
    }
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    assert "_nlp" not in mock_handler_input.attributes_manager.request_attributes


@pytest.mark.asyncio
async def test_organization_ambiguity_reply_wins_over_stale_town_capture(
    monkeypatch, mock_handler_input
):
    """`wtn` -> `walsall` must select the organisation, not set a city."""
    candidates = [
        {
            "type": "organization",
            "id": "org-wakefield",
            "name": "Wakefield Talking Newspaper",
        },
        {
            "type": "organization",
            "id": "org-walsall",
            "name": "Walsall Talking Newspaper",
        },
        {
            "type": "organization",
            "id": "org-warrington",
            "name": "Warrington Talking Newspaper",
        },
    ]
    pending = {
        "requestId": "ambiguous-wtn",
        "intent": "organization",
        "originalUtterance": "play wtn",
        "searchPayload": {"query": "", "page": 0, "limit": 20},
        "slots": {},
        "candidates": candidates,
        "createdAt": 1,
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SetLocationIntent",
                "slots": {"location": {"name": "location", "value": "walsall"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingStage": "ask_town",
        "pendingAmbiguity": pending,
        "activeDialog": {
            "type": "ambiguity",
            "context": pending,
            "createdAt": 1,
            "expiresAt": 4102444800,
        },
    }
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(
            return_value={
                "version": 1,
                "status": "resolved",
                "intent": "organization",
                "confidence": 1.0,
                "ambiguityResolution": True,
                "confirmationLabel": "content from Walsall Talking Newspaper",
                "searchPayload": {
                    "query": "",
                    "filter": {"organizationIds": ["org-walsall"]},
                    "page": 0,
                    "limit": 20,
                },
                "entities": [
                    {
                        "type": "organization",
                        "id": "org-walsall",
                        "canonicalValue": "Walsall Talking Newspaper",
                    }
                ],
                "slots": {
                    "organizationIds": ["org-walsall"],
                    "organizationName": "Walsall Talking Newspaper",
                    "residualQuery": "",
                },
            }
        ),
    )
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "organization"
    assert nlp["searchPayload"]["filter"] == {"organizationIds": ["org-walsall"]}
    assert User.snapshot(mock_handler_input)["pendingAmbiguity"] is None
    assert User.snapshot(mock_handler_input)["activeDialog"] is None
    assert not TownCaptureHandler(deps=ApplicationContainer()).can_handle(mock_handler_input)
    from src.controllers.intent_dispatch import IntentDispatchGateHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    ConfirmationMiddleware().process(mock_handler_input)
    IntentDispatchGateHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "Did you mean Walsall Talking Newspaper?" in spoken
    store = User.snapshot(mock_handler_input)
    assert store["activeDialog"]["type"] == "search_confirmation"
    assert store["awaitingLocationConfirm"] is False
    assert store["pendingLocationConfirm"] is None


@pytest.mark.asyncio
async def test_no_declines_ambiguity_confirmation_before_stale_location(
    mock_handler_input,
):
    from src.controllers.confirmation import NoIntentHandler

    resolution = {
        "requestId": "resolved-neston",
        "intent": "organization",
        "confirmationLabel": "Ellesmere Port and Neston TN",
        "searchPayload": {"query": "", "filter": {"organizationIds": ["org-neston"]}},
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": "AMAZON.NoIntent", "slots": {}}}
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "awaitingSearchConfirmation": True,
        "pendingResolution": resolution,
        "awaitingLocationConfirm": True,
        "pendingLocationConfirm": {"city": "Neston"},
        "activeDialog": {
            "type": "search_confirmation",
            "context": resolution,
            "expiresAt": 4102444800,
        },
    }
    await NoIntentHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    store = User.snapshot(mock_handler_input)
    assert Speech.WELCOME_REPROMPT in spoken
    assert "Which town" not in spoken
    assert store["pendingResolution"] is None
    assert store["awaitingLocationConfirm"] is False
    assert store["pendingLocationConfirm"] is None


@pytest.mark.asyncio
async def test_yes_executes_ambiguity_resolution_before_stale_location(
    monkeypatch, mock_handler_input
):
    from src.controllers.confirmation import YesIntentHandler

    payload = {
        "query": None,
        "filter": {"organizationIds": ["org-neston"]},
        "sort": "relevance",
    }
    resolution = {
        "requestId": "resolved-neston",
        "intent": "organization",
        "confirmationLabel": "Ellesmere Port and Neston TN",
        "searchPayload": payload,
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": "AMAZON.YesIntent", "slots": {}}}
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "awaitingSearchConfirmation": True,
        "pendingResolution": resolution,
        "awaitingLocationConfirm": True,
        "pendingLocationConfirm": {"city": "Neston"},
        "activeDialog": {
            "type": "search_confirmation",
            "context": resolution,
            "expiresAt": 4102444800,
        },
    }
    search = AsyncMock(return_value={"results": [{"contentId": "content-1"}]})
    play = AsyncMock(return_value={"shouldEndSession": True})
    monkeypatch.setattr(HearApiClient, "search", search)
    monkeypatch.setattr("src.models.affirmative.Search.auto_play_first_from_search", play)
    response = await YesIntentHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    search.assert_awaited_once_with(
        {
            "query": "",
            "filter": {"organizationIds": ["org-neston"]},
            "limit": 3,
            "page": 0,
            "alexaUserId": "amzn1.ask.account.TEST",
        },
        timeout_ms=8000,
    )
    play.assert_awaited_once()
    assert response == {"shouldEndSession": True}
    store = User.snapshot(mock_handler_input)
    assert store.get("userCity") is None
    assert store["pendingResolution"] is None
    assert store["awaitingLocationConfirm"] is False
    assert store["pendingLocationConfirm"] is None


@pytest.mark.asyncio
async def test_yes_searches_selected_publication_with_minimal_filter(
    monkeypatch, mock_handler_input
):
    from src.controllers.confirmation import YesIntentHandler

    publication_id = "de232766-3cb2-48dd-8521-7628fbce249b"
    resolution = {
        "requestId": "resolved-buxton",
        "intent": "publication",
        "confirmationLabel": "content from Buxton Talking Song",
        "searchPayload": {
            "query": "stale query",
            "filter": {
                "organizationIds": ["706cb68b-8059-407e-a696-0651018066cd"],
                "publicationIds": [publication_id],
                "isPublication": True,
                "tags": ["stale-tag"],
            },
            "sort": "trending",
            "limit": 3,
            "page": 2,
        },
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": "AMAZON.YesIntent", "slots": {}}}
    )
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingSearchConfirmation": True,
        "pendingResolution": resolution,
        "activeDialog": {
            "type": "search_confirmation",
            "context": resolution,
            "expiresAt": 4102444800,
        },
    }
    search = AsyncMock(
        return_value={
            "failed": False,
            "results": [
                {
                    "contentId": "00733525-e097-4273-a5e0-7e376e65fecf",
                    "audioUrl": "https://cdn.hear.media/buxton-track.mp3",
                }
            ],
        }
    )
    play = AsyncMock(return_value={"shouldEndSession": True})
    progressive = AsyncMock(return_value=True)
    monkeypatch.setattr(HearApiClient, "search", search)
    monkeypatch.setattr("src.models.affirmative.Search.auto_play_first_from_search", play)

    response = await YesIntentHandler(
        deps=ApplicationContainer(
            progressive=SimpleNamespace(send=progressive),
        )
    ).handle(mock_handler_input)

    progressive.assert_awaited_once_with(
        mock_handler_input,
        "Just a moment while I find that for you.",
    )
    search.assert_awaited_once_with(
        {
            "query": "",
            "filter": {"publicationIds": [publication_id]},
            "limit": 3,
            "page": 0,
            "alexaUserId": "amzn1.ask.account.TEST",
        },
        timeout_ms=8000,
    )
    play.assert_awaited_once()
    assert response == {"shouldEndSession": True}


@pytest.mark.asyncio
async def test_confirmed_source_with_multiple_publications_asks_for_publication(
    monkeypatch, mock_handler_input
):
    from src.controllers.confirmation import YesIntentHandler

    resolution = {
        "requestId": "resolved-tnf",
        "intent": "organization",
        "confirmationLabel": "content from Talking News Federation",
        "searchPayload": {"query": "", "filter": {"organizationIds": ["org-tnf"]}},
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": "AMAZON.YesIntent", "slots": {}}}
    )
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingSearchConfirmation": True,
        "pendingResolution": resolution,
        "activeDialog": {
            "type": "search_confirmation",
            "context": resolution,
            "expiresAt": 4102444800,
        },
    }
    availability = AsyncMock(
        return_value={
            "failed": False,
            "page": 0,
            "total_pages": 1,
            "has_more": False,
            "publication_count": 2,
            "standalone_track_count": 0,
            "publications": [
                {
                    "type": "publication",
                    "id": "publication-buxton",
                    "name": "Buxton Talking Song",
                },
                {
                    "type": "publication",
                    "id": "publication-sermons",
                    "name": "Daily Sermons",
                },
            ],
        }
    )
    search = AsyncMock()
    play = AsyncMock(return_value={"shouldEndSession": True})
    monkeypatch.setattr(HearApiClient, "availability", availability)
    monkeypatch.setattr(HearApiClient, "search", search)
    monkeypatch.setattr("src.models.affirmative.Search.auto_play_first_from_search", play)

    response = await YesIntentHandler(deps=ApplicationContainer()).handle(mock_handler_input)

    sent = availability.await_args.args[0]
    assert sent["filter"] == {"organizationId": "org-tnf"}
    assert sent["alexaUserId"] == "amzn1.ask.account.TEST"
    assert sent["limit"] == 3
    assert sent["page"] == 0
    assert "First, Buxton Talking Song" in response["outputSpeech"]["ssml"]
    assert "Second, Daily Sermons" in response["outputSpeech"]["ssml"]
    assert "Buxton Talking Song" in response["outputSpeech"]["ssml"]
    assert "Daily Sermons" in response["outputSpeech"]["ssml"]
    assert response["directives"][0]["type"] == "Dialog.UpdateDynamicEntities"
    search.assert_not_awaited()
    play.assert_not_awaited()
    active = User.snapshot(mock_handler_input)["activeDialog"]
    assert active["type"] == "availability"
    assert all(candidate["type"] == "publication" for candidate in active["context"]["candidates"])


@pytest.mark.asyncio
async def test_explicit_search_replaces_pending_ambiguity(monkeypatch, mock_handler_input):
    pending = {
        "requestId": "ambiguous-tn",
        "intent": "organization",
        "originalUtterance": "play tn",
        "searchPayload": {"query": "", "page": 0, "limit": 20},
        "slots": {},
        "candidates": [
            {"type": "organization", "id": "org-1", "name": "First TN"},
            {"type": "organization", "id": "org-2", "name": "Second TN"},
        ],
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "requestId": "fresh-tnf-request",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "tnf"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "pendingAmbiguity": pending,
        "activeDialog": {
            "type": "ambiguity",
            "context": pending,
            "createdAt": 1,
            "expiresAt": 4102444800,
        },
    }
    resolved_search = {
        "version": 1,
        "status": "resolved",
        "intent": "organization",
        "confidence": 1.0,
        "confirmationLabel": "content from Talking News Federation",
        "searchPayload": {
            "query": "",
            "filter": {"organizationIds": ["org-tnf"]},
            "page": 0,
            "limit": 20,
        },
        "slots": {
            "organizationIds": ["org-tnf"],
            "organizationName": "Talking News Federation",
            "residualQuery": "",
        },
    }

    async def resolve(utterance, **kwargs):
        return resolved_search

    resolve = AsyncMock(side_effect=resolve)
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    assert [call.args for call in resolve.await_args_list] == [("play tnf",)]
    store = User.snapshot(mock_handler_input)
    assert store["pendingAmbiguity"] is None
    assert store["activeDialog"] is None
    assert (
        mock_handler_input.attributes_manager.request_attributes["_nlp"]["confirmationLabel"]
        == "content from Talking News Federation"
    )


@pytest.mark.asyncio
async def test_candidate_in_topic_slot_resolves_before_new_search(monkeypatch, mock_handler_input):
    pending = {
        "requestId": "ambiguous-tn",
        "intent": "organization",
        "originalUtterance": "play tn",
        "searchPayload": {"query": "", "filter": {}, "page": 0, "limit": 20},
        "slots": {},
        "candidates": [
            {"type": "organization", "id": "org-bromley", "name": "Bromley TN"},
            {
                "type": "organization",
                "id": "org-neston",
                "name": "Ellesmere Port and Neston TN",
            },
            {"type": "organization", "id": "org-north", "name": "The Northumbrian"},
        ],
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "requestId": "candidate-topic-request",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "neston"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "pendingAmbiguity": pending,
        "activeDialog": {
            "type": "ambiguity",
            "context": pending,
            "expiresAt": 4102444800,
        },
    }
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "organization",
            "ambiguityResolution": True,
            "confirmationLabel": "content from Ellesmere Port and Neston TN",
            "searchPayload": {
                "query": "",
                "filter": {"organizationIds": ["org-neston"]},
                "page": 0,
                "limit": 20,
            },
            "entities": [
                {
                    "type": "organization",
                    "id": "org-neston",
                    "canonicalValue": "Ellesmere Port and Neston TN",
                }
            ],
            "slots": {
                "organizationIds": ["org-neston"],
                "organizationName": "Ellesmere Port and Neston TN",
            },
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["ambiguityResolution"] is True
    assert nlp["searchPayload"]["filter"] == {"organizationIds": ["org-neston"]}


@pytest.mark.asyncio
async def test_unmatched_clarification_keeps_ambiguity_active_without_resolver(
    monkeypatch, mock_handler_input
):
    pending = {
        "intent": "creator",
        "searchPayload": {"query": "", "filter": {}, "page": 0, "limit": 20},
        "slots": {},
        "candidates": [
            {"type": "creator", "id": "creator-one", "name": "Pendle Voice Dalesman"},
            {
                "type": "creator",
                "id": "creator-two",
                "name": "Pendle Voice Lancashire Life",
            },
        ],
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "intent": {
                "name": "ClarifySelectionIntent",
                "slots": {
                    "selection": {
                        "name": "selection",
                        "value": "something completely different",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["status"] == "ambiguous"
    assert nlp["ambiguityRetry"] is True
    store = User.snapshot(mock_handler_input)
    assert store["pendingAmbiguity"] is not None
    assert store["activeDialog"]["type"] == "ambiguity"


@pytest.mark.asyncio
async def test_show_more_without_slots_pages_pending_ambiguity_locally(
    monkeypatch, mock_handler_input
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler

    candidates = [
        {"type": "creator", "id": f"creator-{index}", "name": name}
        for index, name in enumerate(
            (
                "Pendle Voice Leader and Times",
                "Pendle Voice Dalesman",
                "Pendle Voice Lancashire Life",
                "Pendle Voice Gazette",
                "Pendle Voice Chronicle",
                "Pendle Voice Echo",
                "Pendle Voice Herald",
                "Pendle Voice Review",
            )
        )
    ]
    pending = {
        "intent": "search",
        "searchPayload": {"query": "", "filter": {}},
        "slots": {},
        "candidates": candidates,
        "choiceCandidates": candidates,
        "displayedCandidates": candidates[:3],
        "spokenCandidateOffset": 3,
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": "ShowMoreBrowseIntent"}}
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    }
    mock_handler_input.response_builder = ResponseBuilder()
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    response = await IntentDispatchGateHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )
    resolve.assert_not_awaited()
    assert "Gazette" in response["outputSpeech"]["ssml"]
    assert "Chronicle" in response["outputSpeech"]["ssml"]
    assert "First, Gazette" in response["outputSpeech"]["ssml"]
    assert "say show more or next" in response["outputSpeech"]["ssml"]
    values = response["directives"][0]["types"][0]["values"]
    assert [value["id"] for value in values] == ["creator-3", "creator-4", "creator-5"]
    assert "first" in values[0]["name"]["synonyms"]
    assert "trouble understanding" not in response["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_show_more_fetches_next_publication_page_and_selection_uses_page_zero(
    monkeypatch, mock_handler_input
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler

    initial = [
        {"type": "publication", "id": f"publication-{index}", "name": name}
        for index, name in enumerate(
            ("Buxton Talking Song", "Daily Sermons", "Hexham Talking Newspapers Reading"),
            start=1,
        )
    ]
    pending = {
        "intent": "organization",
        "searchPayload": {
            "query": "",
            "filter": {"organizationIds": ["org-tnf"]},
            "limit": 3,
            "page": 0,
        },
        "slots": {"organizationIds": ["org-tnf"]},
        "candidates": initial,
        "choiceCandidates": initial,
        "displayedCandidates": initial,
        "spokenCandidateOffset": 3,
        "candidatePagination": {
            "kind": "publication",
            "currentPage": 0,
            "totalPages": 2,
            "totalHits": 5,
            "limit": 3,
        },
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": "ShowMoreBrowseIntent", "slots": {}}}
    )
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    }
    search = AsyncMock(
        return_value={
            "failed": False,
            "results": [],
            "_publication_choices": [
                initial[-1],
                {
                    "type": "publication",
                    "id": "publication-4",
                    "name": "Swindon Talking News",
                },
                {
                    "type": "publication",
                    "id": "publication-5",
                    "name": "York Audio Magazine",
                },
            ],
            "page": 1,
            "total_pages": 2,
            "total_hits": 5,
        }
    )
    resolve = AsyncMock()
    monkeypatch.setattr(HearApiClient, "search", search)
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    response = await IntentDispatchGateHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )

    resolve.assert_not_awaited()
    sent = search.await_args.args[0]
    assert sent == {
        "query": "",
        "filter": {"organizationIds": ["org-tnf"]},
        "limit": 3,
        "page": 1,
        "alexaUserId": "amzn1.ask.account.TEST",
    }
    assert "Swindon Talking News" in response["outputSpeech"]["ssml"]
    assert "York Audio Magazine" in response["outputSpeech"]["ssml"]
    directive = response["directives"][0]
    assert directive["type"] == "Dialog.UpdateDynamicEntities"
    dynamic_values = directive["types"][0]["values"]
    assert [value["id"] for value in dynamic_values] == ["publication-4", "publication-5"]
    assert "first" in dynamic_values[0]["name"]["synonyms"]
    assert "second" in dynamic_values[1]["name"]["synonyms"]
    updated = User.snapshot(mock_handler_input)["pendingAmbiguity"]
    assert len(updated["candidates"]) == 5
    assert [candidate["id"] for candidate in updated["displayedCandidates"]] == [
        "publication-4",
        "publication-5",
    ]
    assert updated["candidatePagination"]["currentPage"] == 1

    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "intent": {
                "name": "ClarifySelectionIntent",
                "slots": {"selection": {"name": "selection", "value": "second"}},
            },
        }
    )
    mock_handler_input.response_builder = ResponseBuilder()
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["searchPayload"]["filter"] == {"publicationIds": ["publication-5"]}
    assert nlp["searchPayload"]["page"] == 0


@pytest.mark.asyncio
async def test_publication_choices_support_previous_and_next_navigation(
    monkeypatch, mock_handler_input
):
    from src.controllers.browse import BrowseNavigationHandler

    candidates = [
        {"type": "publication", "id": f"publication-{index}", "name": name}
        for index, name in enumerate(
            (
                "Buxton Talking Song",
                "Daily Sermons",
                "Hexham Talking Newspapers Reading",
                "Swindon Talking News",
                "York Audio Magazine",
            ),
            start=1,
        )
    ]
    pending = {
        "intent": "organization",
        "searchPayload": {"query": "", "filter": {}, "limit": 3, "page": 1},
        "slots": {},
        "candidates": candidates,
        "choiceCandidates": candidates,
        "displayedCandidates": candidates[3:],
        "spokenCandidateOffset": 5,
        "candidatePagination": {
            "kind": "publication",
            "currentPage": 1,
            "totalPages": 2,
            "totalHits": 5,
            "limit": 3,
        },
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    }
    search = AsyncMock()
    monkeypatch.setattr(HearApiClient, "search", search)
    handler = BrowseNavigationHandler(deps=ApplicationContainer())

    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "intent": {"name": "ShowPreviousBrowseIntent", "slots": {}},
        }
    )
    mock_handler_input.response_builder = ResponseBuilder()
    assert handler.can_handle(mock_handler_input) is True
    previous_response = await handler.handle(mock_handler_input)
    assert "previous publication choices" in previous_response["outputSpeech"]["ssml"]
    assert "First, Buxton Talking Song" in previous_response["outputSpeech"]["ssml"]
    assert "Second, Daily Sermons" in previous_response["outputSpeech"]["ssml"]
    assert "Third, Hexham Talking Newspapers Reading" in previous_response["outputSpeech"]["ssml"]
    assert "Buxton Talking Song" in previous_response["outputSpeech"]["ssml"]
    assert "say show more or next" in previous_response["outputSpeech"]["ssml"]
    assert [
        candidate["id"]
        for candidate in User.snapshot(mock_handler_input)["pendingAmbiguity"][
            "displayedCandidates"
        ]
    ] == ["publication-1", "publication-2", "publication-3"]

    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": "AMAZON.NextIntent", "slots": {}}}
    )
    mock_handler_input.response_builder = ResponseBuilder()
    assert handler.can_handle(mock_handler_input) is True
    next_response = await handler.handle(mock_handler_input)
    assert "next publication choices" in next_response["outputSpeech"]["ssml"]
    assert "Swindon Talking News" in next_response["outputSpeech"]["ssml"]
    assert "York Audio Magazine" in next_response["outputSpeech"]["ssml"]
    assert "First, Swindon Talking News" in next_response["outputSpeech"]["ssml"]
    assert "Second, York Audio Magazine" in next_response["outputSpeech"]["ssml"]
    assert "show more" not in next_response["outputSpeech"]["ssml"]
    next_values = next_response["directives"][0]["types"][0]["values"]
    assert [value["id"] for value in next_values] == ["publication-4", "publication-5"]
    assert "first" in next_values[0]["name"]["synonyms"]
    assert "second" in next_values[1]["name"]["synonyms"]
    search.assert_not_awaited()


@pytest.mark.parametrize("intent_name", ["AMAZON.NextIntent", "AMAZON.PreviousIntent"])
def test_browse_navigation_leaves_transport_intents_to_playback_without_ambiguity(
    mock_handler_input, intent_name
):
    from src.controllers.browse import BrowseNavigationHandler

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": intent_name, "slots": {}}}
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    handler = BrowseNavigationHandler(deps=ApplicationContainer())
    assert handler.can_handle(mock_handler_input) is False


@pytest.mark.asyncio
async def test_dynamic_entity_id_selects_pending_candidate_without_resolver(
    monkeypatch, mock_handler_input
):
    candidates = [
        {
            "type": "creator",
            "id": "creator-leader",
            "name": "Pendle Voice Leader and Times",
        },
        {"type": "creator", "id": "creator-dalesman", "name": "Pendle Voice Dalesman"},
    ]
    pending = {
        "intent": "search",
        "searchPayload": {"query": "", "filter": {}},
        "slots": {},
        "candidates": candidates,
        "choiceCandidates": candidates,
        "displayedCandidates": candidates,
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "intent": {
                "name": "ClarifySelectionIntent",
                "slots": {
                    "selection": {
                        "name": "selection",
                        "value": "dalesman",
                        "resolutions": {
                            "resolutionsPerAuthority": [
                                {
                                    "status": {"code": "ER_SUCCESS_MATCH"},
                                    "values": [
                                        {
                                            "value": {
                                                "id": "creator-dalesman",
                                                "name": "Pendle Voice Dalesman",
                                            }
                                        }
                                    ],
                                }
                            ]
                        },
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["ambiguityResolution"] is True
    assert nlp["searchPayload"]["filter"] == {"creatorIds": ["creator-dalesman"]}
    assert User.snapshot(mock_handler_input)["pendingAmbiguity"] is None


@pytest.mark.asyncio
async def test_publication_choice_replaces_source_filter_with_publication_filter(
    monkeypatch, mock_handler_input
):
    from src.middleware.confirmation import ConfirmationMiddleware
    from src.models.play import PlayContent

    pending = {
        "intent": "organization",
        "searchPayload": {
            "query": "",
            "filter": {
                "organizationIds": ["org-tnf"],
                "isPublication": True,
                "tags": ["stale-tag"],
            },
            "limit": 3,
            "page": 0,
            "sort": "trending",
        },
        "slots": {"organizationIds": ["org-tnf"]},
        "candidates": [
            {
                "type": "publication",
                "id": "publication-buxton",
                "name": "Buxton Talking Song",
            },
            {
                "type": "publication",
                "id": "publication-sermons",
                "name": "Daily Sermons",
            },
        ],
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "intent": {
                "name": "ClarifySelectionIntent",
                "slots": {"selection": {"name": "selection", "value": "first"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    }
    resolve = AsyncMock()
    search = AsyncMock(
        return_value={
            "failed": False,
            "results": [
                {
                    "contentId": "track-buxton",
                    "audioUrl": "https://cdn.hear.media/track-buxton.mp3",
                }
            ],
            "total_hits": 1,
        }
    )
    play = AsyncMock(return_value={"shouldEndSession": True})
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    monkeypatch.setattr(HearApiClient, "search", search)
    monkeypatch.setattr("src.models.search.Search.auto_play_first_from_search", play)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "publication"
    assert nlp["searchPayload"] == {
        "query": "",
        "filter": {"publicationIds": ["publication-buxton"]},
        "limit": 3,
        "page": 0,
    }
    assert nlp["slots"]["publicationIds"] == ["publication-buxton"]
    assert "organizationIds" not in nlp["slots"]
    ConfirmationMiddleware().process(mock_handler_input)
    assert (
        mock_handler_input.attributes_manager.request_attributes.get("_pendingConfirmation") is None
    )

    response = await PlayContent(deps=ApplicationContainer()).execute(mock_handler_input)

    search.assert_awaited_once_with(
        {
                "alexaUserId": "amzn1.ask.account.TEST",
                "query": "",
                "isLocal": False,
                "limit": 3,
            "page": 0,
            "filter": {"publicationIds": ["publication-buxton"]},
        },
        timeout_ms=8000,
    )
    play.assert_awaited_once()
    assert response == {"shouldEndSession": True}
    assert User.snapshot(mock_handler_input)["awaitingSearchConfirmation"] is False


@pytest.mark.asyncio
async def test_ordinal_selects_currently_displayed_ambiguity_without_resolver(
    monkeypatch, mock_handler_input
):
    candidates = [
        {"type": "creator", "id": f"creator-{index}", "name": name}
        for index, name in enumerate(
            (
                "Pendle Voice Leader and Times",
                "Pendle Voice Dalesman",
                "Pendle Voice Lancashire Life",
            )
        )
    ]
    pending = {
        "intent": "search",
        "searchPayload": {"query": "", "filter": {}},
        "slots": {},
        "candidates": candidates,
        "choiceCandidates": candidates,
        "displayedCandidates": candidates,
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "intent": {
                "name": "ClarifySelectionIntent",
                "slots": {"selection": {"name": "selection", "value": "second"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["searchPayload"]["filter"] == {"creatorIds": ["creator-1"]}


@pytest.mark.asyncio
async def test_wakefield_reply_uses_legacy_ambiguity_before_onboarding(
    monkeypatch, mock_handler_input
):
    """A WTN clarification reply must never become the listener's town."""
    candidates = [
        {
            "type": "organization",
            "id": "org-wakefield",
            "name": "Wakefield Talking Newspaper",
        },
        {
            "type": "organization",
            "id": "org-walsall",
            "name": "Walsall Talking Newspaper",
        },
        {
            "type": "organization",
            "id": "org-warrington",
            "name": "Warrington Talking Newspaper",
        },
    ]
    pending = {
        "requestId": "ambiguous-wtn",
        "intent": "organization",
        "originalUtterance": "play wtn",
        "searchPayload": {"query": "", "page": 0, "limit": 20},
        "slots": {},
        "candidates": candidates,
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "TownCaptureIntent",
                "slots": {"townName": {"name": "townName", "value": "wakefield"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingStage": "ask_town",
        "pendingAmbiguity": pending,
        "activeDialog": None,
    }
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "organization",
                "confirmationLabel": "content from Wakefield Talking Newspaper",
                "searchPayload": {
                    "query": "",
                    "filter": {"organizationIds": ["org-wakefield"]},
                    "page": 0,
                    "limit": 20,
                },
                "slots": {
                    "organizationIds": ["org-wakefield"],
                    "organizationName": "Wakefield Talking Newspaper",
                    "residualQuery": "",
                },
            }
        ),
    )
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    store = User.snapshot(mock_handler_input)
    assert nlp["intent"] == "organization"
    assert nlp["searchPayload"]["filter"] == {"organizationIds": ["org-wakefield"]}
    assert store["userCity"] is None
    assert store.get("pendingLocationConfirm") is None
    assert not TownCaptureHandler(deps=ApplicationContainer()).can_handle(mock_handler_input)


@pytest.mark.asyncio
async def test_misrouted_unresolved_source_is_not_called_talking_newspaper(
    mock_handler_input,
):
    from src.controllers.play import PlayByOrganizationHandler

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayByOrganizationIntent",
                "slots": {
                    "organizationQuery": {
                        "name": "organizationQuery",
                        "value": "Orion meta glasses from Paul",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "intent": "general",
                "slots": {
                    "residualQuery": "orion meta glasses",
                    "unresolvedReferences": [
                        {
                            "relation": "from",
                            "phrase": "paul",
                            "expectedTypes": ["creator", "organization", "publication"],
                        }
                    ],
                },
            },
        }
    )
    await PlayByOrganizationHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "creator, organisation or publication named paul" in spoken
    assert "talking newspaper" not in spoken
    assert User.snapshot(mock_handler_input)["awaitingOrganizationName"] is False


@pytest.mark.asyncio
async def test_generic_talking_newspaper_request_prompts_and_persists_context(
    monkeypatch, mock_handler_input
):
    from src.controllers.play import PlayByOrganizationHandler

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayByOrganizationIntent",
                "slots": {
                    "organizationQuery": {
                        "name": "organizationQuery",
                        "value": "talking news paper",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
            "_nlp": {
                "intent": "organization",
                "slots": {"genericOrganizationRequest": True},
            },
        }
    )
    discover = AsyncMock()
    monkeypatch.setattr("src.models.search.Search.discover_content_via_search", discover)
    await PlayByOrganizationHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    assert User.snapshot(mock_handler_input)["awaitingOrganizationName"] is True
    assert DialogStateManager.get_active(mock_handler_input)["type"] == "organization_name"
    chained_builder = mock_handler_input.response_builder.speak.return_value.reprompt.return_value
    chained_builder.add_directive.assert_called_once()
    directive = chained_builder.add_directive.call_args.args[0]
    assert directive == DialogStateManager.capture_directive("organization_name")
    json.dumps(directive)
    discover.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_talking_newspaper_pipeline_prompts_when_slot_has_no_value(
    monkeypatch, mock_handler_input
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayByOrganizationIntent",
                "slots": {
                    "organizationQuery": {
                        "name": "organizationQuery",
                        "confirmationStatus": "NONE",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    response = await IntentDispatchGateHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )
    assert "Which talking newspaper would you like" in response["outputSpeech"]["ssml"]
    assert response["directives"] == [
        DialogStateManager.capture_directive("organization_name")
    ]
    assert User.snapshot(mock_handler_input)["awaitingOrganizationName"] is True
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_talking_newspaper_slot_value_still_prompts_for_name(
    monkeypatch, mock_handler_input
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayByOrganizationIntent",
                "slots": {
                    "organizationQuery": {
                        "name": "organizationQuery",
                        "value": "talking newspaper",
                        "confirmationStatus": "NONE",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    response = await IntentDispatchGateHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )
    assert "Which talking newspaper would you like" in response["outputSpeech"]["ssml"]
    assert response["directives"] == [
        DialogStateManager.capture_directive("organization_name")
    ]
    assert User.snapshot(mock_handler_input)["awaitingOrganizationName"] is True
    resolve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "generic_phrase",
    [
        "talking newspaper",
        "talking a talking newspaper",
        "play from a talking a talking newspaper",
    ],
)
async def test_misrouted_talking_newspaper_play_content_prompts_for_name(
    monkeypatch, mock_handler_input, generic_phrase
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler
    from src.middleware.confirmation import (
        ConfirmationMiddleware,
        SearchConfirmationGateHandler,
    )

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": generic_phrase}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    assert SearchConfirmationGateHandler().can_handle(mock_handler_input) is False
    response = await IntentDispatchGateHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )
    assert "Which talking newspaper would you like" in response["outputSpeech"]["ssml"]
    assert response["directives"] == [
        DialogStateManager.capture_directive("organization_name")
    ]
    assert User.snapshot(mock_handler_input)["awaitingOrganizationName"] is True
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_creator_pipeline_asks_for_city(monkeypatch, mock_handler_input):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "ChooseSourceKindIntent",
                "slots": {
                    "sourceKind": {
                        "name": "sourceKind",
                        "value": "creator",
                        "confirmationStatus": "NONE",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    response = await IntentDispatchGateHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )
    assert "Which city would you like me to find creators in" in response["outputSpeech"]["ssml"]
    assert response["directives"] == [DialogStateManager.capture_directive("creator_location")]
    assert response["shouldEndSession"] is False
    assert "awaitingCreatorName" not in User.snapshot(mock_handler_input)
    assert DialogStateManager.get_active(mock_handler_input)["type"] == "creator_location"
    resolve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slot_name", "slot_value"),
    [
        ("PlayContentIntent", "topic", "creator"),
        ("PlayContentIntent", "topic", "creators"),
        ("SearchContentIntent", "searchQuery", "play from a creator"),
        ("SearchContentIntent", "searchQuery", "find me an author"),
        ("CarrierlessDiscoveryIntent", "discoveryQuery", "create a"),
        ("PlayByOrganizationIntent", "organizationQuery", "narrator"),
        ("PlayPublicationIntent", "publicationSourceQuery", "reader"),
        ("BrowseByCategoryIntent", "category", "content creators"),
        ("ClarifySelectionIntent", "selection", "independent creator"),
    ],
)
async def test_live_generic_creator_fallback_asks_for_city(
    monkeypatch,
    mock_handler_input,
    intent_name,
    slot_name,
    slot_value,
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": intent_name,
                "slots": {
                    slot_name: {
                        "name": slot_name,
                        "value": slot_value,
                        "confirmationStatus": "NONE",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    response = await IntentDispatchGateHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )

    assert "Which city would you like me to find creators in" in response["outputSpeech"]["ssml"]
    assert response["directives"] == [DialogStateManager.capture_directive("creator_location")]
    assert response["shouldEndSession"] is False
    assert DialogStateManager.get_active(mock_handler_input)["type"] == "creator_location"
    resolve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slot_name", "slot_value"),
    [
        ("PlayContentIntent", "topic", "talking newspapers"),
        ("SearchContentIntent", "searchQuery", "play from a talking newspaper"),
        ("CarrierlessDiscoveryIntent", "discoveryQuery", "audio newspaper"),
        ("SearchCreatorIntent", "searchQuery", "talking news"),
        ("PlayPublicationIntent", "publicationSourceQuery", "spoken newspaper"),
        ("BrowseByCategoryIntent", "category", "talking news paper"),
        ("ClarifySelectionIntent", "selection", "local talking newspaper"),
    ],
)
async def test_live_generic_talking_newspaper_fallback_asks_for_name(
    monkeypatch,
    mock_handler_input,
    intent_name,
    slot_name,
    slot_value,
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": intent_name,
                "slots": {
                    slot_name: {
                        "name": slot_name,
                        "value": slot_value,
                        "confirmationStatus": "NONE",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    response = await IntentDispatchGateHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )

    assert "Which talking newspaper would you like" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False
    assert DialogStateManager.get_active(mock_handler_input)["type"] == "organization_name"
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_creator_city_reply_uses_location_resolver_without_saving_profile(
    mock_handler_input,
):
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "search",
                "slots": {
                    "city": "Manchester",
                    "placeName": "Manchester",
                    "countryCode": "gb",
                    "latitude": 53.4808,
                    "longitude": -2.2426,
                    "isLocal": True,
                },
                "searchPayload": {
                    "query": "",
                    "filter": {
                        "city": "Manchester",
                        "countryCode": "gb",
                        "latitude": 53.4808,
                        "longitude": -2.2426,
                    },
                },
                "resolution": {
                    "match": {
                        "city": "Manchester",
                        "countryCode": "gb",
                        "latitude": 53.4808,
                        "longitude": -2.2426,
                    }
                },
            }
        )
    )
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SelectCreatorCityIntent",
                "slots": {
                    "cityQuery": {
                        "name": "cityQuery",
                        "value": "Manchester",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "listenerId": "listener-1",
        "userCity": "Swindon",
        "latitude": 51.56,
        "longitude": -1.78,
        "activeDialog": {
            "type": "creator_location",
            "context": {"slotName": "cityQuery"},
            "expiresAt": 4102444800,
        },
    }

    await ResolverInterceptor(
        deps=ApplicationContainer(resolver=resolver, progressive=progressive)
    ).process(mock_handler_input)

    resolver.resolve_utterance.assert_awaited_once()
    resolver_call = resolver.resolve_utterance.await_args
    assert resolver_call.args == ("Manchester",)
    assert resolver_call.kwargs["alexa_user_id"] == "amzn1.ask.account.TEST"
    assert resolver_call.kwargs["listener_id"] == "listener-1"
    assert resolver_call.kwargs["prefer_location"] is True
    assert resolver_call.kwargs["timeout_ms"] > 0
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "creator_location"
    assert nlp["slots"]["city"] == "Manchester"
    store = User.snapshot(mock_handler_input)
    assert store["userCity"] == "Swindon"
    assert store["latitude"] == 51.56
    assert store["longitude"] == -1.78
    assert DialogStateManager.get_active(mock_handler_input) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slot_name", "spoken", "alexa_match", "resolver_input", "city"),
    [
        ("SelectCreatorCityIntent", "cityQuery", "yuck", "York", "York", "York"),
        ("SelectCreatorCityIntent", "cityQuery", "seven ox", None, "seven ox", "Sevenoaks"),
        ("PlayContentIntent", "topic", "liverpool", None, "liverpool", "Liverpool"),
        ("SearchContentIntent", "searchQuery", "york", None, "york", "York"),
        (
            "CarrierlessDiscoveryIntent",
            "discoveryQuery",
            "york",
            "York Talking Newspaper",
            "york",
            "York",
        ),
    ],
)
async def test_creator_city_dialog_uses_location_canonical_or_raw_resolver_input(
    mock_handler_input,
    intent_name,
    slot_name,
    spoken,
    alexa_match,
    resolver_input,
    city,
):
    from src.middleware.dialog_validation import DialogValidationInterceptor

    slot = {"name": slot_name, "value": spoken}
    if alexa_match:
        slot["resolutions"] = {
            "resolutionsPerAuthority": [
                {
                    "status": {"code": "ER_SUCCESS_MATCH"},
                    "values": [{"value": {"name": alexa_match}}],
                }
            ]
        }
    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "search",
                "slots": {},
                "searchPayload": {"query": city, "filter": {"unwanted": True}},
                "resolution": {
                    "match": {
                        "city": city,
                        "countryCode": "gb",
                        "latitude": 53.0,
                        "longitude": -1.0,
                    }
                },
            }
        )
    )
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))
    container = ApplicationContainer(resolver=resolver, progressive=progressive)
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": intent_name, "slots": {slot_name: slot}},
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "activeDialog": {
            "type": "creator_location",
            "context": {"slotName": "cityQuery"},
            "expiresAt": 4102444800,
        },
    }

    DialogValidationInterceptor().process(mock_handler_input)
    await ResolverInterceptor(deps=container).process(mock_handler_input)

    resolver.resolve_utterance.assert_awaited_once()
    assert resolver.resolve_utterance.await_args.args == (resolver_input,)
    assert resolver.resolve_utterance.await_args.kwargs["prefer_location"] is True
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["slots"]["city"] == city
    assert nlp["searchPayload"] == {
        "query": "",
        "filter": {
            "city": city,
            "countryCode": "gb",
            "latitude": 53.0,
            "longitude": -1.0,
        },
    }
    assert DialogStateManager.get_active(mock_handler_input) is None


@pytest.mark.asyncio
async def test_creator_city_rejects_non_location_even_when_alexa_matches_a_city(
    mock_handler_input,
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler
    from src.middleware.dialog_validation import DialogValidationInterceptor

    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "search",
                "slots": {"city": "York"},
                "searchPayload": {"query": "", "filter": {"city": "York"}},
                "resolution": {"match": None, "candidates": []},
            }
        )
    )
    heara = SimpleNamespace(availability=AsyncMock())
    container = ApplicationContainer(
        resolver=resolver,
        progressive=SimpleNamespace(send=AsyncMock(return_value=True)),
        heara=heara,
    )
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SelectCreatorCityIntent",
                "slots": {
                    "cityQuery": {
                        "name": "cityQuery",
                        "value": "yuck",
                        "resolutions": {
                            "resolutionsPerAuthority": [
                                {
                                    "status": {"code": "ER_SUCCESS_MATCH"},
                                    "values": [{"value": {"name": "York"}}],
                                }
                            ]
                        },
                    }
                },
            },
        }
    )
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "activeDialog": {
            "type": "creator_location",
            "context": {"slotName": "cityQuery"},
            "expiresAt": 4102444800,
        },
    }

    DialogValidationInterceptor().process(mock_handler_input)
    await ResolverInterceptor(deps=container).process(mock_handler_input)
    response = await IntentDispatchGateHandler(deps=container).handle(mock_handler_input)

    assert resolver.resolve_utterance.await_args.args == ("York",)
    assert Speech.CREATOR_CITY_NOT_RECOGNISED in response["outputSpeech"]["ssml"]
    heara.availability.assert_not_awaited()
    assert DialogStateManager.get_active(mock_handler_input)["type"] == "creator_location"


@pytest.mark.asyncio
async def test_creator_city_resolver_failure_reasks_without_entering_onboarding(
    mock_handler_input,
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler

    resolver = SimpleNamespace(
        resolve_utterance=AsyncMock(side_effect=ResolverUnavailable("unavailable"))
    )
    progressive = SimpleNamespace(send=AsyncMock(return_value=True))
    container = ApplicationContainer(resolver=resolver, progressive=progressive)
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SelectCreatorCityIntent",
                "slots": {
                    "cityQuery": {"name": "cityQuery", "value": "not a real city"}
                },
            },
        }
    )
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "activeDialog": {
            "type": "creator_location",
            "context": {"slotName": "cityQuery"},
            "expiresAt": 4102444800,
        },
    }

    await ResolverInterceptor(deps=container).process(mock_handler_input)
    response = await IntentDispatchGateHandler(deps=container).handle(mock_handler_input)

    assert Speech.CREATOR_CITY_NOT_RECOGNISED in response["outputSpeech"]["ssml"]
    assert response["directives"] == [
        DialogStateManager.capture_directive("creator_location")
    ]
    store = User.snapshot(mock_handler_input)
    assert store["activeDialog"]["type"] == "creator_location"
    assert store["onboardingStage"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "flag", "dialog_type", "expected_speech"),
    [
        (
            "SelectOrganizationIntent",
            "awaitingOrganizationName",
            "organization_name",
            "Say its full name",
        ),
    ],
)
async def test_empty_delegated_source_reply_gives_name_recovery(
    mock_handler_input, intent_name, flag, dialog_type, expected_speech
):
    from src.controllers.play import PlayByOrganizationHandler

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": intent_name, "slots": {}},
        }
    )
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        flag: True,
        "activeDialog": {
            "type": dialog_type,
            "context": {},
            "expiresAt": 4102444800,
        },
    }
    response = await PlayByOrganizationHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )

    assert expected_speech in response["outputSpeech"]["ssml"]
    assert User.snapshot(mock_handler_input)[flag] is False
    assert User.snapshot(mock_handler_input)["activeDialog"] is None


@pytest.mark.parametrize(
    ("dialog_type", "flag", "slot_name"),
    [
        (
            "organization_name",
            "awaitingOrganizationName",
            "organizationQuery",
        ),
    ],
)
def test_source_name_collision_rechains_the_active_capture_dialog(
    mock_handler_input, dialog_type, flag, slot_name
):
    from src.middleware.dialog_validation import (
        DialogValidationGateHandler,
        DialogValidationInterceptor,
    )

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "FeedbackEnjoyedIntent", "slots": {}},
        }
    )
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        flag: True,
        "activeDialog": {
            "type": dialog_type,
            "context": {"slotName": slot_name},
            "expiresAt": 4102444800,
        },
    }

    DialogValidationInterceptor().process(mock_handler_input)
    gate = DialogValidationGateHandler()
    assert gate.can_handle(mock_handler_input)
    response = gate.handle(mock_handler_input)

    assert "outputSpeech" in response
    assert response["shouldEndSession"] is False
    assert response["directives"] == [DialogStateManager.capture_directive(dialog_type)]


@pytest.mark.parametrize(
    ("dialog_type", "flag", "expected_speech"),
    [
        (
            "organization_name",
            "awaitingOrganizationName",
            "Say its full name",
        ),
    ],
)
def test_unknown_bare_source_reply_exits_capture_with_name_guidance(
    mock_handler_input, dialog_type, flag, expected_speech
):
    from src.middleware.dialog_validation import (
        DialogValidationGateHandler,
        DialogValidationInterceptor,
    )

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "AMAZON.FallbackIntent", "slots": {}},
        }
    )
    mock_handler_input.response_builder = ResponseBuilder()
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        flag: True,
        "activeDialog": {
            "type": dialog_type,
            "context": {},
            "expiresAt": 4102444800,
        },
    }

    DialogValidationInterceptor().process(mock_handler_input)
    response = DialogValidationGateHandler().handle(mock_handler_input)

    assert expected_speech in response["outputSpeech"]["ssml"]
    assert response.get("directives") is None
    assert response["shouldEndSession"] is False
    assert User.snapshot(mock_handler_input)[flag] is False
    assert User.snapshot(mock_handler_input)["activeDialog"] is None


@pytest.mark.asyncio
async def test_generic_publication_pipeline_prompts_when_slot_has_no_value(
    monkeypatch, mock_handler_input
):
    from src.controllers.intent_dispatch import IntentDispatchGateHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayPublicationIntent",
                "slots": {
                    "publicationSourceQuery": {
                        "name": "publicationSourceQuery",
                        "confirmationStatus": "NONE",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    response = await IntentDispatchGateHandler(deps=ApplicationContainer()).handle(
        mock_handler_input
    )
    assert "Which publication would you like?" in response["outputSpeech"]["ssml"]
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_talking_newspaper_follow_up_forces_organization_resolution(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "ynt"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
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
        ResolverClient,
        "resolve_utterance",
        AsyncMock(return_value={"version": 1, "status": "resolved", **resolved}),
    )
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "organization"
    assert nlp["slots"]["organizationIds"] == ["org-ytn"]
    assert nlp["slots"]["organizationQuery"] == "ynt"
    assert nlp["slots"]["organizationFollowUp"] is True


@pytest.mark.asyncio
async def test_resolved_talking_newspaper_follow_up_requires_confirmation(
    monkeypatch, mock_handler_input
):
    from src.controllers.play import PlayByOrganizationHandler

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "ynt"}},
            },
        }
    )
    resolved_slots = {
        "organizationIds": ["org-ytn"],
        "organizationName": "York Talking News",
        "organizationQuery": "ynt",
        "organizationFollowUp": True,
        "residualQuery": "",
    }
    mock_handler_input.attributes_manager.request_attributes.update(
        {
            "_store": {
                **StateSchema.DEFAULT_STORE,
                "onboardingComplete": True,
                "awaitingOrganizationName": True,
            },
            "_nlp": {"intent": "organization", "slots": resolved_slots},
        }
    )
    discover = AsyncMock()
    monkeypatch.setattr("src.models.search.Search.discover_content_via_search", discover)
    await PlayByOrganizationHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    store = User.snapshot(mock_handler_input)
    assert store["awaitingOrganizationName"] is False
    assert store["awaitingSearchConfirmation"] is True
    assert store["pendingResolution"]["intent"] == "organization"
    assert store["pendingResolution"]["confirmationLabel"] == "content from York Talking News"
    discover.assert_not_awaited()


@pytest.mark.asyncio
async def test_location_follow_up_yes_checks_community_availability(
    monkeypatch, mock_handler_input
):
    from src.models.affirmative import Affirmative

    handler_input = _town_request(mock_handler_input, "Manchester")
    handler_input.response_builder = ResponseBuilder()
    store = User.snapshot(handler_input)
    store.update(
        {
            "userCity": "Manchester",
            "locality": "Manchester",
            "onboardingComplete": True,
            "onboardingStage": None,
            "awaitingCommunityPlayback": True,
        }
    )
    handler_input.attributes_manager.request_attributes["_store"] = store
    discover = AsyncMock(
        return_value={
            "failed": False,
            "results": [
                {
                    "contentId": "content-1",
                    "title": "Manchester update",
                    "spokenTitle": "Manchester update",
                    "audioUrl": "https://cdn.hear.media/content-1.mp3",
                }
            ],
        }
    )
    play = AsyncMock(return_value={"response": "playing"})
    availability = AsyncMock(
        return_value={
            "failed": False,
            "page": 0,
            "total_pages": 1,
            "has_more": False,
            "organizations": [
                {"type": "organization", "id": "org-1", "name": "Manchester Talking News"}
            ],
            "creators": [],
        }
    )
    monkeypatch.setattr(HearApiClient, "availability", availability)
    monkeypatch.setattr("src.models.affirmative.Search.discover_content_via_search", discover)
    monkeypatch.setattr("src.models.affirmative.Search.auto_play_first_from_search", play)
    response = await Affirmative(deps=ApplicationContainer())._handle_community_play_yes(
        handler_input, store
    )
    assert "I found Manchester Talking News" in response["outputSpeech"]["ssml"]
    assert User.snapshot(handler_input)["awaitingCommunityPlayback"] is False
    nlp = handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["slots"]["city"] == "Manchester"
    assert nlp["slots"]["isLocal"] is True
    availability.assert_awaited_once()
    discover.assert_not_awaited()
    play.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_setup_yes_retries_voice_location_permission(mock_handler_input):
    from src.models.affirmative import Affirmative

    handler_input = _town_request(mock_handler_input, "yes")
    handler_input.request_envelope.request.intent.name = "AMAZON.YesIntent"
    handler_input.response_builder = ResponseBuilder()
    handler_input.attributes_manager.get_session_attributes = lambda: {}
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "onboardingStage": "confirm_town_for_community",
    }
    response = await Affirmative(deps=ApplicationContainer()).execute(handler_input)
    store = User.snapshot(handler_input)
    assert store["onboardingStage"] is None
    assert store["awaitingCommunityPlayback"] is True
    directive = response["directives"][0]
    assert directive["type"] == "Connections.StartConnection"
    assert directive["token"] == "onboarding_location"


@pytest.mark.asyncio
async def test_local_setup_no_keeps_guest_out_of_permission_flow(mock_handler_input):
    from src.models.decline import Decline

    handler_input = _town_request(mock_handler_input, "no")
    handler_input.request_envelope.request.intent.name = "AMAZON.NoIntent"
    handler_input.attributes_manager.get_session_attributes = lambda: {}
    handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "onboardingStage": "confirm_town_for_community",
    }
    await Decline(deps=ApplicationContainer()).execute(handler_input)
    store = User.snapshot(handler_input)
    assert store["onboardingStage"] is None
    assert store["awaitingCommunityPlayback"] is False
    handler_input.response_builder.add_directive.assert_not_called()


@pytest.mark.asyncio
async def test_local_location_confirmation_resumes_original_playback(
    monkeypatch, mock_handler_input
):
    from src.models.affirmative import Affirmative

    handler_input = _town_request(mock_handler_input, "yes")
    handler_input.response_builder = ResponseBuilder()
    store = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "onboardingStage": "await_location_confirm",
        "awaitingLocationConfirm": True,
        "awaitingCommunityPlayback": True,
        "pendingLocationConfirm": {
            "city": "York",
            "locality": "York",
            "countryCode": "GB",
            "latitude": 53.96,
            "longitude": -1.08,
        },
    }
    handler_input.attributes_manager.request_attributes["_store"] = store
    discover = AsyncMock(
        return_value={
            "results": [
                {
                    "contentId": "local-1",
                    "title": "York update",
                    "audioUrl": "https://cdn.hear.media/local-1.mp3",
                }
            ]
        }
    )
    play = AsyncMock(return_value={"response": "playing-local"})
    availability = AsyncMock(
        return_value={
            "failed": False,
            "page": 0,
            "total_pages": 1,
            "has_more": False,
            "organizations": [
                {"type": "organization", "id": "org-york", "name": "York Talking News"}
            ],
            "creators": [],
        }
    )
    monkeypatch.setattr(HearApiClient, "availability", availability)
    monkeypatch.setattr("src.models.affirmative.Search.discover_content_via_search", discover)
    monkeypatch.setattr("src.models.affirmative.Search.auto_play_first_from_search", play)
    result = await Affirmative(deps=ApplicationContainer())._confirm_location(handler_input, store)
    assert "I found York Talking News" in result["outputSpeech"]["ssml"]
    updated = User.snapshot(handler_input)
    assert updated["userCity"] == "York"
    assert updated["awaitingCommunityPlayback"] is False
    assert updated["awaitingProfilePermission"] is False
    availability.assert_awaited_once()
    discover.assert_not_awaited()
    play.assert_not_awaited()


@pytest.mark.asyncio
async def test_location_confirmation_finishes_onboarding_without_forcing_empty_search(
    monkeypatch, mock_handler_input
):
    from src.models.affirmative import Affirmative

    handler_input = _town_request(mock_handler_input, "swidon")
    store = User.snapshot(handler_input)
    store.update(
        {
            "onboardingStage": "await_location_confirm",
            "awaitingLocationConfirm": True,
            "pendingLocationConfirm": {
                "city": "Swindon",
                "locality": "Swindon",
                "countryCode": "GB",
                "latitude": 51.5558,
                "longitude": -1.7797,
            },
        }
    )
    handler_input.attributes_manager.request_attributes["_store"] = store
    sync = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(HearApiClient, "sync_listener", sync)
    await Affirmative(deps=ApplicationContainer())._confirm_location(handler_input, store)
    updated = User.snapshot(handler_input)
    assert updated["onboardingComplete"] is True
    assert updated["userCity"] == "Swindon"
    assert updated["locationSource"] == "manual"
    assert updated["awaitingCommunityPlayback"] is False
    assert updated["awaitingProfilePermission"] is True
    assert updated["_requiresReliableSave"] is True
    session = handler_input.attributes_manager.set_session_attributes.call_args.args[0]
    assert session["onboardingStage"] is None
    assert session["onboardingComplete"] is True
    assert session["awaitingLocationConfirm"] is False
    assert session.get("awaitingCommunityPlayback", False) is False
    assert session["userCity"] == "Swindon"
    spoken = handler_input.response_builder.speak.call_args.args[0]
    assert "I've set your location to Swindon" in spoken
    assert "share your name and email" in spoken
    sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_location_follow_up_survives_missing_persistence_in_same_session(
    monkeypatch, mock_handler_input
):
    from src.controllers.confirmation import YesIntentHandler
    from src.middleware.onboarding_gate import OnboardingGateHandler

    handler_input = _town_request(mock_handler_input, "yes")
    handler_input.response_builder = ResponseBuilder()
    handler_input.request_envelope.request.intent.name = "AMAZON.YesIntent"
    handler_input.attributes_manager.request_attributes["_store"] = {**StateSchema.DEFAULT_STORE}
    session = {
        "onboardingComplete": True,
        "awaitingCommunityPlayback": True,
        "userCity": "York",
        "locality": "York",
    }
    handler_input.attributes_manager.get_session_attributes = lambda: session
    handler_input.attributes_manager.set_session_attributes = lambda value: session.update(value)
    discover = AsyncMock(
        return_value={
            "failed": False,
            "results": [
                {
                    "contentId": "content-york",
                    "title": "York update",
                    "audioUrl": "https://cdn.hear.media/content-york.mp3",
                }
            ],
        }
    )
    play = AsyncMock(return_value={"response": "playing"})
    availability = AsyncMock(
        return_value={
            "failed": False,
            "page": 0,
            "total_pages": 1,
            "has_more": False,
            "organizations": [
                {"type": "organization", "id": "org-york", "name": "York Talking News"}
            ],
            "creators": [],
        }
    )
    monkeypatch.setattr(HearApiClient, "availability", availability)
    monkeypatch.setattr("src.models.affirmative.Search.discover_content_via_search", discover)
    monkeypatch.setattr("src.models.affirmative.Search.auto_play_first_from_search", play)
    assert OnboardingGateHandler(deps=ApplicationContainer()).can_handle(handler_input) is False
    response = await YesIntentHandler(deps=ApplicationContainer()).handle(handler_input)
    assert "I found York Talking News" in response["outputSpeech"]["ssml"]
    assert handler_input.attributes_manager.request_attributes["_nlp"]["slots"]["city"] == "York"
    assert session["awaitingCommunityPlayback"] is False
    availability.assert_awaited_once()
    discover.assert_not_awaited()
    play.assert_not_awaited()
