from types import SimpleNamespace

import pytest

from src.middleware.identity import IdentityInterceptor
from src.runtime import AttrDict
from src.clients.alexa import send_playback_events

from src.services.store import DEFAULT_STORE

from src.utils.skill_request import get_user_id


def test_identity_extracts_raw_alexa_context_and_session_fallback(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict({
        "context": {
            "System": {
                "user": {
                    "userId": "amzn1.ask.account.REAL",
                },
            },
        },
        "session": {"user": {"userId": "session-user"}},
        "request": {"type": "LaunchRequest"},
    })

    assert get_user_id(mock_handler_input) == "amzn1.ask.account.REAL"

    mock_handler_input.request_envelope.context.System.user.userId = "   "
    assert get_user_id(mock_handler_input) == "session-user"


def test_identity_extracts_ask_sdk_style_snake_case_models(mock_handler_input):
    mock_handler_input.request_envelope = SimpleNamespace(
        context=SimpleNamespace(
            system=SimpleNamespace(
                user=SimpleNamespace(
                    user_id="amzn1.ask.account.SDK",
                ),
            ),
        ),
        session=None,
    )

    assert get_user_id(mock_handler_input) == "amzn1.ask.account.SDK"


@pytest.mark.asyncio
async def test_identity_interceptor_keeps_identity_out_of_persisted_store(mock_handler_input):
    mock_handler_input.attributes_manager.request_attributes["_store"] = dict(DEFAULT_STORE)
    mock_handler_input.request_envelope = AttrDict({
        "context": {"System": {"user": {
            "userId": "amzn1.ask.account.REAL",
        }}},
        "request": {"type": "IntentRequest"},
    })

    await IdentityInterceptor().process(mock_handler_input)

    attrs = mock_handler_input.attributes_manager.request_attributes
    identity = attrs["_identity"]
    assert identity.alexa_user_id == "amzn1.ask.account.REAL"
    assert identity.principal_type == "anonymous_installation"
    assert "_store" in attrs
    assert attrs["_store"].get("alexaUserId") is None


@pytest.mark.asyncio
async def test_backend_playback_dispatch_rejects_blank_identity():
    result = await send_playback_events(
        alexa_user_id="   ",
        events=[{"contentId": "content-1", "sessionId": "session-1"}],
    )

    assert result == {"status": None}
