import base64
from pathlib import Path

import pytest

from src.adapters.memory_persistence import MemoryPersistenceAdapter
from src.application import build_skill
from src.handlers.registry import REQUEST_HANDLERS
from src.middleware import GATE_HANDLERS, REQUEST_INTERCEPTORS, RESPONSE_INTERCEPTORS
from src.services.api.client import HearApiClient
from src.services.api.request import ApiRequester
from src.services.observability import ErrorReporter
from src.services.feedback import FeedbackService
from src.services.playback import PlaybackService
from src.services.storage.playback_state import PlaybackStateRepository
from src.services.tasks import BackgroundTaskManager
from src.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from config.permission_scopes import DEVICE_ADDRESS, GEOLOCATION_READ
from src.webhooks.router import is_http_event, normalize_http_event


def test_skill_factory_registers_the_complete_pipeline():
    skill = build_skill(MemoryPersistenceAdapter())

    assert len(skill.request_handlers) == len(GATE_HANDLERS) + len(REQUEST_HANDLERS)
    assert len(skill._request_interceptors) == len(REQUEST_INTERCEPTORS)
    assert len(skill._response_interceptors) == len(RESPONSE_INTERCEPTORS)


def test_normalizes_api_gateway_v2_event():
    body = base64.b64encode(b'{"ok":true}').decode("ascii")
    event = {
        "requestContext": {"http": {"method": "POST", "path": "/webhook/settings"}},
        "headers": {"x-test": "yes"},
        "body": body,
        "isBase64Encoded": True,
    }

    assert is_http_event(event)
    assert normalize_http_event(event) == {
        "httpMethod": "POST",
        "path": "/webhook/settings",
        "headers": {"x-test": "yes"},
        "body": '{"ok":true}',
    }


def test_normalizes_api_gateway_v1_event():
    event = {
        "httpMethod": "POST",
        "path": "/webhook/notification",
        "headers": {},
        "body": "{}",
    }

    assert is_http_event(event)
    assert normalize_http_event(event)["path"] == "/webhook/notification"


def test_alexa_and_webhook_lambda_entry_points_are_separate():
    root = Path(__file__).resolve().parents[1]
    alexa_entry = (root / "main.py").read_text(encoding="utf-8")
    webhook_entry = (
        root / "src" / "webhooks" / "lambda_handler.py"
    ).read_text(encoding="utf-8")

    assert "src.webhooks.router" not in alexa_entry
    assert "src.resolver" not in webhook_entry


def test_alexa_entry_graph_does_not_import_resolver_implementation():
    root = Path(__file__).resolve().parents[1]
    alexa_modules = [
        root / "main.py",
        root / "src" / "application.py",
        root / "src" / "middleware" / "pipeline.py",
        root / "src" / "nlp" / "__init__.py",
        root / "src" / "handlers" / "can_fulfill.py",
        root / "src" / "handlers" / "intents" / "play.py",
        root / "src" / "handlers" / "intents" / "onboarding.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in alexa_modules)

    assert "from src.resolver" not in combined
    assert "import src.resolver" not in combined
    assert "import spacy" not in combined


def test_resolver_has_a_dedicated_lambda_entry_point():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "resolver" / "lambda_handler.py").read_text(
        encoding="utf-8"
    )

    assert "def handler(" in source
    assert "semantic_intent_router.warm()" not in source


def test_stateful_services_have_explicit_owners():
    assert isinstance(HearApiClient(), HearApiClient)
    assert isinstance(ApiRequester(), ApiRequester)
    assert isinstance(ErrorReporter(), ErrorReporter)
    assert isinstance(PlaybackService(), PlaybackService)
    assert isinstance(BackgroundTaskManager(), BackgroundTaskManager)
    assert isinstance(FeedbackService(), FeedbackService)


@pytest.mark.asyncio
async def test_playback_repositories_have_isolated_memory():
    first = PlaybackStateRepository()
    second = PlaybackStateRepository()

    await first.set("user-1", {"contentId": "track-1"})

    assert await first.get("user-1") == {
        "alexaUserId": "user-1",
        "contentId": "track-1",
    }
    assert await second.get("user-1") is None


@pytest.mark.asyncio
async def test_onboarding_yes_returns_permission_card():
    skill = build_skill(MemoryPersistenceAdapter())
    context = {
        "System": {
            "user": {"userId": "test-user"},
            "device": {"deviceId": "test-device"},
        }
    }
    launch = {
        "version": "1.0",
        "context": context,
        "session": {"user": {"userId": "test-user"}},
        "request": {"type": "LaunchRequest", "locale": "en-GB"},
    }
    yes = {
        "version": "1.0",
        "context": context,
        "session": {"user": {"userId": "test-user"}},
        "request": {
            "type": "IntentRequest",
            "locale": "en-GB",
            "intent": {"name": "AMAZON.YesIntent", "slots": {}},
        },
    }

    await skill.invoke(launch, None)
    response = await skill.invoke(yes, None)

    assert response["response"]["card"] == {
        "type": "AskForPermissionsConsent",
        "permissions": [DEVICE_ADDRESS, GEOLOCATION_READ],
    }


def test_feedback_service_owns_pending_feedback_policy():
    envelope = AttrDict({
        "context": {
            "System": {
                "user": {"userId": "test-user"},
                "device": {"deviceId": "test-device"},
            }
        },
        "request": {
            "type": "IntentRequest",
            "intent": {"name": "PlayContentIntent", "slots": {}},
        },
    })
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            "awaitingFeedback": True,
            "feedbackContentTitle": "Example",
        },
        "_dirty": False,
    }
    handler_input = HandlerInput(
        envelope,
        attributes,
        None,
        ResponseBuilder(),
    )

    service = FeedbackService()

    assert service.should_block(handler_input)
    response = service.pending_response(handler_input)
    assert response["shouldEndSession"] is False
