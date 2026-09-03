import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import config.permission_scopes as permission_scopes
from src.alexa.request import AlexaRequest
from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.clients.events import SqsEventClient
from src.constants.state import StateSchema
from src.database.persistence import MemoryPersistenceAdapter
from src.middleware.identity import IdentityInterceptor
from src.middleware.persistence import LoadPersistenceInterceptor, SavePersistenceInterceptor
from src.models.listener import IdentityContext, Listener, PrincipalType
from src.models.user import User
from src.services.alexa_profile import ListenerProfileService
from src.services.listener_identity import ListenerIdentityService


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
    assert identity.principal_type == "skill_user"
    assert "_store" in attrs
    assert attrs["_store"].get("alexaUserId") is None


@pytest.mark.asyncio
async def test_identity_classifies_a_recognized_person(
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(
        {
            "context": {
                "System": {
                    "application": {"applicationId": "skill-1"},
                    "user": {"userId": "alexa-1"},
                    "person": {"personId": "person-1"},
                    "device": {"deviceId": "device-1"},
                }
            },
            "request": {"type": "LaunchRequest", "locale": "en-GB"},
        }
    )

    await IdentityInterceptor().process(mock_handler_input)

    identity = mock_handler_input.attributes_manager.request_attributes["_identity"]
    assert identity.principal_type == PrincipalType.RECOGNIZED_PERSON
    assert identity.person_id == "person-1"
    assert identity.skill_id == "skill-1"


@pytest.mark.asyncio
async def test_listener_identity_service_resolves_and_caches_canonical_listener(
    mock_handler_input,
):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.context.System.user.permissions.scopes = {
        permission_scopes.PROFILE_EMAIL_READ: {"status": "GRANTED"}
    }
    hear_api = SimpleNamespace(
        resolve_listener_identity=AsyncMock(return_value={"listenerId": "listener-1"})
    )
    settings_client = SimpleNamespace(
        get_profile_setting=AsyncMock(
            return_value={"value": " Alex@Example.COM ", "status": 200}
        )
    )
    service = ListenerIdentityService(
        hear_api,
        settings_client,
        enabled=True,
        timeout_ms=500,
    )
    identity = IdentityContext(
        principal_type=PrincipalType.SKILL_USER,
        alexa_user_id="alexa-1",
        skill_id="skill-1",
    )

    first = await service.resolve(mock_handler_input, identity)
    second = await service.resolve(mock_handler_input, identity)

    assert first.listener_id == "listener-1"
    assert first.user_email == "alex@example.com"
    assert second.listener_id == "listener-1"
    hear_api.resolve_listener_identity.assert_awaited_once()
    settings_client.get_profile_setting.assert_awaited_once_with(
        mock_handler_input,
        "Profile.email",
        label="Profile.email",
    )
    request = hear_api.resolve_listener_identity.await_args.args[0]
    assert request["alexaUserId"] == "alexa-1"
    assert request["principalType"] == "skill_user"
    assert request["userEmail"] == "alex@example.com"


@pytest.mark.asyncio
async def test_listener_identity_service_omits_email_without_permission(
    mock_handler_input,
):
    hear_api = SimpleNamespace(
        resolve_listener_identity=AsyncMock(return_value={"listenerId": "listener-1"})
    )
    settings_client = SimpleNamespace(get_profile_setting=AsyncMock())
    service = ListenerIdentityService(
        hear_api,
        settings_client,
        enabled=True,
        timeout_ms=500,
    )
    identity = IdentityContext(
        principal_type=PrincipalType.SKILL_USER,
        alexa_user_id="alexa-1",
        skill_id="skill-1",
    )

    resolved = await service.resolve(mock_handler_input, identity)

    assert resolved.listener_id == "listener-1"
    assert resolved.user_email is None
    settings_client.get_profile_setting.assert_not_awaited()
    request = hear_api.resolve_listener_identity.await_args.args[0]
    assert "userEmail" not in request


@pytest.mark.asyncio
async def test_identity_interceptor_fails_open_to_current_alexa_alias(mock_handler_input):
    identity_service = SimpleNamespace(
        resolve=AsyncMock(side_effect=RuntimeError("backend unavailable"))
    )
    deps = SimpleNamespace(listener_identity=identity_service, user=User())

    await IdentityInterceptor(deps=deps).process(mock_handler_input)

    identity = mock_handler_input.attributes_manager.request_attributes["_identity"]
    assert identity.alexa_user_id == "amzn1.ask.account.TEST"
    assert identity.listener_id is None


@pytest.mark.asyncio
async def test_canonical_persistence_reads_current_alias_once_and_copies_forward():
    envelope = AttrDict(
        {
            "context": {"System": {"user": {"userId": "alexa-old"}}},
            "request": {"type": "LaunchRequest", "locale": "en-GB"},
        }
    )
    persistence = MemoryPersistenceAdapter()
    persistence._store["alexa-old"] = {
        "listenerId": "listener-1",
        "playCount": 4,
    }
    manager = AttributesManager(envelope, persistence)
    handler_input = HandlerInput(envelope, manager, None, ResponseBuilder())
    identity_service = SimpleNamespace(
        resolve=AsyncMock(
            return_value=IdentityContext(
                principal_type=PrincipalType.SKILL_USER,
                alexa_user_id="alexa-old",
                user_email="alex@example.com",
                listener_id="listener-1",
            )
        )
    )
    deps = SimpleNamespace(listener_identity=identity_service, user=User())

    await IdentityInterceptor(deps=deps).process(handler_input)
    await LoadPersistenceInterceptor().process(handler_input)
    await SavePersistenceInterceptor().process(handler_input)

    canonical_key = User.canonical_persistence_key("listener-1")
    assert manager.used_alias_persistence is True
    assert User.snapshot(handler_input)["playCount"] == 4
    assert "listenerId" not in persistence._store[canonical_key]
    assert "userEmail" not in persistence._store[canonical_key]
    assert persistence._store[canonical_key]["playCount"] == 4
    assert persistence._store["alexa-old"]["playCount"] == 4


def test_backend_event_dispatch_is_disabled_without_a_queue():
    assert SqsEventClient(queue_url="").send({"event": "playback.started"}) is False
