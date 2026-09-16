from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.alexa.dialog import DialogStateManager
from src.alexa.resolver_runner import ResolverWorkflowRunner
from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.container import ApplicationContainer
from src.controllers.intent_dispatch import IntentDispatchGateHandler
from src.models.user import User


@pytest.fixture
def base_envelope():
    return AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "PlayContentIntent",
                    "slots": {"topic": {"name": "topic", "value": "play pendle voice"}},
                },
            },
        }
    )


@pytest.fixture
def mock_handler_input(base_envelope):
    attributes = AttributesManager(base_envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    return HandlerInput(base_envelope, attributes, None, ResponseBuilder())


def test_ambiguity_response_activates_dialog_and_injects_dynamic_entities(mock_handler_input):
    candidates = [
        {"id": "feed-1", "name": "Pendle Voice News", "entityType": "publication"},
        {"id": "feed-2", "name": "Pendle Voice Magazine", "entityType": "publication"},
    ]
    nlp_data = {
        "status": "ambiguous",
        "intent": "search",
        "ambiguities": [{"phrase": "pendle voice", "candidates": candidates}],
        "slots": {},
    }
    mock_handler_input.attributes_manager.request_attributes["_nlp"] = nlp_data

    container = ApplicationContainer()
    dispatcher = container.build_request_intent_dispatcher(mock_handler_input)
    assert dispatcher.can_dispatch(mock_handler_input) is True

    gate = IntentDispatchGateHandler(container.build_request_intent_dispatcher(mock_handler_input))
    assert gate.can_handle(mock_handler_input) is True

    response = gate.handle(mock_handler_input)
    assert "outputSpeech" in response
    speech = response["outputSpeech"]["ssml"]
    assert "Pendle Voice" in speech
    assert "News" in speech
    assert "Magazine" in speech

    store = User.snapshot(mock_handler_input)
    assert store.get("pendingAmbiguity") is not None
    assert store["pendingAmbiguity"]["phrase"] == "pendle voice"
    assert len(store["pendingAmbiguity"]["candidates"]) == 2

    active_dialog = DialogStateManager.get_active(mock_handler_input)
    assert active_dialog is not None
    assert active_dialog.get("type") == "ambiguity"

    directives = response.get("directives") or []
    assert len(directives) == 1
    assert directives[0]["type"] == "Dialog.UpdateDynamicEntities"


@pytest.mark.asyncio
async def test_location_intent_dispatches_to_availability_local(mock_handler_input):
    nlp_data = {
        "status": "resolved",
        "intent": "location",
        "slots": {"city": "Leeds"},
    }
    mock_handler_input.attributes_manager.request_attributes["_nlp"] = nlp_data

    availability = AsyncMock()
    availability.begin_local = AsyncMock(return_value={"outputSpeech": "local"})
    container = ApplicationContainer(request_availability=availability)

    dispatcher = container.build_request_intent_dispatcher(mock_handler_input)
    assert dispatcher.can_dispatch(mock_handler_input) is True

    result = dispatcher.dispatch(mock_handler_input)
    response = await result
    assert response == {"outputSpeech": "local"}
    availability.begin_local.assert_called_once_with(mock_handler_input, nlp_data)


def test_availability_preemption_on_new_search_query(mock_handler_input):
    DialogStateManager.activate(
        mock_handler_input,
        "availability",
        context={
            "kind": "source",
            "candidates": [{"id": "item-1", "name": "York News"}],
        },
    )
    active = DialogStateManager.get_active(mock_handler_input)
    assert active is not None
    assert active.get("type") == "availability"

    context = ResolverWorkflowRunner._request(mock_handler_input)
    assert context is not None
    assert context["alexa_intent"] == "PlayContentIntent"

    cleared = DialogStateManager.get_active(mock_handler_input)
    assert cleared is None


def test_availability_dialog_retains_ordinal_selection(base_envelope):
    base_envelope.request.intent.name = "PlayContentIntent"
    base_envelope.request.intent.slots = {"topic": {"name": "topic", "value": "the first one"}}
    attributes = AttributesManager(base_envelope)
    attributes.request_attributes = {
        "_store": {"onboardingComplete": True},
        "_dirty": False,
    }
    handler_input = HandlerInput(base_envelope, attributes, None, ResponseBuilder())
    DialogStateManager.activate(
        handler_input,
        "availability",
        context={
            "kind": "source",
            "candidates": [{"id": "item-1", "name": "York News"}],
        },
    )

    context = ResolverWorkflowRunner._request(handler_input)
    assert context is None

    active = DialogStateManager.get_active(handler_input)
    assert active is not None
    assert active.get("type") == "availability"


def test_resolver_workflow_runner_carries_alexa_user_id_and_listener_id():
    container = ApplicationContainer()
    runner = ResolverWorkflowRunner(
        alexa_user_id="custom-alexa-user",
        listener_id="custom-listener-id",
        progressive=container.progressive,
        resolver=container.resolver,
        user=container.user,
    )
    assert runner._alexa_user_id == "custom-alexa-user"
    assert runner._listener_id == "custom-listener-id"


@pytest.mark.asyncio
async def test_resolver_interceptor_injects_user_and_listener_id(mock_handler_input, monkeypatch):
    captured = {}

    def capture_init(
        self,
        *,
        alexa_user_id=None,
        listener_id=None,
        progressive,
        resolver,
        user,
    ):
        captured["alexa_user_id"] = alexa_user_id
        captured["listener_id"] = listener_id
        captured["progressive"] = progressive
        captured["resolver"] = resolver
        captured["user"] = user
        self._alexa_user_id = alexa_user_id
        self._listener_id = listener_id

    monkeypatch.setattr(ResolverWorkflowRunner, "__init__", capture_init)
    monkeypatch.setattr(ResolverWorkflowRunner, "apply", AsyncMock())

    interceptor = ApplicationContainer().build_resolver_interceptor()
    await interceptor.process(mock_handler_input)

    assert captured["alexa_user_id"] == "test-alexa-user-123"
    assert captured["listener_id"] == "test-listener-456"
    assert captured["user"] is interceptor._user

@pytest.mark.asyncio
async def test_ambiguity_turn_2_ordinal_selection_resolves_candidate(mock_handler_input):
    candidates = [
        {"id": "creator-1", "name": "Pendle Voice Dalesman", "type": "creator"},
        {"id": "creator-2", "name": "Pendle Voice Lancashire Life", "type": "creator"},
        {"id": "creator-3", "name": "Pendle Voice Leader and Times", "type": "creator"},
    ]
    nlp_data = {
        "status": "ambiguous",
        "intent": "creator",
        "ambiguities": [{"phrase": "pendle voice", "candidates": candidates}],
        "slots": {},
    }
    mock_handler_input.attributes_manager.request_attributes["_nlp"] = nlp_data
    container = ApplicationContainer()
    gate = IntentDispatchGateHandler(container.build_request_intent_dispatcher(mock_handler_input))
    turn1_res = gate.handle(mock_handler_input)
    assert "outputSpeech" in turn1_res

    store = User.snapshot(mock_handler_input)
    assert store.get("pendingAmbiguity") is not None
    assert store["pendingAmbiguity"]["expiresAt"] > 0

    envelope2 = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "ClarifySelectionIntent",
                    "slots": {"selection": {"name": "selection", "value": "second"}},
                },
            },
        }
    )
    attributes2 = AttributesManager(envelope2)
    attributes2.request_attributes = {
        "_store": dict(store),
        "_dirty": False,
    }
    hi2 = HandlerInput(envelope2, attributes2, None, ResponseBuilder())

    await container.build_resolver_interceptor().process(hi2)
    nlp2 = hi2.attributes_manager.request_attributes.get("_nlp")
    assert nlp2 is not None
    assert nlp2["status"] == "resolved"
    assert nlp2["intent"] == "creator"
    assert nlp2["slots"]["creatorIds"] == ["creator-2"]
    assert nlp2["slots"]["creatorName"] == "Pendle Voice Lancashire Life"
    assert User.snapshot(hi2).get("pendingAmbiguity") is None

