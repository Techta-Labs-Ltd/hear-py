from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.handlers.launch import TownCaptureHandler

from src.middleware.pipeline import REQUEST_INTERCEPTORS
from src.middleware.resolver import ResolverInterceptor

from src.runtime import AttrDict, ResponseBuilder
from src.services.store import DEFAULT_STORE, get_store

from src.clients.resolver import ResolverUnavailable, ResolverClient
from src.clients.hear import HearApiClient

from src.utils.speech import resolved_search_request_label


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
async def test_misspelled_bare_town_is_owned_by_onboarding(monkeypatch, mock_handler_input):
    monkeypatch.setattr(
        ResolverClient, "resolve_utterance",
        AsyncMock(return_value={
            "status": "resolved",
            "resolution": {"match": {"city": "Swindon"}, "candidates": []},
        }),
    )
    handler_input = _town_request(mock_handler_input, "swidon")
    await ResolverInterceptor().process(handler_input)

    assert TownCaptureHandler().can_handle(handler_input)
    await TownCaptureHandler().handle(handler_input)

    store = get_store(handler_input)
    assert store["pendingLocationConfirm"]["city"] == "Swindon"
    assert store["awaitingLocationConfirm"] is True
    assert store["onboardingStage"] == "await_location_confirm"
    assert store["_requiresReliableSave"] is True
    session = handler_input.attributes_manager.set_session_attributes.call_args.args[0]
    assert session["onboardingStage"] == "await_location_confirm"
    assert session["awaitingLocationConfirm"] is True
    handler_input.response_builder.speak.return_value.reprompt.return_value \
        .set_should_end_session.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_city_entity_resolution_sends_canonical_town_to_resolver(
    monkeypatch, mock_handler_input,
):
    resolve = AsyncMock(return_value={
        "status": "resolved",
        "resolution": {"match": {"city": "Herne Bay"}, "candidates": []},
    })
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    handler_input = _town_request(mock_handler_input, "arn bay")
    slot = handler_input.request_envelope.request.intent.slots["townName"]
    slot["resolutions"] = {
        "resolutionsPerAuthority": [{
            "status": {"code": "ER_SUCCESS_MATCH"},
            "values": [{"value": {
                "id": "location-1826454069",
                "name": "Herne Bay",
            }}],
        }],
    }

    await ResolverInterceptor().process(handler_input)
    await TownCaptureHandler().handle(handler_input)

    assert handler_input.attributes_manager.request_attributes["_nlp"]["slots"] == {
        "townName": "Herne Bay",
        "placeName": "Herne Bay",
    }
    resolve.assert_awaited_once()
    assert resolve.await_args.args == ("Herne Bay",)
    assert resolve.await_args.kwargs == {
        "alexa_user_id": "amzn1.ask.account.TEST",
        "prefer_location": True,
    }


