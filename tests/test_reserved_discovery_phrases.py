from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.alexa.runtime import AttrDict
from src.clients.resolver import ResolverClient
from src.constants.discovery import DiscoveryConstants
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.middleware.confirmation import ConfirmationMiddleware
from src.middleware.resolver import ResolverInterceptor
from src.models.affirmative import Affirmative
from src.models.decline import Decline
from src.models.play import PlayContent, PlayCreator, PlayOrganization
from src.models.resolver_workflow import ResolverWorkflow
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
async def test_carrierless_discovery_forwards_a_no_match_value_unchanged(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "CarrierlessDiscoveryIntent",
                "slots": {
                    "topic": {
                        "name": "topic",
                        "value": "latest sport in Swindon from TNF",
                        "resolutions": {
                            "resolutionsPerAuthority": [
                                {"status": {"code": "ER_SUCCESS_NO_MATCH"}}
                            ]
                        },
                    }
                },
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
            "intent": "general",
            "slots": {
                "category": "sport",
                "city": "Swindon",
                "organizationName": "Talking News Federation",
                "organizationIds": ["organization-tnf"],
                "residualQuery": "",
            },
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_awaited_once_with(
        "latest sport in Swindon from TNF",
        alexa_user_id="amzn1.ask.account.TEST",
        timeout_ms=5000,
    )
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "general"
    assert nlp["alexaRawIntent"] == "CarrierlessDiscoveryIntent"
    assert nlp["nlpMatchesAlexa"] is True
    assert nlp["needsRedirect"] is False


@pytest.mark.asyncio
async def test_carrierless_name_reply_respects_active_organization_dialog(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "CarrierlessDiscoveryIntent",
                "slots": {
                    "topic": {
                        "name": "topic",
                        "value": "Talking News Federation",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingOrganizationName": True,
        "activeDialog": {
            "type": "organization_name",
            "context": {"slotName": "organizationQuery"},
            "expiresAt": 4102444800,
        },
    }
    resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "organization",
            "slots": {
                "organizationName": "Talking News Federation",
                "organizationIds": ["organization-tnf"],
                "residualQuery": "",
            },
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_awaited_once_with(
        "play from Talking News Federation",
        alexa_user_id="amzn1.ask.account.TEST",
        timeout_ms=5000,
    )
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "organization"
    assert nlp["slots"]["organizationQuery"] == "Talking News Federation"
    assert nlp["slots"]["organizationFollowUp"] is True


@pytest.mark.asyncio
async def test_carrierless_town_reply_respects_active_onboarding(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "CarrierlessDiscoveryIntent",
                "slots": {"topic": {"name": "topic", "value": "Swindon"}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingStage": "ask_town",
        "activeDialog": {
            "type": "onboarding",
            "context": {"stage": "ask_town"},
            "expiresAt": 4102444800,
        },
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "town_capture"
    assert nlp["slots"] == {"townName": "Swindon", "placeName": "Swindon"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_kind", "expected_intent", "flag", "action_type"),
    [
        ("talking newspaper", "organization", "genericOrganizationRequest", PlayOrganization),
        ("creator", "creator", "genericCreatorRequest", PlayCreator),
        ("publication", "publication", "genericPublicationRequest", PlayContent),
    ],
)
async def test_generic_source_kind_stays_local_and_starts_typed_capture(
    monkeypatch,
    mock_handler_input,
    source_kind,
    expected_intent,
    flag,
    action_type,
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "ChooseSourceKindIntent",
                "slots": {
                    "sourceKind": {"name": "sourceKind", "value": source_kind}
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
    await action_type(deps=ApplicationContainer()).execute(mock_handler_input)

    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == expected_intent
    assert nlp["slots"][flag] is True
    assert User.snapshot(mock_handler_input)["activeDialog"]["type"] in {
        "organization_name",
        "creator_name",
        "publication_source",
    }


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
    assert nlp["searchPayload"]["limit"] == 3
    assert nlp["directDiscoveryRequest"] is True
    assert (
        mock_handler_input.attributes_manager.request_attributes.get("_pendingConfirmation") is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slot_name"),
    [
        ("WhatsTrendingIntent", "topic"),
        ("PlayRecommendationIntent", "recommendationQuery"),
    ],
)
async def test_topic_qualified_trending_resolves_topic_and_preserves_trending_semantics(
    monkeypatch, mock_handler_input, intent_name, slot_name
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": intent_name,
                "slots": {slot_name: {"name": slot_name, "value": "sport"}},
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
            "slots": {
                "category": "sport",
                "categorySlugs": ["sport"],
                "residualQuery": "",
                "searchPlan": {"query": "", "filter": {"categorySlugs": ["sport"]}},
            },
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_awaited_once_with(
        "play sport", alexa_user_id="amzn1.ask.account.TEST", timeout_ms=5000
    )
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "trending"
    assert nlp["nlpMatchesAlexa"] is True
    assert nlp["slots"]["category"] == "sport"
    assert nlp["slots"]["isRecommended"] is True
    assert nlp["slots"]["sort"] == "trending"
    assert nlp["slots"]["searchPlan"]["sort"] == "trending"
    assert nlp["searchPayload"]["sort"] == "trending"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "expected_intent", "expected_sort"),
    [
        ("BrowseContentIntent", "browse", "latest"),
        ("WhatsTrendingIntent", "trending", "trending"),
    ],
)
async def test_date_only_discovery_builds_date_filter_without_resolver_text(
    monkeypatch, mock_handler_input, intent_name, expected_intent, expected_sort
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": intent_name,
                "slots": {
                    "dateQuery": {"name": "dateQuery", "value": "2026-09-04"}
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
    assert nlp["intent"] == expected_intent
    assert nlp["searchPayload"]["sort"] == expected_sort
    assert set(nlp["searchPayload"]["filter"]) == {"publishedFrom", "publishedTo"}
    assert nlp["slots"]["searchPlan"]["filter"] == nlp["searchPayload"]["filter"]
    assert nlp["slots"]["temporalOriginal"] == "4 September 2026"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slot_name", "raw_name", "expected_utterance", "resolved_intent"),
    [
        (
            "PlayByOrganizationIntent",
            "organizationQuery",
            "New Voice Network",
            "play from New Voice Network",
            "organization",
        ),
        (
            "PlayByCreatorIntent",
            "creatorQuery",
            "New Speaker",
            "play something by New Speaker",
            "creator",
        ),
        (
            "PlayPublicationIntent",
            "publicationSourceQuery",
            "Dorking Talking Magazine",
            "play publication from Dorking Talking Magazine",
            "publication",
        ),
        (
            "SelectPublicationSourceIntent",
            "publicationSourceQuery",
            "Dorking Talking Magazine",
            "play publication from Dorking Talking Magazine",
            "publication",
        ),
    ],
)
async def test_out_of_catalog_source_name_still_reaches_backend_resolver(
    monkeypatch,
    mock_handler_input,
    intent_name,
    slot_name,
    raw_name,
    expected_utterance,
    resolved_intent,
):
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
                        "value": raw_name,
                        "resolutions": {
                            "resolutionsPerAuthority": [
                                {"status": {"code": "ER_SUCCESS_NO_MATCH"}}
                            ]
                        },
                    }
                },
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
            "intent": resolved_intent,
            "slots": {slot_name: raw_name},
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_awaited_once_with(
        expected_utterance,
        alexa_user_id="amzn1.ask.account.TEST",
        timeout_ms=5000,
    )
    assert mock_handler_input.attributes_manager.request_attributes["_nlp"]["intent"] == (
        resolved_intent
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slot_name", "raw_name", "expected_utterance", "resolved_intent"),
    [
        (
            "SearchContentIntent",
            "topic",
            "Dorking Talking Magazine",
            "play Dorking Talking Magazine",
            "organization",
        ),
        (
            "SearchCreatorIntent",
            "creatorQuery",
            "Unknown Speaker Collective",
            "play something by Unknown Speaker Collective",
            "creator",
        ),
        (
            "SearchOrganizationIntent",
            "organizationQuery",
            "Unknown Voice Network",
            "play from Unknown Voice Network",
            "organization",
        ),
        (
            "SearchPublicationIntent",
            "publicationSourceQuery",
            "Unknown Voice Magazine",
            "play publication from Unknown Voice Magazine",
            "publication",
        ),
    ],
)
async def test_domain_slot_preserves_full_name_and_relation(
    monkeypatch,
    mock_handler_input,
    intent_name,
    slot_name,
    raw_name,
    expected_utterance,
    resolved_intent,
):
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
                        "value": raw_name,
                    }
                },
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
            "intent": resolved_intent,
            "slots": {
                "residualQuery": "",
                f"{resolved_intent}Ids": [f"{resolved_intent}-1"],
                f"{resolved_intent}Name": raw_name,
            },
        }
    )
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    resolve.assert_awaited_once_with(
        expected_utterance,
        alexa_user_id="amzn1.ask.account.TEST",
        timeout_ms=5000,
    )
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == resolved_intent
    assert nlp["needsRedirect"] is (resolved_intent != DiscoveryConstants.ALEXA_TO_NLP[intent_name])


@pytest.mark.asyncio
async def test_topic_slot_rejects_different_catalog_source(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SearchContentIntent",
                "slots": {
                    "topic": {
                        "name": "topic",
                        "value": "Dorking Talking Magazine",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "general",
                "slots": {
                    "publicationIds": ["publication-orkney"],
                    "publicationName": "Orkney Talking Magazine",
                    "residualQuery": "August",
                },
                "entities": [
                    {
                        "type": "publication",
                        "id": "publication-orkney",
                        "canonicalValue": "Orkney Talking Magazine",
                    }
                ],
            }
        ),
    )

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "general"
    assert nlp["nlpMatchesAlexa"] is True
    assert nlp["needsRedirect"] is False
    assert nlp["entities"] == []
    assert nlp["slots"]["residualQuery"] == "Dorking Talking Magazine"
    assert nlp["slots"]["unresolvedReferences"] == [
        {
            "phrase": "Dorking Talking Magazine",
            "expectedTypes": ["creator", "organization", "publication"],
        }
    ]


@pytest.mark.asyncio
async def test_topic_slot_rejects_unverified_publication_source(
    monkeypatch, mock_handler_input
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SearchContentIntent",
                "slots": {
                    "topic": {
                        "name": "topic",
                        "value": "Dorking Talking Magazine",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(
            return_value={
                "status": "resolved",
                "intent": "publication",
                "slots": {
                    "publicationName": "Orkney Talking Magazine",
                    "publicationSourceQuery": "Dorking Talking Magazine",
                    "residualQuery": "Dorking Talking Magazine August",
                },
            }
        ),
    )

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "general"
    assert nlp["slots"]["residualQuery"] == "Dorking Talking Magazine"
    assert nlp["slots"]["unresolvedReferences"][0]["phrase"] == (
        "Dorking Talking Magazine"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "intent_name",
        "slot_name",
        "raw_name",
        "resolved_intent",
        "name_slot",
        "id_slot",
        "canonical",
    ),
    [
        (
            "SearchOrganizationIntent",
            "organizationQuery",
            "Tyndale Talking News",
            "organization",
            "organizationName",
            "organizationIds",
            "Tynedale Talking Newspaper",
        ),
        (
            "SearchCreatorIntent",
            "creatorQuery",
            "John Smyth",
            "creator",
            "creatorName",
            "creatorIds",
            "John Smith",
        ),
    ],
)
async def test_domain_slot_accepts_close_source_name(
    monkeypatch,
    mock_handler_input,
    intent_name,
    slot_name,
    raw_name,
    resolved_intent,
    name_slot,
    id_slot,
    canonical,
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": intent_name,
                "slots": {slot_name: {"name": slot_name, "value": raw_name}},
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(
            return_value={
                "status": "resolved",
                "intent": resolved_intent,
                "slots": {id_slot: ["source-1"], name_slot: canonical},
            }
        ),
    )

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == resolved_intent
    assert nlp["slots"][id_slot] == ["source-1"]
    assert "unresolvedReferences" not in nlp["slots"]


def test_domain_slot_accepts_confident_resolver_alias():
    result = {
        "status": "resolved",
        "intent": "organization",
        "slots": {
            "organizationIds": ["organization-tnf"],
            "organizationName": "Talking News Federation",
            "residualQuery": "",
        },
        "entities": [
            {
                "entityType": "organization",
                "entityId": "organization-tnf",
                "canonicalValue": "Talking News Federation",
                "originalText": "tnf",
                "confidence": 98,
                "method": "bare_match",
            }
        ],
        "ambiguities": [],
    }

    constrained = ResolverWorkflow.apply_alexa_constraints(
        result,
        "SearchContentIntent",
        {"topic": {"name": "topic", "value": "tnf"}},
    )

    assert constrained["intent"] == "organization"
    assert constrained["slots"]["organizationIds"] == ["organization-tnf"]
    assert "unresolvedReferences" not in constrained["slots"]


@pytest.mark.asyncio
async def test_creator_slot_preserves_actionable_creator_ambiguity(
    monkeypatch, mock_handler_input
):
    candidates = [
        {
            "type": "creator",
            "id": f"creator-{index}",
            "name": name,
        }
        for index, name in enumerate(
            (
                "Pendle Voice Dalesman",
                "Pendle Voice Lancashire Life",
                "Pendle Voice Leader and Times",
                "Pendle Voice Sunday People",
                "Pendle Voice Woman's Weekly",
                "Pendle Voice Yorkshire Life",
            ),
            start=1,
        )
    ]
    reference = {"phrase": "pendu voice", "candidates": candidates}
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "SearchCreatorIntent",
                "slots": {
                    "creatorQuery": {
                        "name": "creatorQuery",
                        "value": "pendu voice",
                    }
                },
            },
        }
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(
            return_value={
                "status": "ambiguous",
                "intent": "creator",
                "slots": {
                    "residualQuery": "",
                    "ambiguousReferences": [reference],
                    "unresolvedReferences": [],
                    "searchPlan": {"query": "", "filter": {}},
                },
                "entities": [],
                "ambiguities": [reference],
            }
        ),
    )

    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)

    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["status"] == "ambiguous"
    assert nlp["intent"] == "creator"
    assert nlp["ambiguities"] == [reference]
    assert nlp["slots"]["ambiguousReferences"] == [reference]
    assert nlp["slots"]["unresolvedReferences"] == []

    await PlayCreator(deps=ApplicationContainer()).execute(mock_handler_input)

    store = User.snapshot(mock_handler_input)
    speech = mock_handler_input.response_builder.speak.call_args.args[0]
    assert store["activeDialog"]["type"] == "ambiguity"
    assert store["pendingAmbiguity"]["candidates"] == candidates
    assert "matches beginning Pendle Voice" in speech
    assert "First, Dalesman" in speech
    assert "Second, Lancashire Life" in speech
    assert "Third, Leader and Times" in speech
    assert "couldn't find" not in speech
    directive = mock_handler_input.response_builder.add_directive.call_args.args[0]
    assert directive["type"] == "Dialog.UpdateDynamicEntities"


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