@pytest.mark.asyncio
async def test_ambiguity_turn_2_distinguishing_name_resolves_candidate(mock_handler_input):
    candidates = [
        {"id": "creator-1", "name": "Pendle Voice Dalesman", "type": "creator"},
        {"id": "creator-2", "name": "Pendle Voice Lancashire Life", "type": "creator"},
        {"id": "creator-3", "name": "Pendle Voice Leader and Times", "type": "creator"},
    ]
    nlp_data = {
        "status": "ambiguous",
        "intent": "creator",
        "ambiguities": [{"phrase": "pendle voice", "candidates": candidates}],
        "slots": {},
    }
    mock_handler_input.attributes_manager.request_attributes["_nlp"] = nlp_data
    container = ApplicationContainer()
    gate = IntentDispatchGateHandler(container.build_request_intent_dispatcher(mock_handler_input))
    gate.handle(mock_handler_input)
    store = User.snapshot(mock_handler_input)

    envelope2 = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "PlayContentIntent",
                    "slots": {"topic": {"name": "topic", "value": "play dalesman"}},
                },
            },
        }
    )
    attributes2 = AttributesManager(envelope2)
    attributes2.request_attributes = {
        "_store": dict(store),
        "_dirty": False,
    }
    hi2 = HandlerInput(envelope2, attributes2, None, ResponseBuilder())

    await container.build_resolver_interceptor().process(hi2)
    nlp2 = hi2.attributes_manager.request_attributes.get("_nlp")
    assert nlp2 is not None
    assert nlp2["status"] == "resolved"
    assert nlp2["intent"] == "creator"
    assert nlp2["slots"]["creatorIds"] == ["creator-1"]
    assert nlp2["slots"]["creatorName"] == "Pendle Voice Dalesman"
    assert User.snapshot(hi2).get("pendingAmbiguity") is None


