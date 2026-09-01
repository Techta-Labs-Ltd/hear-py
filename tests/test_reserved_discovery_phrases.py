from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.alexa.runtime import AttrDict
from src.clients.resolver import ResolverClient
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.middleware.confirmation import ConfirmationMiddleware
from src.middleware.resolver import ResolverInterceptor
from src.models.affirmative import Affirmative
from src.models.decline import Decline
from src.models.play import PlayOrganization
from src.models.user import User
from src.utils.filters import SearchFilterUtils


@pytest.mark.parametrize(
    "phrase",
    [
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
    ],
)
def test_generic_discovery_phrases_are_reserved(phrase):
    assert SearchFilterUtils.is_reserved_discovery_phrase(phrase)


@pytest.mark.parametrize(
    "phrase", ["news", "York TN", "Gloucester Talking Newspaper", "local sport"]
)
def test_meaningful_discovery_phrases_are_not_reserved(phrase):
    assert not SearchFilterUtils.is_reserved_discovery_phrase(phrase)


@pytest.mark.parametrize(
    "phrase",
    [
        "talking newspaper",
        "play from a talking news paper",
        "play from a talking a talking newspaper",
        "play something from the talking talking newspaper",
        "play from an audio newspaper",
        "play from talking news",
    ],
)
def test_generic_talking_newspaper_phrases_need_a_name(phrase):
    assert SearchFilterUtils.is_generic_organization_request(phrase)


@pytest.mark.parametrize(
    "phrase",
    ["Pendle Voice", "York Talking Newspaper", "play from Andover Talking Newspaper"],
)
def test_named_talking_newspapers_are_not_generic(phrase):
    assert not SearchFilterUtils.is_generic_organization_request(phrase)


@pytest.mark.parametrize("phrase", ["talking", "news paper", "newspaper", "paper"])
def test_underspecified_organization_phrases_need_a_name(phrase):
    assert SearchFilterUtils.organization_request_kind(phrase, organization_intent=True) == "generic"


@pytest.mark.parametrize(
    "phrase",
    ["top English paper", "play from top English paper", "talk English paper"],
)
def test_known_talking_newspaper_asr_corruptions_need_targeted_repair(phrase):
    assert SearchFilterUtils.organization_request_kind(phrase, organization_intent=True) == "repair"


@pytest.mark.parametrize("phrase", ["Mole Valley Talking", "York Talking News", "TNF"])
def test_specific_organization_names_are_preserved(phrase):
    assert SearchFilterUtils.organization_request_kind(phrase, organization_intent=True) == "specific"


