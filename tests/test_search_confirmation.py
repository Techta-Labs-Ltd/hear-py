from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.controllers.intent_dispatch import IntentDispatchGateHandler
from src.middleware.confirmation import (
    ConfirmationMiddleware,
    SearchConfirmationGateHandler,
)
from src.models.affirmative import Affirmative
from src.models.availability_data import AvailabilityData
from src.models.confirmation import ConfirmationPolicy
from src.models.resolver import ResolutionBuilder
from src.models.user import User


def test_topic_trending_confirmation_uses_clean_spoken_text():
    assert (
        ConfirmationPolicy.confirmation_speech(
            {
                "intent": "trending",
                "slots": {"category": "sport", "isRecommended": True},
            }
        )
        == "what's trending in sport"
    )


def test_full_resolved_search_is_spoken_before_backend_search():
    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {
                "System": {
                    "user": {"userId": "test-user"},
                    "device": {"deviceId": "test-device"},
                }
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
                        }
                    },
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
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
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())
    ConfirmationMiddleware().process(handler_input)
    response = IntentDispatchGateHandler(deps=ApplicationContainer()).handle(handler_input)
    assert (
        "Did you want me to play the latest community services from York Talking News?"
        in response["outputSpeech"]["ssml"]
    )
    store = User.snapshot(handler_input)
    assert store["awaitingSearchConfirmation"] is True
    pending = store["pendingResolution"]
    assert pending["searchPayload"]["filter"]["tags"] == ["community-services"]
    assert pending["searchPayload"]["filter"]["organizationIds"] == ["org-ytn"]


def test_constrained_whats_latest_stops_for_confirmation():
    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-user"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {"name": "WhatsTrendingIntent", "slots": {}},
            },
        }
    )
    attributes = AttributesManager(envelope)
    payload = {
        "query": "update",
        "filter": {"categorySlugs": ["sport"], "organizationIds": ["org-ytn"]},
        "sort": "latest",
        "page": 0,
        "limit": 20,
    }
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "category",
            "requestId": "resolution-trending-1",
            "confirmationLabel": "the latest sport update from York Talking News",
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
    response = IntentDispatchGateHandler(deps=ApplicationContainer()).handle(handler_input)
    assert "Did you want me to play the latest sport update" in response["outputSpeech"]["ssml"]
    assert User.snapshot(handler_input)["pendingResolution"]["searchPayload"] == payload


def test_pending_resolution_stores_only_catalog_valid_query_and_sort():
    pending = ResolutionBuilder.build(
        {
            "intent": "publication",
            "searchPayload": {
                "query": None,
                "sort": "relevance",
                "filter": {"organizationIds": ["org-wtn"]},
            },
        },
        "Wakefield Talking Newspaper",
    )
    assert pending["searchPayload"] == {
        "query": "",
        "filter": {"organizationIds": ["org-wtn"]},
    }


def test_pending_resolution_preserves_explicit_location_context():
    pending = ResolutionBuilder.build(
        {
            "intent": "local",
            "requestedLocation": True,
            "slots": {"city": "London", "placeName": "London", "isLocal": True},
            "searchPayload": {
                "query": "",
                "filter": {"city": "London", "isLocal": True},
            },
        },
        "content in London",
    )

    assert pending["requestedLocation"] is True
    assert AvailabilityData.requested_city(pending, pending["searchPayload"]) == "London"


def test_structured_publication_name_wins_over_conflicting_raw_source_words():
    assert (
        ConfirmationPolicy.confirmation_speech(
            {
                "intent": "publication",
                "slots": {
                    "publicationIds": ["publication-orkney"],
                    "publicationName": "Orkney Talking Magazine",
                    "publicationSourceQuery": "Dorking Talking Magazine",
                    "residualQuery": "Dorking Talking Magazine August",
                },
            }
        )
        == "Orkney Talking Magazine"
    )


def test_play_york_tn_still_requires_confirmation():
    envelope = AttrDict(
        {
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
                        }
                    },
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "organization",
            "confirmationLabel": "content from York Talking News",
            "searchPayload": {"query": "", "filter": {"organizationIds": ["org-ytn"]}},
            "slots": {
                "organizationIds": ["org-ytn"],
                "organizationName": "York Talking News",
                "residualQuery": "",
            },
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())
    ConfirmationMiddleware().process(handler_input)
    response = IntentDispatchGateHandler(deps=ApplicationContainer()).handle(handler_input)
    assert (
        "Did you want me to play content from York Talking News?"
        in response["outputSpeech"]["ssml"]
    )
    store = User.snapshot(handler_input)
    assert store["awaitingSearchConfirmation"] is True
    assert store["activeDialog"]["type"] == "search_confirmation"
    session = handler_input.attributes_manager.get_session_attributes()
    assert session["awaitingSearchConfirmation"] is True
    assert session["pendingResolution"] == store["pendingResolution"]


