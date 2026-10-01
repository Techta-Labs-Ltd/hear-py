from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config import settings
from src.alexa.following_state import FollowingSessionState
from src.models.listener import IdentityContext, PrincipalType
from src.services.listener_identity import ListenerIdentityService
from src.services.listener_repository import Listener
from src.services.listener_sync import ListenerSyncService


def _bind_session(handler_input, session: dict) -> None:
    handler_input.attributes_manager.get_session_attributes = lambda: session

    def set_session(value: dict) -> None:
        session.clear()
        session.update(value)

    handler_input.attributes_manager.set_session_attributes = set_session


@pytest.mark.asyncio
async def test_warm_identity_cache_rehydrates_follow_snapshot_without_second_http_call(
    mock_handler_input,
):
    session: dict = {}
    _bind_session(mock_handler_input, session)
    hear_api = SimpleNamespace(
        resolve_listener_identity=AsyncMock(
            return_value={
                "listenerId": "listener-1",
                "followedCreators": [
                    {"id": "org-1", "name": "York Talking News", "type": "organization"}
                ],
            }
        )
    )
    service = ListenerIdentityService(
        hear_api,
        settings_client=None,
        enabled=True,
        timeout_ms=350,
    )
    identity = IdentityContext(
        principal_type=PrincipalType.SKILL_USER,
        alexa_user_id="amzn1.ask.account.TEST",
        skill_id="skill-1",
    )

    first = await service.resolve(mock_handler_input, identity)
    assert first.listener_id == "listener-1"
    assert FollowingSessionState.status(
        mock_handler_input,
        "org-1",
        "organization",
    ) is True

    session.clear()
    second = await service.resolve(mock_handler_input, identity)

    assert second.listener_id == "listener-1"
    assert FollowingSessionState.status(
        mock_handler_input,
        "org-1",
        "organization",
    ) is True
    hear_api.resolve_listener_identity.assert_awaited_once()


@pytest.mark.asyncio
async def test_listener_sync_uses_bounded_hot_path_timeout(mock_handler_input):
    mock_handler_input.attributes_manager.request_attributes["_store"] = {}
    Listener.set_identity(
        mock_handler_input,
        IdentityContext(
            PrincipalType.SKILL_USER,
            alexa_user_id="amzn1.ask.account.TEST",
            listener_id="listener-1",
        ),
    )
    sync = AsyncMock(
        return_value={
            "listenerId": "listener-1",
            "followedCreators": [],
        }
    )
    service = ListenerSyncService(SimpleNamespace(sync_listener=sync))

    assert await service.sync_for_launch(mock_handler_input) is True

    assert sync.await_args.kwargs["timeout_ms"] <= settings.HEAR_LISTENER_SYNC_TIMEOUT_MS
    assert sync.await_args.kwargs["timeout_ms"] <= 250


def test_listener_hot_path_deployment_budgets_are_sub_second():
    assert settings.HEAR_IDENTITY_TIMEOUT_MS <= 350
    assert settings.HEAR_LISTENER_SYNC_TIMEOUT_MS <= 250

    template = Path("template.yaml").read_text(encoding="utf-8")
    assert 'HEAR_IDENTITY_TIMEOUT_MS: "350"' in template
    assert 'HEAR_LISTENER_SYNC_TIMEOUT_MS: "250"' in template