@pytest.mark.asyncio
async def test_reserved_anything_never_calls_resolver(monkeypatch, mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "anything"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    resolve.assert_not_awaited()
    attrs = mock_handler_input.attributes_manager.request_attributes
    assert attrs["_nlp"]["localResolved"] is True
    assert attrs["_nlp"]["searchPayload"] == {"query": "", "filter": {}}
    assert attrs["_resolverClarification"]["reprompt"] == "Please say your request again."
    assert "elicitSlot" not in attrs["_resolverClarification"]


@pytest.mark.asyncio
async def test_meaningful_news_still_calls_resolver(monkeypatch, mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "news"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "category",
            "slots": {"category": "news", "residualQuery": ""},
            "ambiguities": [],
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    resolve.assert_awaited_once_with(
        "play news", alexa_user_id="amzn1.ask.account.TEST", timeout_ms=5000
    )


@pytest.mark.asyncio
async def test_truncated_talking_organization_request_never_reaches_resolver(
    monkeypatch, mock_handler_input
):
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
                        "value": "talking",
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

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "organization"
    assert nlp["slots"]["genericOrganizationRequest"] is True
    assert "talkingNewspaperRepairCandidate" not in nlp["slots"]


@pytest.mark.asyncio
async def test_talking_newspaper_asr_corruption_uses_targeted_repair_without_resolver(
    monkeypatch, mock_handler_input
):
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
                        "value": "top English paper",
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

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    await PlayOrganization(deps=ApplicationContainer()).execute(mock_handler_input)

    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["slots"]["genericOrganizationRequest"] is True
    assert nlp["slots"]["talkingNewspaperRepairCandidate"] is True
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "Did you mean a talking newspaper" in spoken
    assert "top English paper" not in spoken
    active = User.snapshot(mock_handler_input)["activeDialog"]
    assert active["type"] == "asr_repair"


@pytest.mark.asyncio
async def test_accepting_talking_newspaper_asr_repair_asks_for_the_source_name(
    mock_handler_input,
):
    mock_handler_input.attributes_manager.get_session_attributes.return_value = {}
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "activeDialog": {
            "type": "asr_repair",
            "context": {"repair": "talking_newspaper"},
            "expiresAt": 4102444800,
        },
    }

    await Affirmative(deps=ApplicationContainer()).execute(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "Which talking newspaper would you like" in spoken
    active = User.snapshot(mock_handler_input)["activeDialog"]
    assert active["type"] == "organization_name"


@pytest.mark.asyncio
async def test_declining_talking_newspaper_asr_repair_clears_the_dialog(mock_handler_input):
    mock_handler_input.attributes_manager.get_session_attributes.return_value = {}
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "activeDialog": {
            "type": "asr_repair",
            "context": {"repair": "talking_newspaper"},
            "expiresAt": 4102444800,
        },
    }

    await Decline(deps=ApplicationContainer()).execute(mock_handler_input)

    assert User.snapshot(mock_handler_input)["activeDialog"] is None
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "What would you like to listen to" in spoken


@pytest.mark.asyncio
async def test_repaired_source_name_follow_up_is_forced_to_organization_resolution(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "Mole Valley Talking"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "activeDialog": {
            "type": "organization_name",
            "context": {"sourceKind": "talking_newspaper"},
            "expiresAt": 4102444800,
        },
    }
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "organization",
            "slots": {
                "organizationIds": ["org-mole-valley"],
                "organizationName": "Mole Valley Talking",
                "residualQuery": "",
            },
            "ambiguities": [],
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_awaited_once_with(
        "play from Mole Valley Talking",
        alexa_user_id="amzn1.ask.account.TEST",
        timeout_ms=5000,
    )
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "organization"
    assert nlp["slots"]["organizationIds"] == ["org-mole-valley"]
    assert User.snapshot(mock_handler_input)["activeDialog"] is None


@pytest.mark.asyncio
async def test_elicited_pendle_voice_follow_up_reaches_resolver(monkeypatch, mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "Pendle Voice"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
    }
    resolve = AsyncMock(
        return_value={
            "status": "ambiguous",
            "intent": "search",
            "slots": {"residualQuery": ""},
            "searchPayload": {"query": "", "filter": {}},
            "ambiguities": [
                {
                    "phrase": "pendle voice",
                    "candidates": [
                        {
                            "type": "creator",
                            "id": "creator-leader",
                            "name": "Pendle Voice Leader and Times",
                        },
                        {
                            "type": "creator",
                            "id": "creator-dalesman",
                            "name": "Pendle Voice Dalesman",
                        },
                    ],
                }
            ],
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    resolve.assert_awaited_once_with(
        "play Pendle Voice", alexa_user_id="amzn1.ask.account.TEST", timeout_ms=5000
    )
    assert mock_handler_input.attributes_manager.request_attributes["_nlp"]["status"] == "ambiguous"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "expected_intent", "expected_sort"),
    [
        ("WhatsTrendingIntent", "trending", "trending"),
        ("PlayRecommendationIntent", "trending", "trending"),
        ("BrowseContentIntent", "browse", "latest"),
        ("PlayLocalIntent", "local", "latest"),
    ],
)
async def test_complete_zero_slot_discovery_stays_out_of_resolver(
    monkeypatch, mock_handler_input, intent_name, expected_intent, expected_sort
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": intent_name, "slots": {}},
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == expected_intent
    assert nlp["searchPayload"]["sort"] == expected_sort
    assert nlp["directDiscoveryRequest"] is True
    assert (
        mock_handler_input.attributes_manager.request_attributes.get("_pendingConfirmation") is None
    )


@pytest.mark.asyncio
async def test_misrouted_local_community_phrase_is_redirected_without_resolver(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayByCreatorIntent",
                "slots": {"creatorQuery": {"name": "creatorQuery", "value": "my local community"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "local"
    assert nlp["needsRedirect"] is True
