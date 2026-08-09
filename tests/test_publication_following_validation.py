from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.clients.resolver import ResolverClient
from src.middleware.confirmation import ConfirmationMiddleware
from src.middleware.resolver import ResolverInterceptor
from src.middleware.resolver import _normalize_ordinal
from src.dependencies import Dependencies
from src.handlers.search import play_from_followed_creators
from src.runtime import AttrDict
from src.services.following import add_followed_creator, is_following
from src.services.persistence import merge_initial_store
from src.services.store import DEFAULT_STORE


def _publication_request(handler_input, source=None, *, date=None, sort=None):
    slots = {
        "publicationSourceQuery": {
            "name": "publicationSourceQuery",
            "value": source,
        },
        "dateQuery": {"name": "dateQuery", "value": date},
        "publicationSort": {"name": "publicationSort", "value": sort},
    }
    handler_input.request_envelope = AttrDict(handler_input.request_envelope)
    handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "locale": "en-GB",
        "intent": {"name": "PlayPublicationIntent", "slots": slots},
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [None, "anything", "publication", "play", "find"])
async def test_incomplete_publication_source_skips_resolver_and_elicits_name(
    monkeypatch,
    mock_handler_input,
    source,
):
    _publication_request(mock_handler_input, source, date="2026-08-02", sort="latest")
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)

    await ResolverInterceptor().process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)

    resolve.assert_not_awaited()
    attrs = mock_handler_input.attributes_manager.request_attributes
    assert attrs["_nlp"]["publicationSourceRequired"] is True
    assert attrs["_nlp"]["slots"]["dateQuery"] == "2026-08-02"
    assert attrs["_nlp"]["slots"]["publicationSort"] == "latest"
    assert attrs["_resolverClarification"]["elicitSlot"] == "publicationSourceQuery"


def test_followed_source_migration_types_legacy_creators_and_deduplicates():
    store = merge_initial_store({
        "followedCreators": [
            {"id": "creator-1", "name": "Creator One"},
            {"id": "creator-1", "name": "Creator One"},
            {"id": "org-1", "name": "York Talking News", "type": "organization"},
        ],
    })

    assert store["followedCreators"] == [
        {"id": "creator-1", "name": "Creator One", "type": "creator"},
        {"id": "org-1", "name": "York Talking News", "type": "organization"},
    ]
    assert is_following(store, "creator-1", "creator")
    assert is_following(store, "org-1", "organization")


def test_followed_creator_and_organization_with_same_id_are_distinct(mock_handler_input):
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
    }
    add_followed_creator(mock_handler_input, "source-1", "Creator", "creator")
    add_followed_creator(mock_handler_input, "source-1", "Organization", "organization")

    followed = mock_handler_input.attributes_manager.request_attributes["_store"]["followedCreators"]
    assert {(item["type"], item["id"]) for item in followed} == {
        ("creator", "source-1"),
        ("organization", "source-1"),
    }


@pytest.mark.parametrize("spoken, normalized", [
    ("the first one", "first"),
    ("the second choice", "second"),
    ("number two", "number two"),
    ("3rd option", "third"),
])
def test_ordinal_phrases_are_normalized(spoken, normalized):
    assert _normalize_ordinal(spoken) == normalized


@pytest.mark.asyncio
async def test_followed_content_search_uses_creator_and_organization_filters(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "intent": {"name": "PlayContentIntent", "slots": {}},
    })
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        "followedCreators": [
            {"id": "creator-1", "name": "Creator", "type": "creator"},
            {"id": "org-1", "name": "Organization", "type": "organization"},
        ],
    }
    mock_handler_input.attributes_manager.request_attributes["_nlp"] = {
        "intent": "following",
        "slots": {},
    }
    hear = AsyncMock()
    hear.search.return_value = {
        "results": [], "total_hits": 0, "total_pages": 1, "page": 0,
    }

    await play_from_followed_creators(
        mock_handler_input,
        deps=Dependencies(heara=hear),
    )

    payload = hear.search.await_args.args[0]
    assert payload["filter"]["creatorIds"] == ["creator-1"]
    assert payload["filter"]["organizationIds"] == ["org-1"]
