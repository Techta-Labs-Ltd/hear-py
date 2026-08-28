from __future__ import annotations

from src.middleware.confirmation import ConfirmationMiddleware, SearchConfirmationGateHandler
from src.handlers.dispatch import IntentDispatchHandler

from src.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.services.store import DEFAULT_STORE, get_store
from src.services.resolution import build_pending_resolution



def test_full_resolved_search_is_spoken_before_backend_search():
    envelope = AttrDict({
        "version": "1.0",
        "context": {
            "System": {
                "user": {"userId": "test-user"},
                "device": {"deviceId": "test-device"},
            },
        },
        "request": {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayByOrganizationIntent",
                "slots": {
                    "organizationQuery": {
                        "name": "organizationQuery",
                        "value": "latest community service from ytn",
                    },
                },
            },
        },
    })
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "intent": "organization",
            "requestId": "resolution-1",
            "confirmationLabel": "the latest community services from York Talking News",
            "searchPayload": {
                "query": "",
                "filter": {
                    "tags": ["community-services"],
                    "organizationIds": ["org-ytn"],
                },
                "sort": "latest",
                "page": 0,
                "limit": 20,
            },
            "slots": {
                "latest": True,
                "tags": ["community-services"],
                "organizationIds": ["org-ytn"],
                "organizationName": "York Talking News",
                "residualQuery": "",
            },
        },
    }
    handler_input = HandlerInput(
        envelope, attributes, None, ResponseBuilder(),
    )

    ConfirmationMiddleware().process(handler_input)
    response = IntentDispatchHandler().handle(handler_input)

    assert (
        "Did you want me to play the latest community services "
        "from York Talking News?"
    ) in response["outputSpeech"]["ssml"]
    store = get_store(handler_input)
    assert store["awaitingSearchConfirmation"] is True
    pending = store["pendingResolution"]
    assert pending["searchPayload"]["filter"]["tags"] == ["community-services"]
    assert pending["searchPayload"]["filter"]["organizationIds"] == ["org-ytn"]


def test_constrained_whats_latest_stops_for_confirmation():
    envelope = AttrDict({
        "version": "1.0",
        "context": {"System": {"user": {"userId": "test-user"}}},
        "request": {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "WhatsTrendingIntent", "slots": {}},
        },
    })
    attributes = AttributesManager(envelope)
    payload = {
        "query": "update",
        "filter": {
            "categorySlugs": ["sport"],
            "organizationIds": ["org-ytn"],
        },
        "sort": "latest",
        "page": 0,
        "limit": 20,
    }
    attributes.request_attributes = {
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "category",
            "requestId": "resolution-trending-1",
            "confirmationLabel": (
                "the latest sport update from York Talking News"
            ),
            "searchPayload": payload,
            "slots": {
                "latest": True,
                "category": "sport",
                "residualQuery": "update",
                "organizationIds": ["org-ytn"],
                "organizationName": "York Talking News",
            },
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())

    ConfirmationMiddleware().process(handler_input)
    response = IntentDispatchHandler().handle(handler_input)

    assert "Did you want me to play the latest sport update" in (
        response["outputSpeech"]["ssml"]
    )
    assert get_store(handler_input)["pendingResolution"]["searchPayload"] == payload


def test_pending_resolution_stores_only_catalog_valid_query_and_sort():
    pending = build_pending_resolution({
        "intent": "publication",
        "searchPayload": {
            "query": None,
            "sort": "relevance",
            "filter": {"organizationIds": ["org-wtn"]},
        },
    }, "Wakefield Talking Newspaper")

    assert pending["searchPayload"] == {
        "query": "",
        "filter": {"organizationIds": ["org-wtn"]},
    }


def test_play_york_tn_still_requires_confirmation():
    envelope = AttrDict({
        "version": "1.0",
        "context": {"System": {"user": {"userId": "test-user"}}},
        "request": {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayByOrganizationIntent",
                "slots": {
                    "organizationQuery": {
                        "name": "organizationQuery",
                        "value": "York TN",
                    },
                },
            },
        },
    })
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "organization",
            "confirmationLabel": "content from York Talking News",
            "searchPayload": {
                "query": "",
                "filter": {"organizationIds": ["org-ytn"]},
            },
            "slots": {
                "organizationIds": ["org-ytn"],
                "organizationName": "York Talking News",
                "residualQuery": "",
            },
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())

    ConfirmationMiddleware().process(handler_input)
    response = IntentDispatchHandler().handle(handler_input)

    assert "Did you want me to play content from York Talking News?" in (
        response["outputSpeech"]["ssml"]
    )
    store = get_store(handler_input)
    assert store["awaitingSearchConfirmation"] is True
    assert store["activeDialog"]["type"] == "search_confirmation"