@pytest.mark.asyncio
async def test_onboarding_treats_creator_misclassification_as_town(
    monkeypatch, mock_handler_input,
):
    resolve = AsyncMock(return_value={
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
    })
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayByCreatorIntent",
            "slots": {
                "creatorQuery": {
                    "name": "creatorQuery",
                    "value": "Gloucester",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingStage": "ask_town",
    }

    await ResolverInterceptor().process(mock_handler_input)

    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "town_capture"
    assert nlp["slots"]["townName"] == "Gloucester"
    assert TownCaptureHandler().can_handle(mock_handler_input)

    await TownCaptureHandler().handle(mock_handler_input)

    store = get_store(mock_handler_input)
    assert store["onboardingStage"] == "await_location_confirm"
    assert store["pendingLocationConfirm"]["city"] == "Gloucester"
    assert store["onboardingTownAttempts"] == 0
    resolve.assert_awaited_once_with(
        "Gloucester",
        alexa_user_id="amzn1.ask.account.TEST",
        prefer_location=True,
    )


def test_manual_town_reprompt_exposes_skip_command():
    from src.utils.speech import REPROMPT_ASK_TOWN

    assert "say skip" in REPROMPT_ASK_TOWN.casefold()


@pytest.mark.asyncio
async def test_onboarding_gate_preserves_city_phrase_misclassified_as_search(
    mock_handler_input,
):
    from src.middleware.onboarding_gate import OnboardingGateHandler

    handler_input = _town_request(mock_handler_input, "ammm ba")
    handler_input.request_envelope.request.intent.name = "PlayContentIntent"
    handler_input.request_envelope.request.intent.slots = {
        "topic": {"name": "topic", "value": "ammm ba"},
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
    gate = OnboardingGateHandler()

    assert gate.can_handle(handler_input) is True
    await gate.handle(handler_input)

    speech = handler_input.response_builder.speak.call_args.args[0]
    assert "couldn't find ammm ba as a city" in speech.casefold()
    handler_input.response_builder.speak.return_value.reprompt.return_value \
        .set_should_end_session.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_town_intent_remains_owned_when_resolver_calls_it_search(
    monkeypatch,
    mock_handler_input,
):
    resolve = AsyncMock(return_value={
        "status": "resolved",
        "intent": "search",
        "entities": [],
        "resolution": {"match": None, "candidates": []},
        "slots": {"residualQuery": "ammm ba"},
    })
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    handler_input = _town_request(mock_handler_input, "ammm ba")
    handler_input.attributes_manager.request_attributes["_nlp"] = {
        "status": "resolved",
        "intent": "search",
        "entities": [],
        "slots": {"residualQuery": "ammm ba"},
    }
    handler = TownCaptureHandler()

    assert handler.can_handle(handler_input) is True
    await handler.handle(handler_input)

    speech = handler_input.response_builder.speak.call_args.args[0]
    assert "couldn't find ammm ba as a city" in speech.casefold()
    handler_input.response_builder.speak.return_value.reprompt.return_value \
        .add_directive.return_value.set_should_end_session.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_unknown_city_names_city_and_keeps_session_open(
    monkeypatch,
    mock_handler_input,
):
    monkeypatch.setattr(
        ResolverClient,
        "resolve_utterance",
        AsyncMock(return_value={
            "status": "resolved",
            "resolution": {"match": None, "candidates": []},
        }),
    )
    handler_input = _town_request(mock_handler_input, "nottinghamshire place")

    await TownCaptureHandler().handle(handler_input)

    speech = handler_input.response_builder.speak.call_args.args[0]
    assert "couldn't find nottinghamshire place as a city" in speech.casefold()
    retry_builder = handler_input.response_builder.speak.return_value.reprompt.return_value
    retry_builder.add_directive.assert_called_once_with({
        "type": "Dialog.ElicitSlot",
        "slotToElicit": "townName",
    })
    retry_builder.add_directive.return_value.set_should_end_session \
        .assert_called_once_with(False)
    assert get_store(handler_input)["onboardingStage"] == "ask_town"


@pytest.mark.asyncio
async def test_town_slot_fallback_resolves_without_nlp_attrs(monkeypatch, mock_handler_input):
    monkeypatch.setattr(
        ResolverClient, "resolve_utterance",
        AsyncMock(return_value={
            "status": "resolved",
            "resolution": {"match": {"city": "Swindon"}, "candidates": []},
        }),
    )
    handler_input = _town_request(mock_handler_input, "swidon")
    await TownCaptureHandler().handle(handler_input)

    store = get_store(handler_input)
    assert store["pendingLocationConfirm"]["city"] == "Swindon"
    assert store["awaitingLocationConfirm"] is True


@pytest.mark.asyncio
async def test_town_resolver_failure_retries_once_without_closing_session(
    monkeypatch, mock_handler_input,
):
    monkeypatch.setattr(
        ResolverClient, "resolve_utterance",
        AsyncMock(side_effect=ResolverUnavailable("taxonomy_sync_unavailable")),
    )
    handler_input = _town_request(mock_handler_input, "york")

    await TownCaptureHandler().handle(handler_input)

    store = get_store(handler_input)
    speech = handler_input.response_builder.speak.call_args.args[0]
    assert "try the city name again" in speech
    retry_builder = handler_input.response_builder.speak.return_value.reprompt.return_value
    retry_builder.add_directive.assert_called_once_with({
        "type": "Dialog.ElicitSlot",
        "slotToElicit": "townName",
    })
    retry_builder.add_directive.return_value.set_should_end_session \
        .assert_called_once_with(False)
    assert store["onboardingStage"] == "ask_town"
    assert store["onboardingTownResolverFailures"] == 1


@pytest.mark.asyncio
async def test_repeated_town_resolver_failure_continues_without_location(
    monkeypatch, mock_handler_input,
):
    monkeypatch.setattr(
        ResolverClient, "resolve_utterance",
        AsyncMock(side_effect=ResolverUnavailable("taxonomy_sync_unavailable")),
    )
    handler_input = _town_request(mock_handler_input, "herne bay")
    handler_input.attributes_manager.request_attributes["_store"][
        "onboardingTownResolverFailures"
    ] = 1

    await TownCaptureHandler().handle(handler_input)

    store = get_store(handler_input)
    speech = handler_input.response_builder.speak.call_args.args[0]
    assert "continue without your location" in speech
    handler_input.response_builder.speak.return_value.reprompt.return_value \
        .set_should_end_session.assert_called_once_with(False)
    assert store["onboardingComplete"] is True
    assert store["onboardingStage"] is None


def test_search_confirmation_runs_after_local_nlp_resolution():
    names = [interceptor.__name__ for interceptor in REQUEST_INTERCEPTORS]
    assert "ConfirmationMiddleware" in names
    assert names.index("ConfirmationMiddleware") > names.index("ResolverInterceptor")


def test_resolved_confirmation_repeats_full_search_request():
    assert resolved_search_request_label({
        "latest": True,
        "tags": ["community-services"],
        "residualQuery": "",
        "organizationIds": ["org-ytn"],
    }, "York Talking News") == (
        "the latest community services from York Talking News"
    )


def test_confirmation_never_uses_from_without_source_filter():
    assert resolved_search_request_label({
        "category": "sport",
        "residualQuery": "adeshina",
    }, "sport from adeshina") == "sport adeshina"


def test_publication_filter_uses_natural_source_wording():
    assert resolved_search_request_label({
        "latest": True,
        "category": "sport",
        "publicationIds": ["publication-1"],
        "publicationName": "London Weekly Review",
        "city": "London",
    }, "London Weekly Review") == (
        "the latest sport from London Weekly Review in London"
    )


def test_bare_publication_confirmation_speaks_its_name_directly():
    assert resolved_search_request_label({
        "publicationIds": ["publication-1"],
        "publicationName": "Weekend product podcast",
        "residualQuery": "",
        "isPublication": False,
    }) == "Weekend product podcast"


def test_publication_format_is_spoken_with_creator_source():
    assert resolved_search_request_label({
        "isPublication": True,
        "latest": True,
        "creatorIds": ["creator-1"],
        "creatorName": "Adeshina Ayomide",
    }) == "the latest publication from Adeshina Ayomide"


def test_epoch_month_filter_is_spoken_in_readable_calendar_format():
    assert resolved_search_request_label({
        "latest": True,
        "searchPlan": {
            "filter": {
                "publishedFrom": 1780272000,
                "publishedTo": 1782864000,
            },
            "sort": "latest",
        },
    }) == "the latest content published in June 2026"


@pytest.mark.asyncio
async def test_publication_intent_reconstructs_sort_and_source_for_resolver(
    monkeypatch,
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "requestId": "publication-request",
        "locale": "en-GB",
        "intent": {
            "name": "PlayPublicationIntent",
            "slots": {
                "publicationSort": {
                    "name": "publicationSort",
                    "value": "latest",
                },
                "publicationSourceQuery": {
                    "name": "publicationSourceQuery",
                    "value": "tnf",
                },
            },
        },
    })
    resolve = AsyncMock(return_value={
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
                "filter": {
                    "isPublication": True,
                    "organizationIds": ["org-tnf"],
                },
                "sort": "latest",
            },
        },
    })
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor().process(mock_handler_input)

    assert resolve.await_args.args == ("play latest publication from tnf",)