@pytest.mark.asyncio
async def test_yes_uses_session_confirmation_when_persistent_dialog_state_is_missing():
    resolution = {
        "requestId": "resolution-session-1",
        "intent": "organization",
        "confirmationLabel": "content from Wakefield Talking Newspaper",
        "searchPayload": {"query": "", "filter": {"organizationIds": ["org-wtn"]}},
        "expiresAt": int(time.time()) + 300,
    }
    envelope = AttrDict(
        {
            "version": "1.0",
            "session": {
                "attributes": {
                    "awaitingSearchConfirmation": True,
                    "pendingResolution": resolution,
                }
            },
            "context": {"System": {"user": {"userId": "test-user"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {"name": "AMAZON.YesIntent", "slots": {}},
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())
    expected = {"outputSpeech": {"ssml": "played"}}
    availability = SimpleNamespace(handle_resolution=AsyncMock(return_value=expected))
    deps = SimpleNamespace(user=User(), availability=availability)

    response = await Affirmative(deps=deps).execute(handler_input)

    assert response == expected
    availability.handle_resolution.assert_awaited_once()
    assert attributes.get_session_attributes() == {}


def test_empty_play_request_reports_failed_recognition_and_stays_open():
    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-user"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {"name": "PlayContentIntent", "slots": {}},
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
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
    response = IntentDispatchGateHandler(deps=ApplicationContainer()).handle(handler_input)
    assert "Sorry, I didn't catch that" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False
    assert response.get("directives") in (None, [])
    store = User.snapshot(handler_input)
    assert store["awaitingSearchConfirmation"] is False


def test_generic_anything_asks_for_specific_request():
    envelope = AttrDict(
        {
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
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
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
    response = IntentDispatchGateHandler(deps=ApplicationContainer()).handle(handler_input)
    assert "Sorry, I didn't catch that" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False
    assert response.get("directives") in (None, [])
    assert User.snapshot(handler_input)["awaitingSearchConfirmation"] is False


def test_bare_trending_request_bypasses_confirmation():
    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-user"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {"name": "WhatsTrendingIntent", "slots": {}},
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
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
    assert handler_input.attributes_manager.request_attributes.get("_pendingConfirmation") is None
    assert SearchConfirmationGateHandler().can_handle(handler_input) is False
    assert User.snapshot(handler_input).get("awaitingSearchConfirmation") is False


def test_resolved_search_alias_is_always_confirmed():
    envelope = AttrDict(
        {
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
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
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
    response = IntentDispatchGateHandler(deps=ApplicationContainer()).handle(handler_input)
    assert "Did you want me to play content on Wakefield news?" in response["outputSpeech"]["ssml"]
    assert User.snapshot(handler_input)["awaitingSearchConfirmation"] is True


def test_category_search_is_described_as_content_on_subject():
    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-user"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "PlayContentIntent",
                    "slots": {"topic": {"name": "topic", "value": "history"}},
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "category",
            "confirmationLabel": "history",
            "searchPayload": {"query": "", "filter": {"categorySlugs": ["history"]}},
            "slots": {"category": "history", "tags": ["history"], "residualQuery": ""},
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())
    ConfirmationMiddleware().process(handler_input)
    response = IntentDispatchGateHandler(deps=ApplicationContainer()).handle(handler_input)
    assert "Did you want me to play content on history?" in response["outputSpeech"]["ssml"]
    assert User.snapshot(handler_input)["pendingResolution"]["searchPayload"] == {
        "query": "",
        "filter": {"categorySlugs": ["history"]},
    }


def test_location_only_search_is_confirmed_with_city_filter():
    envelope = AttrDict(
        {
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
                            "value": "Liverpool",
                        }
                    },
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    payload = {
        "query": "",
        "filter": {
            "city": "Liverpool",
            "countryCode": "gb",
            "latitude": 53.4072,
            "longitude": -2.9917,
        },
    }
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "search",
            "searchPayload": payload,
            "slots": {
                "city": "Liverpool",
                "placeName": "Liverpool",
                "countryCode": "gb",
                "latitude": 53.4072,
                "longitude": -2.9917,
                "isLocal": True,
                "residualQuery": "",
                "searchPlan": payload,
            },
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())
    ConfirmationMiddleware().process(handler_input)
    response = IntentDispatchGateHandler(deps=ApplicationContainer()).handle(handler_input)
    assert "Did you want me to play content in Liverpool?" in response["outputSpeech"]["ssml"]
    attrs = handler_input.attributes_manager.request_attributes
    assert "_resolverClarification" not in attrs
    store = User.snapshot(handler_input)
    assert store["awaitingSearchConfirmation"] is True
    assert store["pendingResolution"]["searchPayload"] == payload


def test_search_confirmation_gate_blocks_direct_catalogue_fallback():
    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-user"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {"name": "PlayContentIntent", "slots": {}},
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())
    gate = SearchConfirmationGateHandler()
    assert gate.can_handle(handler_input) is True
    response = gate.handle(handler_input)
    assert "couldn't safely confirm that search" in response["outputSpeech"]["ssml"]
    assert response["shouldEndSession"] is False


def test_search_confirmation_gate_allows_unresolved_reference_handler():
    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-user"}}},
            "request": {
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
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
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
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())

    ConfirmationMiddleware().process(handler_input)

    assert SearchConfirmationGateHandler().can_handle(handler_input) is False
    assert IntentDispatchGateHandler(deps=ApplicationContainer()).can_handle(handler_input) is True


def test_resolved_pendle_ambiguity_bypasses_generic_clarification():
    envelope = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-user"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "PlayContentIntent",
                    "slots": {"topic": {"name": "topic", "value": "pendle voice"}},
                },
            },
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {**StateSchema.DEFAULT_STORE, "onboardingComplete": True},
        "_dirty": False,
        "_nlp": {
            "status": "resolved",
            "intent": "search",
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
            "searchPayload": {"query": "", "filter": {}},
            "slots": {
                "residualQuery": "",
                "ambiguousReferences": [
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
            },
        },
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())
    ConfirmationMiddleware().process(handler_input)
    attrs = handler_input.attributes_manager.request_attributes
    assert "_resolverClarification" not in attrs
    assert "_pendingConfirmation" not in attrs
    assert SearchConfirmationGateHandler().can_handle(handler_input) is False