@pytest.mark.asyncio
async def test_ambiguity_turn_2_dismissal_phrase_clears_ambiguity_and_returns_to_search(mock_handler_input):
    candidates = [
        {"id": "creator-1", "name": "Pendle Voice Dalesman", "type": "creator"},
        {"id": "creator-2", "name": "Pendle Voice Lancashire Life", "type": "creator"},
        {"id": "creator-3", "name": "Pendle Voice Leader and Times", "type": "creator"},
    ]
    nlp_data = {
        "status": "ambiguous",
        "intent": "creator",
        "ambiguities": [{"phrase": "pendle voice", "candidates": candidates}],
        "slots": {},
    }
    mock_handler_input.attributes_manager.request_attributes["_nlp"] = nlp_data
    container = ApplicationContainer()
    gate = IntentDispatchGateHandler(container.build_request_intent_dispatcher(mock_handler_input))
    gate.handle(mock_handler_input)
    store = User.snapshot(mock_handler_input)

    for phrase in ("another thing else", "something else", "none of these"):
        envelope2 = AttrDict(
            {
                "version": "1.0",
                "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
                "request": {
                    "type": "IntentRequest",
                    "locale": "en-GB",
                    "intent": {
                        "name": "ClarifySelectionIntent",
                        "slots": {"selection": {"name": "selection", "value": phrase}},
                    },
                },
            }
        )
        attributes2 = AttributesManager(envelope2)
        attributes2.request_attributes = {
            "_store": dict(store),
            "_dirty": False,
        }
        hi2 = HandlerInput(envelope2, attributes2, None, ResponseBuilder())

        await container.build_resolver_interceptor().process(hi2)
        nlp2 = hi2.attributes_manager.request_attributes.get("_nlp")
        assert nlp2 is not None
        assert nlp2["intent"] == "dismiss_choices"
        assert User.snapshot(hi2).get("pendingAmbiguity") is None
        assert gate.can_handle(hi2) is True
        res = gate.handle(hi2)
        speech = res["outputSpeech"]["ssml"]
        assert "What would you like to listen to instead" in speech