@pytest.mark.asyncio
async def test_publication_intent_carries_alexa_date_with_source_to_resolver(
    monkeypatch,
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.request_envelope.request = AttrDict({
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
    })
    resolve = AsyncMock(return_value={
        "status": "resolved",
        "intent": "organization",
        "slots": {"searchPlan": {}},
    })
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor().process(mock_handler_input)

    assert resolve.await_args.args == ("play 2026-08-02 publication from wtn",)


@pytest.mark.asyncio
async def test_publication_discovery_sends_format_and_creator_filters(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.search import discover_content_via_search


    mock_handler_input.request_envelope = AttrDict(
        mock_handler_input.request_envelope
    )
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {"name": "PlayPublicationIntent", "slots": {}},
    })
    mock_handler_input.attributes_manager.request_attributes.update({
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_nlp": {
            "intent": "creator",
            "slots": {
                "isPublication": True,
                "creatorIds": ["creator-1"],
                "residualQuery": "",
                "searchPlan": {
                    "filter": {
                        "isPublication": True,
                        "creatorIds": ["creator-1"],
                    },
                    "sort": "trending",
                },
            },
        },
    })
    search = AsyncMock(return_value={
        "failed": False,
        "results": [],
        "total_hits": 0,
    })
    monkeypatch.setattr(HearApiClient, "search", search)

    await discover_content_via_search(mock_handler_input)

    payload = search.await_args.args[0]
    assert payload["query"] == ""
    assert payload["filter"] == {
        "creatorIds": ["creator-1"],
        "isPublication": True,
    }
    assert payload["sort"] == "trending"


