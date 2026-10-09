from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.alexa.following_state import FollowCheck, FollowingSessionState
from src.alexa.notification_permission import NotificationPermissionPrompt
from src.clients.hear import HearApiClient
from src.models.user import User


class _Heara:
    def __init__(self, result):
        self.check_follow = AsyncMock(return_value=result)


def _handler_input(mock_handler_input, *, granted: bool = False):
    scopes = {"alexa::devices:all:notifications:write": {"status": "GRANTED"}} if granted else {}
    system = mock_handler_input.request_envelope.setdefault("context", {}).setdefault("System", {})
    system.setdefault("user", {})["permissions"] = {"scopes": scopes}
    return mock_handler_input


def _with_session(handler_input):
    session: dict = {}
    handler_input.attributes_manager.get_session_attributes = lambda: session
    handler_input.attributes_manager.set_session_attributes = lambda value: (
        session.clear(),
        session.update(value),
    )
    return handler_input


@pytest.mark.asyncio
async def test_follow_check_asks_the_api_and_remembers_a_follow(mock_handler_input):
    mock_handler_input = _with_session(mock_handler_input)
    heara = _Heara(True)
    store = {"listenerId": "11111111-2222-3333-4444-555555555555"}

    first = await FollowCheck.already_following(mock_handler_input, heara, store, "org-1", "organization")
    second = await FollowCheck.already_following(mock_handler_input, heara, store, "org-1", "organization")

    assert first is True and second is True
    heara.check_follow.assert_awaited_once()
    assert heara.check_follow.await_args.kwargs["source_type"] == "organization"
    assert FollowingSessionState.status(mock_handler_input, "org-1", "organization") is True


@pytest.mark.asyncio
async def test_follow_check_failure_falls_back_to_not_following(mock_handler_input):
    heara = SimpleNamespace(check_follow=AsyncMock(side_effect=TimeoutError()))

    assert not await FollowCheck.already_following(mock_handler_input, heara, {}, "creator-1", "creator")


@pytest.mark.asyncio
async def test_api_client_sends_the_documented_follow_check_contract(monkeypatch):
    client = HearApiClient()
    raw = AsyncMock(return_value=(200, True))
    monkeypatch.setattr(HearApiClient, "_raw_request", raw)

    result = await client.check_follow(
        listener_id="11111111-2222-3333-4444-555555555555",
        alexa_user_id="amzn1.ask.account.X",
        source_id="org-1",
        source_type="organization",
    )

    assert result is True
    method, path, body, _ = raw.await_args.args
    assert method == "POST" and path.endswith("listeners/follows/check")
    assert body == {"organizationId": "org-1", "listenerId": "11111111-2222-3333-4444-555555555555"}


def test_permission_prompt_is_not_repeated_once_granted(mock_handler_input):
    assert NotificationPermissionPrompt.due(_handler_input(mock_handler_input), {}) is True
    assert NotificationPermissionPrompt.due(_handler_input(mock_handler_input, granted=True), {}) is False


def test_permission_prompt_waits_thirty_days_after_asking(monkeypatch, mock_handler_input):
    monkeypatch.setattr("src.alexa.notification_permission.time.time", lambda: 10_000_000)
    handler_input = _handler_input(mock_handler_input)
    recent = {"notificationPermissionPromptedAt": 10_000_000 - 86400}
    old = {"notificationPermissionPromptedAt": 10_000_000 - 31 * 86400}

    assert NotificationPermissionPrompt.due(handler_input, recent) is False
    assert NotificationPermissionPrompt.due(handler_input, old) is True


def test_permission_prompt_records_when_it_asked(monkeypatch, mock_handler_input):
    monkeypatch.setattr("src.alexa.notification_permission.time.time", lambda: 1234)
    builder = mock_handler_input.response_builder
    for name in ("speak", "reprompt", "with_ask_for_permissions_consent_card", "add_directive", "set_should_end_session"):
        getattr(builder, name).return_value = builder

    NotificationPermissionPrompt.respond(mock_handler_input, User(), "speech", "reprompt")

    builder.with_ask_for_permissions_consent_card.assert_called_once_with(
        ["alexa::devices:all:notifications:write"]
    )
    assert User.snapshot(mock_handler_input)["notificationPermissionPromptedAt"] == 1234