@pytest.mark.asyncio
async def test_play_from_creator_elicits_city_then_forwards_unmatched_spoken_words_to_resolver():
    from src.middleware.confirmation import ConfirmationMiddleware
    from src.middleware.dialog_validation import DialogValidationInterceptor

    envelope1 = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "SearchContentIntent",
                    "slots": {
                        "searchQuery": {
                            "name": "searchQuery",
                            "value": "play from a creator",
                            "confirmationStatus": "NONE",
                        }
                    },
                },
            },
        }
    )
    attributes1 = AttributesManager(envelope1)
    attributes1.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi1 = HandlerInput(envelope1, attributes1, None, ResponseBuilder())
    resolver = AsyncMock()
    resolver.resolve_utterance = AsyncMock()
    progressive = AsyncMock()
    progressive.send = AsyncMock(return_value=True)
    container = ApplicationContainer(resolver=resolver, progressive=progressive)

    await DialogValidationInterceptor().process(hi1)
    await container.build_resolver_interceptor().process(hi1)
    await ConfirmationMiddleware().process(hi1)
    gate = IntentDispatchGateHandler(container.build_request_intent_dispatcher(hi1))
    assert gate.can_handle(hi1) is True
    res1 = await gate.handle(hi1)

    assert "Which city would you like me to find creators in" in res1["outputSpeech"]["ssml"]
    assert res1["directives"] == [DialogStateManager.capture_directive("creator_location")]
    assert resolver.resolve_utterance.call_count == 0

    store1 = User.snapshot(hi1)
    assert store1["activeDialog"]["type"] == "creator_location"

    envelope2 = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "SelectCreatorCityIntent",
                    "slots": {
                        "cityQuery": {
                            "name": "cityQuery",
                            "value": "Sevenoaks",
                            "confirmationStatus": "NONE",
                            "resolutions": {
                                "resolutionsPerAuthority": [
                                    {
                                        "status": {"code": "ER_SUCCESS_NO_MATCH"},
                                        "authority": "amzn1.er-authority.echo-sdk.1",
                                    }
                                ]
                            },
                        }
                    },
                },
            },
        }
    )
    attributes2 = AttributesManager(envelope2)
    attributes2.request_attributes = {
        "_store": dict(store1),
        "_dirty": False,
    }
    hi2 = HandlerInput(envelope2, attributes2, None, ResponseBuilder())
    resolver.resolve_utterance = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "search",
            "slots": {"city": "Sevenoaks"},
            "searchPayload": {"query": "", "filter": {"city": "Sevenoaks"}},
            "resolution": {
                "match": {
                    "city": "Sevenoaks",
                    "countryCode": "gb",
                    "latitude": 51.27,
                    "longitude": 0.19,
                }
            },
        }
    )

    await DialogValidationInterceptor().process(hi2)
    await container.build_resolver_interceptor().process(hi2)

    resolver.resolve_utterance.assert_awaited_once()
    call_args = resolver.resolve_utterance.await_args
    assert call_args.args == ("Sevenoaks",)
    assert call_args.kwargs["prefer_location"] is True
    nlp2 = hi2.attributes_manager.request_attributes.get("_nlp")
    assert nlp2["intent"] == "creator_location"
    assert nlp2["slots"]["city"] == "Sevenoaks"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_name", "slot_name", "spoken_text", "expected_carrier_utterance"),
    [
        ("SearchContentIntent", "searchQuery", "unknown creator", "play unknown creator"),
        ("SearchCreatorIntent", "searchQuery", "David Beard", "play something by David Beard"),
        ("SearchOrganizationIntent", "searchQuery", "Pendle Audio", "play from Pendle Audio"),
        ("SearchPublicationIntent", "searchQuery", "Lancashire Life", "play publication from Lancashire Life"),
        ("PlayContentIntent", "topic", "astronomy today", "play astronomy today"),
        ("PlayByOrganizationIntent", "organizationQuery", "Ribble Valley TN", "play from Ribble Valley TN"),
        ("PlayPublicationIntent", "publicationSourceQuery", "Craven Herald", "play publication from Craven Herald"),
        ("PlayLocalIntent", "localQuery", "Barrow-in-Furness", "play near Barrow-in-Furness"),
        ("PlayRecommendationIntent", "recommendationQuery", "indie jazz", "play indie jazz"),
        ("SelectOrganizationIntent", "organizationQuery", "Colne TN", "play Colne TN"),
        ("SelectPublicationSourceIntent", "publicationSourceQuery", "Yorkshire Post", "play Yorkshire Post"),
        ("SelectCreatorCityIntent", "cityQuery", "Hebden Bridge", "Hebden Bridge"),
        ("BrowseByCategoryIntent", "category", "gardening", "play gardening"),
        ("WhatsTrendingIntent", "topic", "premier league", "play premier league"),
    ],
)
async def test_all_search_slots_forward_unmatched_spoken_words_to_resolver(
    intent_name, slot_name, spoken_text, expected_carrier_utterance
):
    from src.middleware.dialog_validation import DialogValidationInterceptor

    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": intent_name,
                    "slots": {
                        slot_name: {
                            "name": slot_name,
                            "value": spoken_text,
                            "confirmationStatus": "NONE",
                            "resolutions": {
                                "resolutionsPerAuthority": [
                                    {
                                        "status": {"code": "ER_SUCCESS_NO_MATCH"},
                                        "authority": "amzn1.er-authority.echo-sdk.1",
                                    }
                                ]
                            },
                        }
                    },
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    resolver = AsyncMock()
    resolver.resolve_utterance = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "search",
            "slots": {},
            "searchPayload": {"query": spoken_text, "filter": {}},
        }
    )
    progressive = AsyncMock()
    progressive.send = AsyncMock(return_value=True)
    container = ApplicationContainer(resolver=resolver, progressive=progressive)

    await DialogValidationInterceptor().process(hi)
    await container.build_resolver_interceptor().process(hi)

    resolver.resolve_utterance.assert_awaited_once()
    called_utterance = resolver.resolve_utterance.await_args.args[0]
    assert called_utterance == expected_carrier_utterance


