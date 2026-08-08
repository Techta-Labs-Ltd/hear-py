from pathlib import Path

import pytest

from src.adapters.memory_persistence import MemoryPersistenceAdapter
from src.application import build_skill
from src.registry import REQUEST_HANDLERS

from src.middleware import GATE_HANDLERS, REQUEST_INTERCEPTORS, RESPONSE_INTERCEPTORS
from src.clients.hear import HearApiClient


from src.services.observability import ErrorReporter
from src.services.feedback import FeedbackService
from src.services.playback import PlaybackService
from src.services.persistence import PlaybackStateRepository

from src.services.tasks import BackgroundTaskManager
from src.clients.resolver import ResolverClient

from src.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from config.permission_scopes import DEVICE_ADDRESS, GEOLOCATION_READ


def test_skill_factory_registers_the_complete_pipeline():
    skill = build_skill(MemoryPersistenceAdapter())

    assert len(skill.request_handlers) == len(GATE_HANDLERS) + len(REQUEST_HANDLERS)
    assert len(skill._request_interceptors) == len(REQUEST_INTERCEPTORS)
    assert len(skill._response_interceptors) == len(RESPONSE_INTERCEPTORS)


def test_obsolete_resolver_and_webhook_packages_are_absent():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "src" / "resolver").exists()
    assert not (root / "src" / "webhooks").exists()


def test_alexa_entry_graph_does_not_import_resolver_implementation():
    root = Path(__file__).resolve().parents[1]
    alexa_modules = [
        root / "main.py",
        root / "src" / "application.py",
        root / "src" / "middleware" / "pipeline.py",
        root / "src" / "middleware" / "resolver.py",
        root / "src" / "handlers" / "can_fulfill.py",
        root / "src" / "handlers" / "play.py",
        root / "src" / "handlers" / "onboarding.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in alexa_modules)

    assert "from src.resolver" not in combined
    assert "import src.resolver" not in combined
    assert "import spacy" not in combined


def test_template_has_no_dedicated_resolver_configuration():
    template = (Path(__file__).resolve().parents[1] / "template.yaml").read_text(
        encoding="utf-8"
    )
    assert "RESOLVER_" not in template
    assert "ResolverApiKey" not in template
    assert "ResolverFunction:" not in template
    assert "WebhookFunction:" not in template
    assert "Taxonomy" not in template


def test_template_owns_and_wires_durable_persistence_table():
    template = (Path(__file__).resolve().parents[1] / "template.yaml").read_text(
        encoding="utf-8"
    )

    assert "HearPersistenceTable:" in template
    assert "Type: AWS::DynamoDB::Table" in template
    assert "DeletionPolicy: Retain" in template
    assert "UpdateReplacePolicy: Retain" in template
    assert "BillingMode: PAY_PER_REQUEST" in template
    assert "PointInTimeRecoveryEnabled: true" in template
    assert "AttributeName: expiresAt" in template
    assert "HEAR_DDB_TABLE: !Ref HearPersistenceTable" in template
    assert "DynamoDBCrudPolicy: { TableName: !Ref HearPersistenceTable }" in template
    assert "HEAR_DDB_TABLE: hear-service" not in template


def test_runtime_and_container_do_not_install_or_import_spacy():
    root = Path(__file__).resolve().parents[1]
    runtime_sources = [
        root / "requirements.txt",
        root / "Dockerfile",
        root / ".github" / "workflows" / "deploy.yml",
        *sorted((root / "src").rglob("*.py")),
    ]
    combined = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in runtime_sources
    )

    assert "spacy" not in combined
    assert "en_core_web" not in combined


def test_stateful_services_have_explicit_owners():
    assert isinstance(HearApiClient(), HearApiClient)
    assert isinstance(ErrorReporter(), ErrorReporter)
    assert isinstance(PlaybackService(), PlaybackService)
    assert isinstance(BackgroundTaskManager(), BackgroundTaskManager)
    assert isinstance(FeedbackService(), FeedbackService)
    assert isinstance(
        ResolverClient(host="https://resolver.test", api_key="test"),
        ResolverClient,
    )


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
