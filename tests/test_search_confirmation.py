from __future__ import annotations

from src.middleware.confirmation import ConfirmationMiddleware
from src.handlers.dispatch import IntentDispatchHandler

from src.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.services.store import DEFAULT_STORE, get_store



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