@pytest.mark.asyncio
async def test_user_idle_no_does_not_trigger_search_confirmation():
    from src.alexa.context import RequestContext
    from src.middleware.confirmation import ConfirmationMiddleware
    from src.middleware.dialog_validation import DialogValidationInterceptor

    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "OpenDiscoveryIntent",
                    "slots": {
                        "searchQuery": {
                            "name": "searchQuery",
                            "value": "no",
                            "confirmationStatus": "NONE",
                        }
                    },
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    resolver = AsyncMock()
    progressive = AsyncMock(send=AsyncMock(return_value=True))
    container = ApplicationContainer(resolver=resolver, progressive=progressive)

    await DialogValidationInterceptor().process(hi)
    await container.build_resolver_interceptor().process(hi)
    await ConfirmationMiddleware().process(hi)

    assert resolver.resolve_utterance.call_count == 0
    assert RequestContext.request(hi).get("_pendingConfirmation") is None

    gate = IntentDispatchGateHandler(container.build_request_intent_dispatcher(hi))
    assert gate.can_handle(hi) is True
    res = gate.handle(hi)
    assert "Please say the name of a talking newspaper, creator, publication, or city" in res["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_user_idle_stop_speaks_goodbye_and_ends_session():
    from src.middleware.confirmation import ConfirmationMiddleware
    from src.middleware.dialog_validation import DialogValidationInterceptor

    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "OpenDiscoveryIntent",
                    "slots": {
                        "searchQuery": {
                            "name": "searchQuery",
                            "value": "stop",
                            "confirmationStatus": "NONE",
                        }
                    },
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    resolver = AsyncMock()
    progressive = AsyncMock(send=AsyncMock(return_value=True))
    container = ApplicationContainer(resolver=resolver, progressive=progressive)

    await DialogValidationInterceptor().process(hi)
    await container.build_resolver_interceptor().process(hi)
    await ConfirmationMiddleware().process(hi)

    assert resolver.resolve_utterance.call_count == 0
    gate = IntentDispatchGateHandler(container.build_request_intent_dispatcher(hi))
    assert gate.can_handle(hi) is True
    res = gate.handle(hi)
    assert "Goodbye" in res["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_direct_creator_city_query_routes_to_creator_location_without_generic_confirmation():
    from src.alexa.context import RequestContext
    from src.middleware.confirmation import ConfirmationMiddleware
    from src.middleware.dialog_validation import DialogValidationInterceptor

    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "SelectCreatorCityIntent",
                    "slots": {
                        "cityQuery": {
                            "name": "cityQuery",
                            "value": "Swindon",
                            "confirmationStatus": "NONE",
                        }
                    },
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    resolver = AsyncMock()
    resolver.resolve_utterance = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "search",
            "slots": {"city": "Swindon"},
            "searchPayload": {"query": "", "filter": {"city": "Swindon"}},
            "resolution": {
                "match": {
                    "city": "Swindon",
                    "countryCode": "gb",
                    "latitude": 51.56,
                    "longitude": -1.78,
                }
            },
        }
    )
    availability = AsyncMock()
    availability.begin_creator_location = AsyncMock(
        return_value=ResponseBuilder().speak("I found Adeshina Ayomide near Swindon. Would you like to listen?").response
    )
    progressive = AsyncMock(send=AsyncMock(return_value=True))
    container = ApplicationContainer(resolver=resolver, progressive=progressive, request_availability=availability)

    await DialogValidationInterceptor().process(hi)
    await container.build_resolver_interceptor().process(hi)
    await ConfirmationMiddleware().process(hi)

    assert RequestContext.request(hi).get("_pendingConfirmation") is None

    gate = IntentDispatchGateHandler(container.build_request_intent_dispatcher(hi))
    assert gate.can_handle(hi) is True
    res = await gate.handle(hi)
    assert "Adeshina Ayomide near Swindon" in res["outputSpeech"]["ssml"]
    availability.begin_creator_location.assert_awaited_once()


