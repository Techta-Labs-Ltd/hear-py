from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock

import pytest

from src.resolver.engine import resolver
from src.resolver.correction import command_corrector
from src.resolver.lambda_handler import handler
from src.resolver.taxonomy import TaxonomyRecord, TaxonomySnapshot, taxonomy_manager
from src.services.storage.persistence import DEFAULT_STORE, get_store


class _InvokeClient:
    def __init__(self, body, *, function_error=None):
        self.body = body
        self.function_error = function_error

    def invoke(self, **_kwargs):
        return {
            "FunctionError": self.function_error,
            "Payload": io.BytesIO(json.dumps(self.body).encode("utf-8")),
        }


@pytest.fixture
def resolver_snapshot(monkeypatch):
    snapshot = TaxonomySnapshot("resolver-test", [
        TaxonomyRecord("category", "sport", slug="sport"),
        TaxonomyRecord(
            "organization",
            "York Talking News",
            entity_id="63915f39-db54-4001-9877-7d2b3fc36639",
            aliases=("ytn",),
        ),
    ])
    monkeypatch.setattr(taxonomy_manager, "_snapshot", snapshot)
    monkeypatch.setattr(resolver.taxonomy, "_snapshot", snapshot)
    return snapshot


def test_contextual_form_typo_resolves_complete_filter(resolver_snapshot):
    result = handler({
        "version": 1,
        "requestId": "request-1",
        "operation": "resolve_search",
        "utterance": "play the latest sport form ytn",
        "alexaIntent": "PlayContentIntent",
    })

    assert result["status"] == "resolved"
    assert result["normalizedUtterance"] == "play the latest sport from ytn"
    assert result["corrections"] == [{
        "original": "form",
        "replacement": "from",
        "type": "contextual",
    }]
    assert result["confirmationLabel"] == (
        "the latest sport from York Talking News"
    )
    assert result["searchPayload"]["filter"] == {
        "categorySlugs": ["sport"],
        "organizationIds": ["63915f39-db54-4001-9877-7d2b3fc36639"],
    }
    assert result["searchPayload"]["sort"] == "latest"


def test_misspelled_initial_command_still_resolves_ambiguous_source():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "playt wtn",
    })

    assert result["normalizedUtterance"] == "play wtn"
    assert result["corrections"] == [{
        "original": "playt",
        "replacement": "play",
        "type": "contextual",
    }]
    assert result["status"] == "ambiguous"
    assert result["searchPayload"]["query"] == ""


def test_command_correction_is_model_derived_and_semantically_checked(
    monkeypatch,
    resolver_snapshot,
):
    from src.services.semantic_routing import SemanticDecision

    monkeypatch.setattr(
        "src.resolver.correction.semantic_intent_router.route",
        lambda *_args, **_kwargs: SemanticDecision("organization", 0.91),
    )

    result = command_corrector.correct(
        "play the latrest sport form ytn",
        resolver_snapshot,
    )

    assert result.utterance == "play the latest sport from ytn"
    assert {item["replacement"] for item in result.corrections} == {"latest", "from"}
    assert {item["type"] for item in result.corrections} == {"semantic_contextual"}


def test_command_correction_does_not_rewrite_free_text_topic(resolver_snapshot):
    result = command_corrector.correct(
        "play something on heatwave from ytn",
        resolver_snapshot,
    )

    assert result.utterance == "play something on heatwave from ytn"
    assert result.corrections == ()


def test_exact_category_keeps_following_description_as_query():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play the latest sport briefing update",
    })

    assert result["confirmationLabel"] == (
        "the latest sport briefing update"
    )
    assert result["searchPayload"]["query"] == "briefing update"
    assert result["searchPayload"]["filter"]["categorySlugs"] == ["sport"]
    assert result["searchPayload"]["sort"] == "latest"


def test_duplicated_source_slot_text_is_not_confirmable():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "sport adeshina from sport from adeshina",
    })

    assert result["status"] == "unresolved"
    assert result["unresolvedReferences"]


def test_unresolved_source_is_removed_from_residual_topic_query():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play something on orion meta glasses from paul",
    })

    assert result["status"] == "unresolved"
    assert result["searchPayload"]["query"] == "orion meta glasses"
    assert result["unresolvedReferences"] == [{
        "relation": "from",
        "phrase": "paul",
        "expectedTypes": ["creator", "organization", "publication"],
    }]


