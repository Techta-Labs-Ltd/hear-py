from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.clients.resolver import ResolverClient
from src.middleware.confirmation import ConfirmationMiddleware
from src.middleware.resolver import ResolverInterceptor
from src.runtime import AttrDict
from src.services.store import DEFAULT_STORE
from src.utils.discovery_request import is_reserved_discovery_phrase


@pytest.mark.parametrize("phrase", [
    "anything",
    "something",
    "whatever",
    "play audio",
    "play me something",
    "give me something to listen to",
    "start listening",
    "let me listen",
    "find",
    "find me",
    "search",
    "search for something",
])
def test_generic_discovery_phrases_are_reserved(phrase):
    assert is_reserved_discovery_phrase(phrase)


@pytest.mark.parametrize("phrase", [
    "news",
    "York TN",
    "Gloucester Talking Newspaper",
    "local sport",
])
def test_meaningful_discovery_phrases_are_not_reserved(phrase):
    assert not is_reserved_discovery_phrase(phrase)


@pytest.mark.asyncio
async def test_reserved_anything_never_calls_resolver(monkeypatch, mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayContentIntent",
            "slots": {
                "topic": {"name": "topic", "value": "anything"},
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor().process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)

    resolve.assert_not_awaited()
    attrs = mock_handler_input.attributes_manager.request_attributes
    assert attrs["_nlp"]["localResolved"] is True
    assert attrs["_nlp"]["searchPayload"] == {"query": "", "filter": {}}
    assert attrs["_resolverClarification"]["reprompt"] == (
        "What would you like to play?"
    )


@pytest.mark.asyncio
async def test_meaningful_news_still_calls_resolver(monkeypatch, mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayContentIntent",
            "slots": {"topic": {"name": "topic", "value": "news"}},
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock(return_value={
        "status": "resolved",
        "intent": "category",
        "slots": {"category": "news", "residualQuery": ""},
        "ambiguities": [],
    })
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor().process(mock_handler_input)

    resolve.assert_awaited_once_with(
        "news",
        alexa_user_id="amzn1.ask.account.TEST",
    )


@pytest.mark.asyncio
async def test_elicited_pendle_voice_follow_up_reaches_resolver(
    monkeypatch,
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayContentIntent",
            "slots": {"topic": {"name": "topic", "value": "Pendle Voice"}},
        },
    })
    mock_handler_input.attributes_manager.request_attributes = {
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
    }
    resolve = AsyncMock(return_value={
        "status": "ambiguous",
        "intent": "search",
        "slots": {"residualQuery": ""},
        "searchPayload": {"query": "", "filter": {}},
        "ambiguities": [{
            "phrase": "pendle voice",
            "candidates": [{
                "type": "creator",
                "id": "creator-leader",
                "name": "Pendle Voice Leader and Times",
            }, {
                "type": "creator",
                "id": "creator-dalesman",
                "name": "Pendle Voice Dalesman",
            }],
        }],
    })
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor().process(mock_handler_input)

    resolve.assert_awaited_once_with(
        "Pendle Voice",
        alexa_user_id="amzn1.ask.account.TEST",
    )
    assert mock_handler_input.attributes_manager.request_attributes["_nlp"][
        "status"
    ] == "ambiguous"


@pytest.mark.asyncio
@pytest.mark.parametrize(("intent_name", "canonical"), [
    ("BrowseContentIntent", "what's new"),
    ("WhatsTrendingIntent", "what's trending"),
    ("PlayLocalIntent", "play local content"),
    ("PlayRecommendationIntent", "recommend something"),
])
async def test_zero_slot_discovery_uses_canonical_resolver_utterance(
    monkeypatch,
    mock_handler_input,
    intent_name,
    canonical,
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {"name": intent_name, "slots": {}},
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock(return_value={
        "status": "resolved",
        "intent": "search",
        "confirmationLabel": canonical,
        "searchPayload": {"query": canonical, "filter": {}},
        "slots": {"residualQuery": canonical},
        "ambiguities": [],
    })
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor().process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)

    resolve.assert_awaited_once_with(
        canonical,
        alexa_user_id="amzn1.ask.account.TEST",
    )
    assert mock_handler_input.attributes_manager.request_attributes.get(
        "_pendingConfirmation"
    )