@pytest.mark.asyncio
async def test_unrecognized_creator_city_reprompts_for_city_not_topic_creators():
    from src.alexa.context import RequestContext
    from src.middleware.confirmation import ConfirmationMiddleware
    from src.middleware.dialog_validation import DialogValidationInterceptor

    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "SearchContentIntent",
                    "slots": {
                        "searchQuery": {
                            "name": "searchQuery",
                            "value": "find creators in swidon",
                            "confirmationStatus": "NONE",
                        }
                    },
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    resolver = AsyncMock()
    resolver.resolve_utterance = AsyncMock(
        return_value={
            "status": "resolved",
            "intent": "search",
            "slots": {},
            "searchPayload": {"query": "swidon", "filter": {}},
        }
    )
    availability = AsyncMock()
    availability.begin_creator_location = AsyncMock(
        return_value=ResponseBuilder().speak("Sorry, I couldn't identify that location. Please try another city.").response
    )
    progressive = AsyncMock(send=AsyncMock(return_value=True))
    container = ApplicationContainer(resolver=resolver, progressive=progressive, request_availability=availability)

    await DialogValidationInterceptor().process(hi)
    await container.build_resolver_interceptor().process(hi)
    await ConfirmationMiddleware().process(hi)

    assert RequestContext.request(hi).get("_pendingConfirmation") is None

    gate = IntentDispatchGateHandler(container.build_request_intent_dispatcher(hi))
    assert gate.can_handle(hi) is True
    res = await gate.handle(hi)
    assert "couldn't identify that location" in res["outputSpeech"]["ssml"]
    assert "creators" not in res["outputSpeech"]["ssml"]
    availability.begin_creator_location.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_idle_yes_does_not_trigger_search_confirmation():
    from src.alexa.context import RequestContext
    from src.middleware.confirmation import ConfirmationMiddleware
    from src.middleware.dialog_validation import DialogValidationInterceptor

    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "OpenDiscoveryIntent",
                    "slots": {
                        "searchQuery": {
                            "name": "searchQuery",
                            "value": "yes",
                            "confirmationStatus": "NONE",
                        }
                    },
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    resolver = AsyncMock()
    progressive = AsyncMock(send=AsyncMock(return_value=True))
    container = ApplicationContainer(resolver=resolver, progressive=progressive)

    await DialogValidationInterceptor().process(hi)
    await container.build_resolver_interceptor().process(hi)
    await ConfirmationMiddleware().process(hi)

    assert resolver.resolve_utterance.call_count == 0
    assert RequestContext.request(hi).get("_pendingConfirmation") is None

    gate = IntentDispatchGateHandler(container.build_request_intent_dispatcher(hi))
    assert gate.can_handle(hi) is True
    res = gate.handle(hi)
    assert "Please say the name of a talking newspaper, creator, publication, or city" in res["outputSpeech"]["ssml"]


@pytest.mark.asyncio
async def test_resolver_interceptor_preserves_availability_dialog_on_fallback_intent():
    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {"name": "AMAZON.FallbackIntent", "slots": {}},
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    DialogStateManager.activate(
        hi,
        "availability",
        context={"kind": "publication", "candidates": [{"id": "p1", "name": "Pub 1"}]},
    )
    resolver = AsyncMock()
    container = ApplicationContainer(resolver=resolver)

    await container.build_resolver_interceptor().process(hi)

    assert resolver.resolve_utterance.call_count == 0
    active = DialogStateManager.get_active(hi)
    assert active is not None
    assert active["type"] == "availability"


@pytest.mark.asyncio
async def test_resolver_interceptor_preserves_availability_dialog_on_dismiss_phrase():
    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "OpenDiscoveryIntent",
                    "slots": {
                        "searchQuery": {
                            "name": "searchQuery",
                            "value": "something else",
                            "confirmationStatus": "NONE",
                        }
                    },
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    DialogStateManager.activate(
        hi,
        "availability",
        context={"kind": "publication", "candidates": [{"id": "p1", "name": "Pub 1"}]},
    )
    resolver = AsyncMock()
    container = ApplicationContainer(resolver=resolver)

    await container.build_resolver_interceptor().process(hi)

    assert resolver.resolve_utterance.call_count == 0
    active = DialogStateManager.get_active(hi)
    assert active is not None
    assert active["type"] == "availability"