@pytest.mark.asyncio
async def test_unresolved_source_is_not_sent_as_a_search_query(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.search import discover_content_via_search


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
    monkeypatch.setattr("src.clients.hear.search", search)

    result = await discover_content_via_search(
        handler_input,
        {"q": "", "intent": "category"},
    )

    search.assert_not_awaited()
    assert "creator, organisation or publication named david" in result["client_message"]


@pytest.mark.asyncio
async def test_organization_slot_is_resolved_and_confirmed_before_search(
    monkeypatch,
    mock_handler_input,
):
    from src.middleware.confirmation import ConfirmationMiddleware
    from src.handlers.dispatch import IntentDispatchHandler


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

    await ResolverInterceptor().process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    IntentDispatchHandler().handle(mock_handler_input)

    store = get_store(mock_handler_input)
    assert store["awaitingSearchConfirmation"] is True
    assert store["pendingResolution"]["searchPayload"]["filter"]["organizationIds"] == ["org-tnf"]


@pytest.mark.asyncio
async def test_resolved_organization_requires_confirmation_before_search(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.play import PlayByOrganizationHandler


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
        "src.handlers.play.discover_content_via_search", discover,
    )

    await PlayByOrganizationHandler().handle(mock_handler_input)

    store = get_store(mock_handler_input)
    assert store["awaitingSearchConfirmation"] is True
    assert store["pendingResolution"]["intent"] == "organization"
    assert store["pendingResolution"]["confirmationLabel"] == (
        "heatwave from York Talking News"
    )
    discover.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_organization_prompts_and_preserves_all_candidates(
    mock_handler_input,
):
    from src.handlers.play import PlayByOrganizationHandler


    candidates = [
        {"type": "organization", "id": f"org-{index}", "name": name}
        for index, name in enumerate((
            "Wakefield Talking Newspaper",
            "Walsall Talking Newspaper",
            "Warrington Talking Newspaper",
            "Wirral Talking Newspaper",
        ))
    ]
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
                    "value": "wtn",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes.update({
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_nlp": {
            "requestId": "ambiguous-wtn",
            "intent": "organization",
            "originalUtterance": "play wtn",
            "searchPayload": {"query": "", "page": 0, "limit": 20},
            "slots": {
                "residualQuery": "",
                "ambiguousReferences": [{
                    "phrase": "wtn",
                    "candidates": candidates,
                }],
            },
        },
    })

    await PlayByOrganizationHandler().handle(mock_handler_input)

    store = get_store(mock_handler_input)
    assert store["activeDialog"]["type"] == "ambiguity"
    assert store["pendingAmbiguity"]["candidates"] == candidates
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "more than one match" in spoken
    assert "couldn't match" not in spoken
    directive = mock_handler_input.response_builder.add_directive.call_args.args[0]
    assert directive["type"] == "Dialog.UpdateDynamicEntities"
    assert directive["types"][0]["name"] == "HEAR_CLARIFICATION"


@pytest.mark.asyncio
async def test_ambiguity_response_without_original_slot_reprompts_candidates(
    monkeypatch,
    mock_handler_input,
):
    """A bare ambiguity follow-up must not become the generic TN prompt."""
    from src.handlers.play import PlayByOrganizationHandler


    candidates = [
        {"type": "organization", "id": "org-wakefield", "name": "Wakefield Talking Newspaper"},
        {"type": "organization", "id": "org-walsall", "name": "Walsall Talking Newspaper"},
        {"type": "organization", "id": "org-warrington", "name": "Warrington Talking Newspaper"},
    ]
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {"name": "PlayByOrganizationIntent", "slots": {}},
    })
    mock_handler_input.attributes_manager.request_attributes.update({
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_nlp": {
            "status": "ambiguous",
            "intent": "organization",
            "slots": {"ambiguousReferences": [{
                "phrase": "wtn",
                "candidates": candidates,
            }]},
        },
    })
    discover = AsyncMock(return_value={
        "results": [],
        "total_hits": 0,
        "failed": False,
        "client_message": (
            "I found more than one match for that name. Did you mean "
            "Wakefield Talking Newspaper, Walsall Talking Newspaper, or "
            "Warrington Talking Newspaper?"
        ),
    })
    monkeypatch.setattr(
        "src.handlers.play.discover_content_via_search", discover,
    )

    await PlayByOrganizationHandler().handle(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "more than one match" in spoken
    assert "Which talking newspaper" not in spoken
    discover.assert_awaited_once()


def test_fallback_during_ambiguity_repeats_candidates_not_welcome(
    mock_handler_input,
):
    from src.handlers.fallback import FallbackHandler


    candidates = [
        {"type": "organization", "id": "org-wakefield", "name": "Wakefield Talking Newspaper"},
        {"type": "organization", "id": "org-walsall", "name": "Walsall Talking Newspaper"},
        {"type": "organization", "id": "org-warrington", "name": "Warrington Talking Newspaper"},
    ]
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {"name": "AMAZON.FallbackIntent", "slots": {}},
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "pendingAmbiguity": {
            "slots": {"ambiguousReferences": [{
                "phrase": "wtn",
                "candidates": candidates,
            }]},
            "candidates": candidates,
        },
    }

    FallbackHandler().handle(mock_handler_input)

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
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {"name": "AMAZON.FallbackIntent", "slots": {}},
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "pendingAmbiguity": {
            "slots": {"ambiguousReferences": [{
                "phrase": "wtn",
                "candidates": [],
            }]},
            "candidates": [{
                "type": "organization",
                "id": "org-walsall",
                "name": "Walsall Talking Newspaper",
            }],
        },
    }

    await ResolverInterceptor().process(mock_handler_input)

    assert "_nlp" not in mock_handler_input.attributes_manager.request_attributes