def test_my_community_uses_listener_local_search_without_category_or_query():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play something from my community",
        "alexaIntent": "PlayLocalIntent",
        "alexaUserId": "listener-1",
    })

    assert result["status"] == "resolved"
    assert result["intent"] == "local"
    assert result["confirmationLabel"] == "content from your community"
    assert result["searchPayload"] == {
        "alexaUserId": "listener-1",
        "isLocal": True,
        "isRecommended": False,
        "limit": 20,
        "page": 0,
        "query": "",
        "sort": "nearest",
    }


def test_named_city_search_is_not_listener_local_search():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play something in manchester",
        "alexaIntent": "PlayLocalIntent",
        "alexaUserId": "listener-1",
    })

    assert result["status"] == "resolved"
    assert result["searchPayload"]["isLocal"] is False
    assert result["searchPayload"]["filter"]["city"] == "Manchester"
    assert result["confirmationLabel"] == "content in Manchester"


def test_lates_sport_from_london_corrects_and_confirms_every_constraint():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play the lates sport from london",
    })

    assert result["status"] == "resolved"
    assert result["normalizedUtterance"] == (
        "play the latest sport from london"
    )
    assert result["corrections"] == [{
        "original": "lates",
        "replacement": "latest",
        "type": "contextual",
    }]
    assert result["confirmationLabel"] == "the latest sport in London"
    assert result["searchPayload"]["filter"] == {
        "categorySlugs": ["sport"],
        "city": "London",
        "latitude": 51.5072,
        "longitude": -0.1275,
        "countryCode": "gb",
    }
    assert result["searchPayload"]["sort"] == "latest"


def test_sport_update_in_london_is_not_duplicated_or_called_a_source():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play me the latest sport update in london",
    })

    assert result["status"] == "resolved"
    assert result["confirmationLabel"] == (
        "the latest sport update in London"
    )
    assert result["searchPayload"]["query"] == "update"
    assert result["searchPayload"]["filter"] == {
        "categorySlugs": ["sport"],
        "city": "London",
        "latitude": 51.5072,
        "longitude": -0.1275,
        "countryCode": "gb",
    }


def test_location_name_is_not_also_applied_as_a_tag():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play the latest sound recording in burnley",
    })

    assert result["confirmationLabel"] == (
        "the latest sound recording in Burnley"
    )
    assert result["searchPayload"]["filter"] == {
        "categorySlugs": ["sound-recording"],
        "city": "Burnley",
        "latitude": 53.789,
        "longitude": -2.248,
        "countryCode": "gb",
    }


def test_words_inside_full_organization_name_do_not_add_a_category():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play Barking and Dagenham Talking Newspaper",
    })

    assert result["intent"] == "organization"
    assert result["confirmationLabel"] == (
        "content from Barking and Dagenham Talking Newspaper"
    )
    assert result["searchPayload"]["filter"] == {
        "organizationIds": ["012e0329-f6ad-48d9-8713-13ecee671f64"],
    }


@pytest.mark.parametrize(
    "utterance,label,query,category",
    (
        (
            "what's the latest music from ytn",
            "the latest music from York Talking News",
            "",
            "music",
        ),
        (
            "what's the latest sport update from ytn",
            "the latest sport update from York Talking News",
            "update",
            "sport",
        ),
        (
            "what is the latest sport update from ytn",
            "the latest sport update from York Talking News",
            "update",
            "sport",
        ),
    ),
)
def test_constrained_whats_latest_uses_resolved_search_contract(
    utterance,
    label,
    query,
    category,
):
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": utterance,
        "alexaIntent": "WhatsTrendingIntent",
    })

    assert result["status"] == "resolved"
    assert result["intent"] == "category"
    assert result["confirmationLabel"] == label
    assert result["searchPayload"]["query"] == query
    assert result["searchPayload"]["filter"] == {
        "categorySlugs": [category],
        "organizationIds": ["63915f39-db54-4001-9877-7d2b3fc36639"],
    }
    assert result["searchPayload"]["sort"] == "latest"


def test_what_in_a_real_topic_is_not_removed_as_command_language():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play what matters from ytn",
    })

    assert result["searchPayload"]["query"] == "what matters"


def test_duplicate_creator_ids_resolve_as_one_spoken_creator():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play the latest news from adeshina",
    })

    assert result["status"] == "resolved"
    assert result["confirmationLabel"] == (
        "the latest news from Adeshina Ayomide"
    )
    assert len(result["searchPayload"]["filter"]["creatorIds"]) == 2