def test_fallback_handler_preserves_ambiguity_dialog_from_active_state():
    from src.controllers.fallback import FallbackHandler

    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {"name": "AMAZON.FallbackIntent", "slots": {}},
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    DialogStateManager.activate(
        hi,
        "ambiguity",
        context={
            "phrase": "dorking",
            "candidates": [
                {"id": "c1", "name": "Dorking News", "entityType": "publication"},
                {"id": "c2", "name": "Dorking Magazine", "entityType": "publication"},
            ],
            "slots": {"ambiguousReferences": [{"phrase": "dorking"}]},
        },
    )
    container = ApplicationContainer()
    handler = FallbackHandler(container.user, container.onboarding)
    assert handler.can_handle(hi) is True

    res = handler.handle(hi)
    speech = res["outputSpeech"]["ssml"]
    assert "Dorking" in speech
    assert "First, News" in speech
    assert "Second, Magazine" in speech
    assert res["shouldEndSession"] is False


@pytest.mark.asyncio
async def test_dialog_validation_gate_speaks_ambiguity_retry_for_unrecognized_utterance():
    from src.middleware.dialog_validation import (
        DialogValidationGateHandler,
        DialogValidationInterceptor,
    )

    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "OpenDiscoveryIntent",
                    "slots": {"searchQuery": {"name": "searchQuery", "value": "dan"}},
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    DialogStateManager.activate(
        hi,
        "ambiguity",
        context={
            "phrase": "pendle voice",
            "candidates": [
                {"id": "c1", "name": "Pendle Voice Dalesman", "type": "creator"},
                {"id": "c2", "name": "Pendle Voice Lancashire Life", "type": "creator"},
                {"id": "c3", "name": "Pendle Voice Leader and Times", "type": "creator"},
            ],
            "displayedCandidates": [
                {"id": "c1", "name": "Pendle Voice Dalesman", "type": "creator"},
                {"id": "c2", "name": "Pendle Voice Lancashire Life", "type": "creator"},
                {"id": "c3", "name": "Pendle Voice Leader and Times", "type": "creator"},
            ],
            "slots": {},
        },
    )

    await DialogValidationInterceptor().process(hi)
    gate = DialogValidationGateHandler()
    assert gate.can_handle(hi) is True

    res = gate.handle(hi)
    speech = res["outputSpeech"]["ssml"]
    assert "That did not match the available choices beginning Pendle Voice." in speech
    assert "First, Dalesman." in speech
    assert "Second, Lancashire Life." in speech
    assert "Third, Leader and Times." in speech
    assert res["shouldEndSession"] is False


@pytest.mark.asyncio
async def test_dialog_validation_gate_speaks_publication_retry_for_unrecognized_utterance():
    from src.middleware.dialog_validation import (
        DialogValidationGateHandler,
        DialogValidationInterceptor,
    )

    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "OpenDiscoveryIntent",
                    "slots": {"searchQuery": {"name": "searchQuery", "value": "yu"}},
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    hi = HandlerInput(envelope, attributes, None, ResponseBuilder())
    DialogStateManager.activate(
        hi,
        "ambiguity",
        context={
            "phrase": "dorking",
            "candidates": [
                {"id": "p1", "name": "Dorking News April", "type": "publication"},
                {"id": "p2", "name": "Dorking Mag May", "type": "publication"},
            ],
            "displayedCandidates": [
                {"id": "p1", "name": "Dorking News April", "type": "publication"},
                {"id": "p2", "name": "Dorking Mag May", "type": "publication"},
            ],
            "candidatePagination": {"kind": "publication"},
            "slots": {},
        },
    )

    await DialogValidationInterceptor().process(hi)
    gate = DialogValidationGateHandler()
    assert gate.can_handle(hi) is True

    res = gate.handle(hi)
    speech = res["outputSpeech"]["ssml"]
    assert "I didn't match that to one of the publication choices." in speech
    assert "First, Dorking News April." in speech
    assert "Second, Dorking Mag May." in speech
    assert res["shouldEndSession"] is False
