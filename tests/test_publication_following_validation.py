from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.alexa.dialog import DialogStateManager
from src.alexa.runtime import AttrDict
from src.alexa.search import Search
from src.clients.resolver import ResolverClient
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.middleware.confirmation import ConfirmationMiddleware
from src.models.resolver_workflow import ResolverWorkflow
from src.models.social import FollowCommand, FollowingManager
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
    await ApplicationContainer().build_resolver_interceptor().process(mock_handler_input)
    await ConfirmationMiddleware().process(mock_handler_input)
    resolve.assert_not_awaited()
    attrs = mock_handler_input.attributes_manager.request_attributes
    assert attrs["_nlp"]["slots"]["genericPublicationRequest"] is True
    assert attrs["_nlp"]["slots"]["dateQuery"] == "2026-08-02"
    assert attrs["_nlp"]["slots"]["publicationSort"] == "latest"
    response = await ApplicationContainer().build_request_play_content(mock_handler_input).execute(mock_handler_input)
    assert response is not None
    store = User.snapshot(mock_handler_input)
    assert store["awaitingPublicationSource"] is True
    assert store["activeDialog"]["type"] == "publication_source"
    directive = DialogStateManager.capture_directive("publication_source")
    assert directive["updatedIntent"]["name"] == "SelectPublicationSourceIntent"
    assert directive["slotToElicit"] == "publicationSourceQuery"


def test_followed_source_history_is_not_loaded_from_persistence():
    store = User.merge_persisted(
        {
            "followedCreators": [
                {"id": "creator-1", "name": "Creator One"},
                {"id": "creator-1", "name": "Creator One"},
                {"id": "org-1", "name": "York Talking News", "type": "organization"},
            ]
        }
    )
    assert store["followedCreators"] == []
    assert not FollowingManager.is_following(store, "creator-1", "creator")
    assert not FollowingManager.is_following(store, "org-1", "organization")


def test_follow_command_rejects_missing_source_or_unsupported_type():
    with pytest.raises(ValueError, match="source id and name"):
        FollowCommand("", "Creator")
    with pytest.raises(ValueError, match="supported source type"):
        FollowCommand("creator-1", "Creator", "publisher")


def test_social_model_has_no_alexa_or_request_state_dependency():
    source = (Path(__file__).parents[1] / "src/models/social.py").read_text(
        encoding="utf-8"
    )
    assert "src.alexa" not in source
    assert "RequestContext" not in source
    assert "handler_input" not in source
    assert "src.models.user" not in source


def test_followed_creator_and_organization_with_same_id_are_distinct():
    followed, _ = FollowingManager.add(
        [], FollowCommand("source-1", "Creator", "creator")
    )
    followed, _ = FollowingManager.add(
        followed, FollowCommand("source-1", "Organization", "organization")
    )
    assert {(item["type"], item["id"]) for item in followed} == {
        ("creator", "source-1"),
        ("organization", "source-1"),
    }


@pytest.mark.parametrize(
    "spoken, normalized",
    [
        ("the first one", "first"),
        ("the second choice", "second"),
        ("number two", "two"),
        ("play the first one", "first"),
        ("pick option two", "two"),
        ("select choice 3", "3"),
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
    container = ApplicationContainer(heara=hear)
    await Search.play_from_followed_creators(
        mock_handler_input,
        user=container.user,
        heara=container.heara,
        progressive=container.progressive,
        browse=container.browse,
        playback=container.playback,
    )
    payload = hear.search.await_args.args[0]
    assert payload["filter"]["creatorIds"] == ["creator-1"]
    assert payload["filter"]["organizationIds"] == ["org-1"]