def test_empty_play_request_reports_failed_recognition_and_stays_open():
    envelope = AttrDict({
        "version": "1.0",
        "context": {"System": {"user": {"userId": "test-user"}}},
        "request": {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "PlayContentIntent", "slots": {}},
        },
    })
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "general",
            "searchPayload": {"query": "", "filter": {}},
            "slots": {"residualQuery": ""},
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())

    ConfirmationMiddleware().process(handler_input)
    response = IntentDispatchHandler().handle(handler_input)

    assert "Sorry, I didn't catch that" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False
    assert response.get("directives") in (None, [])
    store = get_store(handler_input)
    assert store["awaitingSearchConfirmation"] is False


def test_generic_anything_asks_for_specific_request():
    envelope = AttrDict({
        "version": "1.0",
        "context": {"System": {"user": {"userId": "test-user"}}},
        "request": {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "anything"}},
            },
        },
    })
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "general",
            "searchPayload": {"query": "anything", "filter": {}},
            "slots": {"residualQuery": "anything"},
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())

    ConfirmationMiddleware().process(handler_input)
    response = IntentDispatchHandler().handle(handler_input)

    assert "Sorry, I didn't catch that" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False
    assert response.get("directives") in (None, [])
    assert get_store(handler_input)["awaitingSearchConfirmation"] is False


def test_bare_trending_request_bypasses_confirmation():
    envelope = AttrDict({
        "version": "1.0",
        "context": {"System": {"user": {"userId": "test-user"}}},
        "request": {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "WhatsTrendingIntent", "slots": {}},
        },
    })
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "trending",
            "directDiscoveryRequest": True,
            "searchPayload": {"query": "", "filter": {}, "sort": "trending"},
            "slots": {"residualQuery": ""},
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())

    ConfirmationMiddleware().process(handler_input)
    assert handler_input.attributes_manager.request_attributes.get(
        "_pendingConfirmation"
    ) is None
    assert SearchConfirmationGateHandler().can_handle(handler_input) is False
    assert get_store(handler_input).get("awaitingSearchConfirmation") is False


def test_resolved_search_alias_is_always_confirmed():
    envelope = AttrDict({
        "version": "1.0",
        "context": {"System": {"user": {"userId": "test-user"}}},
        "request": {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {"topic": {"name": "topic", "value": "Wakefield news"}},
            },
        },
    })
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "search",
            "confirmationLabel": "Wakefield news",
            "searchPayload": {"query": "Wakefield news", "filter": {}},
            "slots": {"residualQuery": "Wakefield news"},
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())

    ConfirmationMiddleware().process(handler_input)
    response = IntentDispatchHandler().handle(handler_input)

    assert "Did you want me to play Wakefield news?" in response["outputSpeech"]["ssml"]
    assert get_store(handler_input)["awaitingSearchConfirmation"] is True


def test_search_confirmation_gate_blocks_direct_catalogue_fallback():
    envelope = AttrDict({
        "version": "1.0",
        "context": {"System": {"user": {"userId": "test-user"}}},
        "request": {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "PlayContentIntent", "slots": {}},
        },
    })
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())
    gate = SearchConfirmationGateHandler()

    assert gate.can_handle(handler_input) is True
    response = gate.handle(handler_input)
    assert "couldn't safely confirm that search" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False


def test_resolved_pendle_ambiguity_bypasses_generic_clarification():
    envelope = AttrDict({
        "version": "1.0",
        "context": {"System": {"user": {"userId": "test-user"}}},
        "request": {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "slots": {
                    "topic": {"name": "topic", "value": "pendle voice"},
                },
            },
        },
    })
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "search",
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
            "searchPayload": {"query": "", "filter": {}},
            "slots": {
                "residualQuery": "",
                "ambiguousReferences": [{
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
            },
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())

    ConfirmationMiddleware().process(handler_input)

    attrs = handler_input.attributes_manager.request_attributes
    assert "_resolverClarification" not in attrs
    assert "_pendingConfirmation" not in attrs
    assert SearchConfirmationGateHandler().can_handle(handler_input) is False