def test_short_category_asr_error_uses_combined_context():
    result = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play the latest new from adeshina",
    })

    assert result["status"] == "resolved"
    assert result["confirmationLabel"] == (
        "the latest news from Adeshina Ayomide"
    )
    assert result["searchPayload"]["filter"]["categorySlugs"] == ["news"]


def test_ambiguity_follow_up_stays_with_offered_candidates():
    initial = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play sussex",
    })
    candidates = initial["ambiguities"][0]["candidates"][:3]
    context = {
        "searchPayload": initial["searchPayload"],
        "slots": initial["slots"],
        "candidates": candidates,
    }

    still_ambiguous = handler({
        "version": 1,
        "operation": "resolve_ambiguity_follow_up",
        "utterance": "sussex coast",
        "context": context,
    })
    resolved = handler({
        "version": 1,
        "operation": "resolve_ambiguity_follow_up",
        "utterance": "talking news",
        "context": context,
    })

    assert still_ambiguous["status"] == "ambiguous"
    assert len(still_ambiguous["ambiguities"][0]["candidates"]) == 3
    assert resolved["status"] == "resolved"
    assert resolved["confirmationLabel"] == (
        "content from Sussex Coast Talking News"
    )
    assert resolved["searchPayload"]["filter"]["organizationIds"] == [
        "60bfdbda-ab55-48d4-94a6-c8998435678b"
    ]


def test_repeated_ambiguous_alias_preserves_candidates_for_next_answer():
    initial = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play wtn",
    })
    candidates = initial["ambiguities"][0]["candidates"][:3]
    context = {
        "intent": initial["intent"],
        "searchPayload": initial["searchPayload"],
        "slots": {
            **initial["slots"],
            "ambiguousReferences": [{"phrase": "wtn", "candidates": candidates}],
        },
        "candidates": candidates,
    }

    repeated = handler({
        "version": 1,
        "operation": "resolve_ambiguity_follow_up",
        "utterance": "wtn",
        "context": context,
    })
    selected = handler({
        "version": 1,
        "operation": "resolve_ambiguity_follow_up",
        "utterance": "walsall",
        "context": {**context, "candidates": repeated["ambiguities"][0]["candidates"]},
    })

    assert repeated["status"] == "ambiguous"
    assert repeated["ambiguities"][0]["candidates"] == candidates
    assert selected["status"] == "resolved"
    assert selected["confirmationLabel"] == (
        "content from Walsall Talking Newspaper"
    )


def test_misspelled_distinguishing_word_selects_offered_candidate():
    initial = handler({
        "version": 1,
        "operation": "resolve_search",
        "utterance": "play wtn",
    })
    candidates = initial["ambiguities"][0]["candidates"][:3]
    selected = handler({
        "version": 1,
        "operation": "resolve_ambiguity_follow_up",
        "utterance": "wasall",
        "context": {
            "intent": "organization",
            "searchPayload": initial["searchPayload"],
            "slots": initial["slots"],
            "candidates": candidates,
        },
    })

    assert selected["status"] == "resolved"
    assert selected["confirmationLabel"] == (
        "content from Walsall Talking Newspaper"
    )
    assert selected["searchPayload"]["filter"]["organizationIds"] == [
        "ddce8ea4-d9a4-4b7b-b5c8-30ed5b89174e"
    ]


def test_resolver_client_rejects_malformed_contract(monkeypatch):
    from src.services import resolver_client

    monkeypatch.setattr(
        resolver_client.settings,
        "HEAR_RESOLVER_FUNCTION_ARN",
        "arn:aws:lambda:eu-west-1:123456789012:function:resolver:live",
    )
    monkeypatch.setattr(
        resolver_client,
        "_lambda_client",
        lambda: _InvokeClient({"status": "resolved"}),
    )

    with pytest.raises(resolver_client.ResolverUnavailable):
        resolver_client._invoke({"version": 1})


def test_resolver_client_rejects_lambda_function_error(monkeypatch):
    from src.services import resolver_client

    monkeypatch.setattr(
        resolver_client.settings,
        "HEAR_RESOLVER_FUNCTION_ARN",
        "arn:aws:lambda:eu-west-1:123456789012:function:resolver:live",
    )
    monkeypatch.setattr(
        resolver_client,
        "_lambda_client",
        lambda: _InvokeClient({"errorMessage": "boom"}, function_error="Unhandled"),
    )

    with pytest.raises(resolver_client.ResolverUnavailable):
        resolver_client._invoke({"version": 1})


