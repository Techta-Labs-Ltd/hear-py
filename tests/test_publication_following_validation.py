from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.alexa.runtime import AttrDict
from src.clients.resolver import ResolverClient
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.middleware.confirmation import ConfirmationMiddleware
from src.middleware.resolver import ResolverInterceptor
from src.models.resolver_workflow import ResolverWorkflow
from src.models.search import Search
from src.models.social import FollowingManager
from src.models.user import User


def _publication_request(handler_input, source=None, *, date=None, sort=None):
    slots = {
        "publicationSourceQuery": {"name": "publicationSourceQuery", "value": source},
        "dateQuery": {"name": "dateQuery", "value": date},
        "publicationSort": {"name": "publicationSort", "value": sort},
    }
    handler_input.request_envelope = AttrDict(handler_input.request_envelope)
    handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "PlayPublicationIntent", "slots": slots},
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [None, "anything", "publication", "play", "find"])
async def test_incomplete_publication_source_skips_resolver_and_elicits_name(
    monkeypatch, mock_handler_input, source
):
    _publication_request(mock_handler_input, source, date="2026-08-02", sort="latest")
    resolve = AsyncMock()
    monkeypatch.setattr(ResolverClient, "resolve_utterance", resolve)
    await ResolverInterceptor(deps=ApplicationContainer()).process(mock_handler_input)
    ConfirmationMiddleware().process(mock_handler_input)
    resolve.assert_not_awaited()
    attrs = mock_handler_input.attributes_manager.request_attributes
    assert attrs["_nlp"]["publicationSourceRequired"] is True
    assert attrs["_nlp"]["slots"]["dateQuery"] == "2026-08-02"
    assert attrs["_nlp"]["slots"]["publicationSort"] == "latest"
    assert attrs["_resolverClarification"]["elicitSlot"] == "publicationSourceQuery"


def test_followed_source_migration_types_legacy_creators_and_deduplicates():
    store = User.merge_persisted(
        {
            "followedCreators": [
                {"id": "creator-1", "name": "Creator One"},
                {"id": "creator-1", "name": "Creator One"},
                {"id": "org-1", "name": "York Talking News", "type": "organization"},
            ]
        }
    )
    assert store["followedCreators"] == [
        {"id": "creator-1", "name": "Creator One", "type": "creator"},
        {"id": "org-1", "name": "York Talking News", "type": "organization"},
    ]
    assert FollowingManager.is_following(store, "creator-1", "creator")
    assert FollowingManager.is_following(store, "org-1", "organization")


def test_followed_creator_and_organization_with_same_id_are_distinct(
    mock_handler_input,
):
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE
    }
    FollowingManager.add(mock_handler_input, "source-1", "Creator", "creator")
    FollowingManager.add(mock_handler_input, "source-1", "Organization", "organization")
    followed = mock_handler_input.attributes_manager.request_attributes["_store"][
        "followedCreators"
    ]
    assert {(item["type"], item["id"]) for item in followed} == {
        ("creator", "source-1"),
        ("organization", "source-1"),
    }


@pytest.mark.parametrize(
    "spoken, normalized",
    [
        ("the first one", "first"),
        ("the second choice", "second"),
        ("number two", "number two"),
        ("3rd option", "third"),
    ],
)
def test_ordinal_phrases_are_normalized(spoken, normalized):
    assert ResolverWorkflow._normalize_ordinal(spoken) == normalized


@pytest.mark.asyncio
async def test_followed_content_search_uses_creator_and_organization_filters(
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {"type": "IntentRequest", "intent": {"name": "PlayContentIntent", "slots": {}}}
    )
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
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
        "results": [],
        "total_hits": 0,
        "total_pages": 1,
        "page": 0,
    }
    await Search.play_from_followed_creators(
        mock_handler_input, deps=ApplicationContainer(heara=hear)
    )
    payload = hear.search.await_args.args[0]
    assert payload["filter"]["creatorIds"] == ["creator-1"]
    assert payload["filter"]["organizationIds"] == ["org-1"]