@pytest.mark.asyncio
async def test_organization_ambiguity_reply_wins_over_stale_town_capture(
    monkeypatch,
    mock_handler_input,
):
    """`wtn` -> `walsall` must select the organisation, not set a city."""
    candidates = [
        {"type": "organization", "id": "org-wakefield", "name": "Wakefield Talking Newspaper"},
        {"type": "organization", "id": "org-walsall", "name": "Walsall Talking Newspaper"},
        {"type": "organization", "id": "org-warrington", "name": "Warrington Talking Newspaper"},
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
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            # Alexa can retain the town slot model even though Hear's latest
            # prompt is an organization clarification.
            "name": "SetLocationIntent",
            "slots": {"location": {"name": "location", "value": "walsall"}},
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
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
        ResolverClient, "resolve_utterance",
        AsyncMock(return_value={
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
            "entities": [{
                "type": "organization",
                "id": "org-walsall",
                "canonicalValue": "Walsall Talking Newspaper",
            }],
            "slots": {
                "organizationIds": ["org-walsall"],
                "organizationName": "Walsall Talking Newspaper",
                "residualQuery": "",
            },
        }),
    )

    await ResolverInterceptor().process(mock_handler_input)

    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "organization"
    assert nlp["searchPayload"]["filter"] == {
        "organizationIds": ["org-walsall"],
    }
    assert get_store(mock_handler_input)["pendingAmbiguity"] is None
    assert get_store(mock_handler_input)["activeDialog"] is None
    assert not TownCaptureHandler().can_handle(mock_handler_input)

    from src.middleware.confirmation import ConfirmationMiddleware
    from src.handlers.dispatch import IntentDispatchHandler


    ConfirmationMiddleware().process(mock_handler_input)
    IntentDispatchHandler().handle(mock_handler_input)
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "Did you mean Walsall Talking Newspaper?" in spoken
    store = get_store(mock_handler_input)
    assert store["activeDialog"]["type"] == "search_confirmation"
    assert store["awaitingLocationConfirm"] is False
    assert store["pendingLocationConfirm"] is None


