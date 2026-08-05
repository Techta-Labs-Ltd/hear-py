from types import SimpleNamespace

import pytest

from src.middleware.identity import IdentityInterceptor
from src.resolver.models import SearchPlan
from src.resolver.alexa import alexa_resolver
from src.runtime import AttrDict
from src.services.alexa.client import send_playback_events
from src.services.storage.store import DEFAULT_STORE
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
async def test_identity_interceptor_persists_real_id_without_storing_token(mock_handler_input):
    mock_handler_input.attributes_manager.request_attributes["_store"] = dict(DEFAULT_STORE)
    mock_handler_input.request_envelope = AttrDict({
        "context": {"System": {"user": {
            "userId": "amzn1.ask.account.REAL",
        }}},
        "request": {"type": "IntentRequest"},
    })

    await IdentityInterceptor().process(mock_handler_input)

    attrs = mock_handler_input.attributes_manager.request_attributes
    assert attrs["_store"]["alexaUserId"] == "amzn1.ask.account.REAL"
    assert attrs["_identity"] == {
        "alexaUserId": "amzn1.ask.account.REAL",
    }


@pytest.mark.asyncio
async def test_backend_playback_dispatch_rejects_blank_identity(monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        "src.services.alexa.client.dispatch",
        lambda *args, **kwargs: dispatched.append(args),
    )

    result = await send_playback_events(
        alexa_user_id="   ",
        events=[{"contentId": "content-1", "sessionId": "session-1"}],
    )

    assert result == {"status": None}
    assert dispatched == []


def test_resolver_backend_payload_omits_blank_identity():
    payload = alexa_resolver.build_payload(SearchPlan(alexa_user_id="", query="news"))
    assert "alexaUserId" not in payload