@pytest.mark.asyncio
async def test_yes_executes_exact_pending_resolver_payload(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.intents.system import YesIntentHandler

    payload = {
        "query": "",
        "filter": {
            "categorySlugs": ["sport"],
            "organizationIds": ["org-ytn"],
        },
        "sort": "latest",
        "page": 0,
        "limit": 20,
    }
    store = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingSearchConfirmation": True,
        "pendingResolution": {
            "requestId": "resolution-1",
            "intent": "category",
            "confirmationLabel": "the latest sport from York Talking News",
            "searchPayload": payload,
            "resolvedEntities": [],
            "createdAt": 1,
            "expiresAt": 4102444800,
        },
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = store
    search = AsyncMock(return_value={
        "failed": False,
        "results": [{"contentId": "content-1", "audioUrl": "https://example.com/a.mp3"}],
        "total_hits": 1,
    })
    play = AsyncMock(return_value={"playing": True})
    monkeypatch.setattr("src.handlers.intents.system.search", search)
    monkeypatch.setattr("src.handlers.intents.system.auto_play_first_from_search", play)

    response = await YesIntentHandler()._handle_search_confirmation(
        mock_handler_input, store, {},
    )

    assert response == {"playing": True}
    search.assert_awaited_once_with(payload)
    assert get_store(mock_handler_input)["pendingResolution"] is None


@pytest.mark.asyncio
async def test_yes_prefers_recent_search_confirmation_over_stale_resume(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.intents.system import YesIntentHandler

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
    store = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingResume": True,
        "awaitingSearchConfirmation": True,
        "pendingResolution": {
            "requestId": "resolution-priority",
            "intent": "category",
            "confirmationLabel": "the latest sport update from York Talking News",
            "searchPayload": payload,
            "resolvedEntities": [],
            "createdAt": 1,
            "expiresAt": 4102444800,
        },
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = store
    search = AsyncMock(return_value={
        "failed": False,
        "results": [{"contentId": "content-1", "audioUrl": "https://example.com/a.mp3"}],
        "total_hits": 1,
    })
    play = AsyncMock(return_value={"playing": True})
    resume = AsyncMock(return_value={"resuming": True})
    monkeypatch.setattr("src.handlers.intents.system.search", search)
    monkeypatch.setattr("src.handlers.intents.system.auto_play_first_from_search", play)
    monkeypatch.setattr(YesIntentHandler, "_handle_resume_yes", resume)

    response = await YesIntentHandler().handle(mock_handler_input)

    assert response == {"playing": True}
    search.assert_awaited_once_with(payload)
    resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_combined_results_offers_confirmed_source_only_relaxation(
    monkeypatch,
    mock_handler_input,
):
    from src.handlers.intents.system import YesIntentHandler

    store = {
        **DEFAULT_STORE,
        "onboardingComplete": True,
        "awaitingSearchConfirmation": True,
        "pendingResolution": {
            "requestId": "resolution-2",
            "intent": "category",
            "confirmationLabel": "the latest sport from York Talking News",
            "searchPayload": {
                "query": "",
                "filter": {
                    "categorySlugs": ["sport"],
                    "organizationIds": ["org-ytn"],
                },
                "sort": "latest",
                "page": 0,
                "limit": 20,
            },
            "resolvedEntities": [{
                "type": "organization",
                "canonicalValue": "York Talking News",
            }],
            "createdAt": 1,
            "expiresAt": 4102444800,
        },
    }
    mock_handler_input.attributes_manager.request_attributes["_store"] = store
    monkeypatch.setattr(
        "src.handlers.intents.system.search",
        AsyncMock(return_value={"failed": False, "results": [], "total_hits": 0}),
    )

    await YesIntentHandler()._handle_search_confirmation(
        mock_handler_input, store, {},
    )

    pending = get_store(mock_handler_input)["pendingResolution"]
    assert pending["searchPayload"]["filter"] == {
        "organizationIds": ["org-ytn"],
    }
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "couldn't find any sport from York Talking News" in spoken
    assert "latest recordings from York Talking News instead" in spoken
