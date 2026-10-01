from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.alexa.following_state import FollowingSessionState
from src.alexa.resolver_runner import ResolverWorkflowRunner
from src.alexa.search import Search
from src.constants.state import StateSchema
from src.middleware.direct_intent import DirectIntentPhraseInterceptor
from src.models.listener import IdentityContext, PrincipalType
from src.models.user import User
from src.services.listener_repository import Listener
from src.services.listener_sync import ListenerSyncService


def _bind_session(handler_input, session: dict) -> None:
    handler_input.attributes_manager.get_session_attributes = lambda: session

    def set_session(value: dict) -> None:
        session.clear()
        session.update(value)

    handler_input.attributes_manager.set_session_attributes = set_session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phrase", "target"),
    (
        ("folw ths cretr", "FollowCreatorIntent"),
        ("flw crtr", "FollowCreatorIntent"),
        ("subscrbe ths cretr", "FollowCreatorIntent"),
        ("unfolw ths cretr", "UnfollowCreatorIntent"),
        ("unflw crtr", "UnfollowCreatorIntent"),
        ("stop folowing ths cretr", "UnfollowCreatorIntent"),
    ),
)
async def test_noisy_social_commands_are_rerouted_before_search(
    mock_intent_request,
    phrase,
    target,
):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "SearchContentIntent"
    intent["slots"] = {
        "searchQuery": {"name": "searchQuery", "value": phrase},
    }

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    assert intent["name"] == target
    assert ResolverWorkflowRunner._request(mock_intent_request) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase",
    ("flower gardening", "creator news", "football creator"),
)
async def test_social_fuzzy_guard_does_not_steal_unrelated_searches(
    mock_intent_request,
    phrase,
):
    mock_intent_request.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
    }
    intent = mock_intent_request.request_envelope["request"]["intent"]
    intent["name"] = "SearchContentIntent"
    intent["slots"] = {
        "searchQuery": {"name": "searchQuery", "value": phrase},
    }

    await DirectIntentPhraseInterceptor().process(mock_intent_request)

    assert intent["name"] == "SearchContentIntent"
    assert ResolverWorkflowRunner._request(mock_intent_request) is not None


@pytest.mark.asyncio
async def test_listener_launch_sync_hydrates_authoritative_follow_snapshot(
    mock_handler_input,
):
    session: dict = {}
    _bind_session(mock_handler_input, session)
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
    }
    Listener.set_identity(
        mock_handler_input,
        IdentityContext(
            PrincipalType.SKILL_USER,
            alexa_user_id="amzn1.ask.account.TEST",
        ),
    )
    sync = AsyncMock(
        return_value={
            "status": "synced",
            "listenerId": "listener-1",
            "followedCreators": [
                {"id": "creator-1", "name": "News Reader", "type": "creator"},
                {
                    "id": "org-1",
                    "name": "York Talking News",
                    "type": "organization",
                },
            ],
        }
    )

    service = ListenerSyncService(SimpleNamespace(sync_listener=sync))

    assert await service.sync_for_launch(mock_handler_input) is True
    assert FollowingSessionState.followed_sources(mock_handler_input) == [
        {"id": "creator-1", "name": "News Reader", "type": "creator"},
        {"id": "org-1", "name": "York Talking News", "type": "organization"},
    ]
    assert FollowingSessionState.status(
        mock_handler_input,
        "creator-1",
        "creator",
    ) is True
    assert FollowingSessionState.status(
        mock_handler_input,
        "org-1",
        "organization",
    ) is True
    assert FollowingSessionState.status(
        mock_handler_input,
        "creator-missing",
        "creator",
    ) is False
    assert User.snapshot(mock_handler_input)["followedCreators"] == [
        {"id": "creator-1", "name": "News Reader", "type": "creator"},
        {"id": "org-1", "name": "York Talking News", "type": "organization"},
    ]


@pytest.mark.asyncio
async def test_followed_playback_uses_synced_creator_and_organization_snapshot(
    monkeypatch,
    mock_handler_input,
):
    session: dict = {}
    _bind_session(mock_handler_input, session)
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **StateSchema.DEFAULT_STORE,
        "listenerId": "listener-1",
    }
    FollowingSessionState.replace_snapshot(
        mock_handler_input,
        [
            {"id": "creator-1", "name": "News Reader", "type": "creator"},
            {
                "id": "org-1",
                "name": "York Talking News",
                "type": "organization",
            },
        ],
    )
    discover = AsyncMock(
        return_value={
            "results": [],
            "total_hits": 0,
            "total_pages": 1,
            "page": 0,
            "failed": False,
        }
    )
    monkeypatch.setattr(Search, "_discover_content_avoiding_recent", discover)

    await Search.play_from_followed_creators(
        mock_handler_input,
        user=User(),
        heara=MagicMock(),
        progressive=MagicMock(),
        browse=MagicMock(),
        playback=MagicMock(),
    )

    request = discover.await_args.args[1]
    assert request.filters == {
        "creatorIds": ["creator-1"],
        "organizationIds": ["org-1"],
    }


def test_session_follow_override_updates_synced_snapshot(mock_handler_input):
    session: dict = {}
    _bind_session(mock_handler_input, session)
    FollowingSessionState.replace_snapshot(
        mock_handler_input,
        [{"id": "org-1", "name": "York Talking News", "type": "organization"}],
    )

    FollowingSessionState.record(
        mock_handler_input,
        source_id="org-1",
        source_type="organization",
        followed=False,
        source_name="York Talking News",
    )
    assert FollowingSessionState.status(
        mock_handler_input,
        "org-1",
        "organization",
    ) is False
    assert FollowingSessionState.followed_sources(mock_handler_input) == []

    FollowingSessionState.record(
        mock_handler_input,
        source_id="creator-1",
        source_type="creator",
        followed=True,
        source_name="News Reader",
    )
    assert FollowingSessionState.followed_sources(mock_handler_input) == [
        {"id": "creator-1", "name": "News Reader", "type": "creator"}
    ]