@pytest.mark.asyncio
async def test_no_declines_ambiguity_confirmation_before_stale_location(
    mock_handler_input,
):
    from src.handlers.yesno import NoIntentHandler


    resolution = {
        "requestId": "resolved-neston",
        "intent": "organization",
        "confirmationLabel": "Ellesmere Port and Neston TN",
        "searchPayload": {
            "query": "",
            "filter": {"organizationIds": ["org-neston"]},
        },
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "intent": {"name": "AMAZON.NoIntent", "slots": {}},
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
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

    await NoIntentHandler().handle(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    store = get_store(mock_handler_input)
    assert "news or sport" in spoken
    assert "Which town" not in spoken
    assert store["pendingResolution"] is None
    assert store["awaitingLocationConfirm"] is False
    assert store["pendingLocationConfirm"] is None


@pytest.mark.asyncio
async def test_yes_executes_ambiguity_resolution_before_stale_location(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.yesno import YesIntentHandler


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
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "intent": {"name": "AMAZON.YesIntent", "slots": {}},
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
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
    monkeypatch.setattr("src.handlers.yesno.auto_play_first_from_search", play)

    response = await YesIntentHandler().handle(mock_handler_input)

    search.assert_awaited_once_with({
        "query": "",
        "filter": {"organizationIds": ["org-neston"]},
        "alexaUserId": "amzn1.ask.account.TEST",
    })
    play.assert_awaited_once()
    assert response == {"shouldEndSession": True}
    store = get_store(mock_handler_input)
    assert store.get("userCity") is None
    assert store["pendingResolution"] is None
    assert store["awaitingLocationConfirm"] is False
    assert store["pendingLocationConfirm"] is None


@pytest.mark.asyncio
async def test_explicit_search_replaces_pending_ambiguity(
    monkeypatch,
    mock_handler_input,
):
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
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "requestId": "fresh-tnf-request",
        "locale": "en-GB",
        "intent": {
            "name": "PlayContentIntent",
            "slots": {"topic": {"name": "topic", "value": "tnf"}},
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
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

    await ResolverInterceptor().process(mock_handler_input)

    assert [call.args for call in resolve.await_args_list] == [("tnf",)]
    store = get_store(mock_handler_input)
    assert store["pendingAmbiguity"] is None
    assert store["activeDialog"] is None
    assert mock_handler_input.attributes_manager.request_attributes["_nlp"][
        "confirmationLabel"
    ] == "content from Talking News Federation"


@pytest.mark.asyncio
async def test_candidate_in_topic_slot_resolves_before_new_search(
    monkeypatch,
    mock_handler_input,
):
    pending = {
        "requestId": "ambiguous-tn",
        "intent": "organization",
        "originalUtterance": "play tn",
        "searchPayload": {"query": "", "filter": {}, "page": 0, "limit": 20},
        "slots": {},
        "candidates": [
            {"type": "organization", "id": "org-bromley", "name": "Bromley TN"},
            {"type": "organization", "id": "org-neston", "name": "Ellesmere Port and Neston TN"},
            {"type": "organization", "id": "org-north", "name": "The Northumbrian"},
        ],
        "expiresAt": 4102444800,
    }
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "requestId": "candidate-topic-request",
        "locale": "en-GB",
        "intent": {
            "name": "PlayContentIntent",
            "slots": {"topic": {"name": "topic", "value": "neston"}},
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "pendingAmbiguity": pending,
        "activeDialog": {
            "type": "ambiguity",
            "context": pending,
            "expiresAt": 4102444800,
        },
    }
    resolve = AsyncMock(return_value={
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
        "entities": [{
            "type": "organization",
            "id": "org-neston",
            "canonicalValue": "Ellesmere Port and Neston TN",
        }],
        "slots": {
            "organizationIds": ["org-neston"],
            "organizationName": "Ellesmere Port and Neston TN",
        },
    })
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor().process(mock_handler_input)

    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["ambiguityResolution"] is True
    assert nlp["searchPayload"]["filter"] == {
        "organizationIds": ["org-neston"],
    }


@pytest.mark.asyncio
async def test_dynamic_entity_id_selects_pending_candidate_without_resolver(
    monkeypatch,
    mock_handler_input,
):
    candidates = [{
        "type": "creator",
        "id": "creator-leader",
        "name": "Pendle Voice Leader and Times",
    }, {
        "type": "creator",
        "id": "creator-dalesman",
        "name": "Pendle Voice Dalesman",
    }]
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
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "intent": {
            "name": "ClarifySelectionIntent",
            "slots": {"selection": {
                "name": "selection",
                "value": "dalesman",
                "resolutions": {
                    "resolutionsPerAuthority": [{
                        "status": {"code": "ER_SUCCESS_MATCH"},
                        "values": [{"value": {
                            "id": "creator-dalesman",
                            "name": "Pendle Voice Dalesman",
                        }}],
                    }],
                },
            }},
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor().process(mock_handler_input)

    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["ambiguityResolution"] is True
    assert nlp["searchPayload"]["filter"] == {
        "creatorIds": ["creator-dalesman"],
    }
    assert get_store(mock_handler_input)["pendingAmbiguity"] is None


@pytest.mark.asyncio
async def test_ordinal_selects_currently_displayed_ambiguity_without_resolver(
    monkeypatch,
    mock_handler_input,
):
    candidates = [{
        "type": "creator",
        "id": f"creator-{index}",
        "name": name,
    } for index, name in enumerate((
        "Pendle Voice Leader and Times",
        "Pendle Voice Dalesman",
        "Pendle Voice Lancashire Life",
    ))]
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
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "intent": {
            "name": "ClarifySelectionIntent",
            "slots": {"selection": {
                "name": "selection",
                "value": "second",
            }},
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "pendingAmbiguity": pending,
        "activeDialog": {"type": "ambiguity", "context": pending},
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor().process(mock_handler_input)

    resolve.assert_not_awaited()
    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["searchPayload"]["filter"] == {"creatorIds": ["creator-1"]}


@pytest.mark.asyncio
async def test_wakefield_reply_uses_legacy_ambiguity_before_onboarding(
    monkeypatch,
    mock_handler_input,
):
    """A WTN clarification reply must never become the listener's town."""
    candidates = [
        {"type": "organization", "id": "org-wakefield", "name": "Wakefield Talking Newspaper"},
        {"type": "organization", "id": "org-walsall", "name": "Walsall Talking Newspaper"},
        {"type": "organization", "id": "org-warrington", "name": "Warrington Talking Newspaper"},
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
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "TownCaptureIntent",
            "slots": {"townName": {"name": "townName", "value": "wakefield"}},
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingStage": "ask_town",
        "pendingAmbiguity": pending,
        "activeDialog": None,
    }
    monkeypatch.setattr(
        ResolverClient, "resolve_utterance",
        AsyncMock(return_value={
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
        }),
    )

    await ResolverInterceptor().process(mock_handler_input)

    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    store = get_store(mock_handler_input)
    assert nlp["intent"] == "organization"
    assert nlp["searchPayload"]["filter"] == {
        "organizationIds": ["org-wakefield"],
    }
    assert store["userCity"] is None
    assert store.get("pendingLocationConfirm") is None
    assert not TownCaptureHandler().can_handle(mock_handler_input)


@pytest.mark.asyncio
async def test_misrouted_unresolved_source_is_not_called_talking_newspaper(
    mock_handler_input,
):
    from src.handlers.play import PlayByOrganizationHandler


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
                    "value": "Orion meta glasses from Paul",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes.update({
        "_store": {**DEFAULT_STORE, "onboardingComplete": True},
        "_nlp": {
            "intent": "general",
            "slots": {
                "residualQuery": "orion meta glasses",
                "unresolvedReferences": [{
                    "relation": "from",
                    "phrase": "paul",
                    "expectedTypes": ["creator", "organization", "publication"],
                }],
            },
        },
    })

    await PlayByOrganizationHandler().handle(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "creator, organisation or publication named paul" in spoken
    assert "talking newspaper" not in spoken
    assert get_store(mock_handler_input)["awaitingOrganizationName"] is False


@pytest.mark.asyncio
async def test_generic_talking_newspaper_request_prompts_and_persists_context(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.play import PlayByOrganizationHandler


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
        "src.handlers.play.discover_content_via_search", discover,
    )

    await PlayByOrganizationHandler().handle(mock_handler_input)

    assert get_store(mock_handler_input)["awaitingOrganizationName"] is True
    chained_builder = (
        mock_handler_input.response_builder.speak.return_value
        .reprompt.return_value
    )
    chained_builder.add_directive.assert_called_once()
    directive = chained_builder.add_directive.call_args.args[0]
    assert directive == {
        "type": "Dialog.ElicitSlot",
        "slotToElicit": "organizationQuery",
    }
    json.dumps(directive)
    discover.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_talking_newspaper_pipeline_prompts_when_slot_has_no_value(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.dispatch import IntentDispatchHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayByOrganizationIntent",
            "slots": {
                "organizationQuery": {
                    "name": "organizationQuery",
                    "confirmationStatus": "NONE",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()

    await ResolverInterceptor().process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    response = await IntentDispatchHandler().handle(mock_handler_input)

    assert "Which talking newspaper would you like" in response["outputSpeech"]["ssml"]
    assert get_store(mock_handler_input)["awaitingOrganizationName"] is True
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_talking_newspaper_slot_value_still_prompts_for_name(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.dispatch import IntentDispatchHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayByOrganizationIntent",
            "slots": {
                "organizationQuery": {
                    "name": "organizationQuery",
                    "value": "talking newspaper",
                    "confirmationStatus": "NONE",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()

    await ResolverInterceptor().process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    response = await IntentDispatchHandler().handle(mock_handler_input)

    assert "Which talking newspaper would you like" in response["outputSpeech"]["ssml"]
    assert get_store(mock_handler_input)["awaitingOrganizationName"] is True
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_misrouted_talking_newspaper_play_content_prompts_for_name(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.dispatch import IntentDispatchHandler
    from src.middleware.confirmation import (
        ConfirmationMiddleware,
        SearchConfirmationGateHandler,
    )

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayContentIntent",
            "slots": {
                "topic": {
                    "name": "topic",
                    "value": "talking newspaper",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()

    await ResolverInterceptor().process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    assert SearchConfirmationGateHandler().can_handle(mock_handler_input) is False
    response = await IntentDispatchHandler().handle(mock_handler_input)

    assert "Which talking newspaper would you like" in response["outputSpeech"]["ssml"]
    assert get_store(mock_handler_input)["awaitingOrganizationName"] is True
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_creator_pipeline_asks_for_creator_name(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.dispatch import IntentDispatchHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayByCreatorIntent",
            "slots": {
                "creatorQuery": {
                    "name": "creatorQuery",
                    "value": "a creator",
                    "confirmationStatus": "NONE",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()

    await ResolverInterceptor().process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    response = await IntentDispatchHandler().handle(mock_handler_input)

    assert "Which creator would you like to hear" in response["outputSpeech"]["ssml"]
    assert response["directives"] == [{
        "type": "Dialog.ElicitSlot",
        "slotToElicit": "creatorQuery",
    }]
    assert response["shouldEndSession"] is False
    assert get_store(mock_handler_input)["awaitingCreatorName"] is True
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_publication_pipeline_prompts_when_slot_has_no_value(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.dispatch import IntentDispatchHandler
    from src.middleware.confirmation import ConfirmationMiddleware

    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {
            "name": "PlayPublicationIntent",
            "slots": {
                "publicationSourceQuery": {
                    "name": "publicationSourceQuery",
                    "confirmationStatus": "NONE",
                },
            },
        },
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
    }
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    mock_handler_input.response_builder = ResponseBuilder()

    await ResolverInterceptor().process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    response = IntentDispatchHandler().handle(mock_handler_input)

    assert "Which publication, creator, or organization would you like" in response["outputSpeech"]["ssml"]
    resolve.assert_not_awaited()


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
        ResolverClient, "resolve_utterance",
        AsyncMock(return_value={"version": 1, "status": "resolved", **resolved}),
    )

    await ResolverInterceptor().process(mock_handler_input)

    nlp = mock_handler_input.attributes_manager.request_attributes["_nlp"]
    assert nlp["intent"] == "organization"
    assert nlp["slots"]["organizationIds"] == ["org-ytn"]
    assert nlp["slots"]["organizationQuery"] == "ynt"
    assert nlp["slots"]["organizationFollowUp"] is True


@pytest.mark.asyncio
async def test_resolved_talking_newspaper_follow_up_requires_confirmation(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.play import PlayByOrganizationHandler


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
    resolved_slots = {
        "organizationIds": ["org-ytn"],
        "organizationName": "York Talking News",
        "organizationQuery": "ynt",
        "organizationFollowUp": True,
        "residualQuery": "",
    }
    mock_handler_input.attributes_manager.request_attributes.update({
        "_store": {
            **DEFAULT_STORE,
            "onboardingComplete": True,
            "awaitingOrganizationName": True,
        },
        "_nlp": {
            "intent": "organization",
            "slots": resolved_slots,
        },
    })
    discover = AsyncMock()
    monkeypatch.setattr(
        "src.handlers.play.discover_content_via_search", discover,
    )

    await PlayByOrganizationHandler().handle(mock_handler_input)

    store = get_store(mock_handler_input)
    assert store["awaitingOrganizationName"] is False
    assert store["awaitingSearchConfirmation"] is True
    assert store["pendingResolution"]["intent"] == "organization"
    assert store["pendingResolution"]["confirmationLabel"] == (
        "content from York Talking News"
    )
    discover.assert_not_awaited()


@pytest.mark.asyncio
async def test_location_follow_up_yes_executes_community_search(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.yesno import YesIntentHandler


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
        "src.handlers.yesno.discover_content_via_search",
        discover,
    )
    monkeypatch.setattr(
        "src.handlers.yesno.auto_play_first_from_search",
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


@pytest.mark.asyncio
async def test_location_confirmation_finishes_onboarding_without_forcing_empty_search(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.yesno import YesIntentHandler


    handler_input = _town_request(mock_handler_input, "swidon")
    store = get_store(handler_input)
    store.update({
        "onboardingStage": "await_location_confirm",
        "awaitingLocationConfirm": True,
        "pendingLocationConfirm": {
            "city": "Swindon",
            "locality": "Swindon",
            "countryCode": "GB",
            "latitude": 51.5558,
            "longitude": -1.7797,
        },
    })
    handler_input.attributes_manager.request_attributes["_store"] = store
    sync = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(HearApiClient, "sync_listener", sync)

    await YesIntentHandler()._confirm_location(handler_input, store)

    updated = get_store(handler_input)
    assert updated["onboardingComplete"] is True
    assert updated["userCity"] == "Swindon"
    assert updated["locationSource"] == "manual"
    assert updated["awaitingCommunityPlayback"] is True
    assert updated["_requiresReliableSave"] is True
    session = handler_input.attributes_manager.set_session_attributes.call_args.args[0]
    assert session["onboardingStage"] is None
    assert session["onboardingComplete"] is True
    assert session["awaitingLocationConfirm"] is False
    assert session["awaitingCommunityPlayback"] is True
    assert session["userCity"] == "Swindon"
    spoken = handler_input.response_builder.speak.call_args.args[0]
    assert "I've set your location to Swindon" in spoken
    assert "What would you like to hear?" in spoken
    assert "Would you like to hear the latest from Swindon" in spoken
    sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_location_follow_up_survives_missing_persistence_in_same_session(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.yesno import YesIntentHandler
    from src.middleware.onboarding_gate import OnboardingGateHandler

    handler_input = _town_request(mock_handler_input, "yes")
    handler_input.request_envelope.request.intent.name = "AMAZON.YesIntent"
    handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
    }
    session = {
        "onboardingComplete": True,
        "awaitingCommunityPlayback": True,
        "userCity": "York",
        "locality": "York",
    }
    handler_input.attributes_manager.get_session_attributes = lambda: session
    handler_input.attributes_manager.set_session_attributes = lambda value: session.update(value)
    discover = AsyncMock(return_value={
        "failed": False,
        "results": [{
            "contentId": "content-york",
            "title": "York update",
            "audioUrl": "https://cdn.hear.media/content-york.mp3",
        }],
    })
    play = AsyncMock(return_value={"response": "playing"})
    monkeypatch.setattr("src.handlers.yesno.discover_content_via_search", discover)
    monkeypatch.setattr("src.handlers.yesno.auto_play_first_from_search", play)

    assert OnboardingGateHandler().can_handle(handler_input) is False
    response = await YesIntentHandler().handle(handler_input)

    assert response == {"response": "playing"}
    assert handler_input.attributes_manager.request_attributes["_nlp"]["slots"]["city"] == "York"
    assert session["awaitingCommunityPlayback"] is False
