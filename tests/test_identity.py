import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import config.permission_scopes as permission_scopes
from src.alexa.request import AlexaRequest
from src.alexa.runtime import AttrDict
from src.clients.events import SqsEventClient
from src.constants.state import StateSchema
from src.middleware.identity import IdentityInterceptor
from src.models.listener import Listener
from src.models.user import User
from src.services.alexa_profile import ListenerProfileService


@pytest.mark.asyncio
async def test_listener_profile_fetches_independent_settings_concurrently(
    mock_handler_input,
):
    active = 0
    maximum = 0

    async def fetch(handler_input, setting_path, *, label=""):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        values = {
            "Profile.name": "Alex Hear",
            "Profile.givenName": "Alex",
            "Profile.email": "alex@example.com",
        }
        return {"value": values[setting_path], "status": 200}

    User.hydrate(mock_handler_input, {})
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.context.System.user.permissions.scopes = {
        permission_scopes.PROFILE_NAME_READ: {"status": "GRANTED"},
        permission_scopes.PROFILE_EMAIL_READ: {"status": "GRANTED"},
    }
    settings_client = SimpleNamespace(get_profile_setting=AsyncMock(side_effect=fetch))
    result = await ListenerProfileService(settings_client, Listener(User())).apply_listener_profile(
        mock_handler_input
    )
    assert maximum == 2
    assert result["userName"] == "Alex Hear"
    assert result["userEmail"] == "alex@example.com"


def test_identity_extracts_raw_alexa_context_and_session_fallback(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(
        {
            "context": {"System": {"user": {"userId": "amzn1.ask.account.REAL"}}},
            "session": {"user": {"userId": "session-user"}},
            "request": {"type": "LaunchRequest"},
        }
    )
    assert AlexaRequest.get_user_id(mock_handler_input) == "amzn1.ask.account.REAL"
    mock_handler_input.request_envelope.context.System.user.userId = "   "
    assert AlexaRequest.get_user_id(mock_handler_input) == "session-user"


def test_identity_extracts_ask_sdk_style_snake_case_models(mock_handler_input):
    mock_handler_input.request_envelope = SimpleNamespace(
        context=SimpleNamespace(
            system=SimpleNamespace(user=SimpleNamespace(user_id="amzn1.ask.account.SDK"))
        ),
        session=None,
    )
    assert AlexaRequest.get_user_id(mock_handler_input) == "amzn1.ask.account.SDK"


@pytest.mark.asyncio
async def test_identity_interceptor_keeps_identity_out_of_persisted_store(
    mock_handler_input,
):
    mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
        StateSchema.DEFAULT_STORE
    )
    mock_handler_input.request_envelope = AttrDict(
        {
            "context": {"System": {"user": {"userId": "amzn1.ask.account.REAL"}}},
            "request": {"type": "IntentRequest"},
        }
    )
    await IdentityInterceptor().process(mock_handler_input)
    attrs = mock_handler_input.attributes_manager.request_attributes
    identity = attrs["_identity"]
    assert identity.alexa_user_id == "amzn1.ask.account.REAL"
    assert identity.principal_type == "anonymous_installation"
    assert "_store" in attrs
    assert attrs["_store"].get("alexaUserId") is None


def test_backend_event_dispatch_is_disabled_without_a_queue():
    assert SqsEventClient(queue_url="").send({"event": "playback.started"}) is False
