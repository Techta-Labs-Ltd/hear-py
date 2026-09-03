import ast
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.application import Application
from src.clients.alexa import AlexaClient
from src.clients.hear import HearApiClient
from src.clients.resolver import ResolverClient, ResolverOptions
from src.constants.onboarding import OnboardingConstants
from src.container import ApplicationContainer
from src.database.persistence import MemoryPersistenceAdapter
from src.models.feedback import FeedbackService
from src.models.playback import Playback
from src.registry import RouteRegistry
from src.services.observability import ErrorReporter


def test_skill_factory_registers_the_complete_pipeline():
    skill = Application.build_skill(MemoryPersistenceAdapter(), deps=ApplicationContainer())
    assert len(skill.request_handlers) == len(RouteRegistry.GATE_HANDLERS) + len(
        RouteRegistry.REQUEST_CONTROLLERS
    )
    assert len(skill._request_interceptors) == len(RouteRegistry.REQUEST_INTERCEPTORS)
    assert len(skill._response_interceptors) == len(RouteRegistry.RESPONSE_INTERCEPTORS)


def test_obsolete_resolver_and_webhook_packages_are_absent():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "src" / "resolver").exists()
    assert not (root / "src" / "webhooks").exists()


def test_related_domain_models_are_consolidated():
    models = Path(__file__).resolve().parents[1] / "src" / "models"
    assert not (models / "identity.py").exists()
    assert not (models / "resolution.py").exists()
    assert not (models / "launch.py").exists()
    assert not (models / "deferred.py").exists()


def test_runtime_and_utility_modules_have_clear_owners():
    src = Path(__file__).resolve().parents[1] / "src"
    assert not any((src / "runtime").glob("*.py"))
    assert not (src / "filters.py").exists()
    assert (src / "alexa" / "runtime.py").exists()
    assert (src / "utils" / "deadline.py").exists()
    assert (src / "utils" / "filters.py").exists()


def test_github_workflows_use_the_current_architecture_audit():
    root = Path(__file__).resolve().parents[1]
    workflows = [
        root / ".github" / "workflows" / "deploy-develop.yml",
        root / ".github" / "workflows" / "deploy-main.yml",
    ]
    for workflow in workflows:
        source = workflow.read_text(encoding="utf-8")
        assert "hear-architecture-refactor/scripts/audit_architecture.py . --strict" in source
        assert "hear-alexa-python/scripts/audit_project.py" not in source


def test_models_only_expose_classes_with_imports_at_the_top():
    root = Path(__file__).resolve().parents[1] / "src" / "models"
    for path in root.glob("*.py"):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            allowed = isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef))
            type_checking = (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and (node.test.id == "TYPE_CHECKING")
            )
            assert allowed or type_checking, (
                f"{path.name}:{node.lineno} contains module-level {type(node).__name__}"
            )
        first_class = min((node.lineno for node in tree.body if isinstance(node, ast.ClassDef)))
        late_imports = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom)) and node.lineno > first_class
        ]
        assert not late_imports, f"{path.name} has late imports at {late_imports}"


def test_dependency_container_exposes_feature_facades():
    dependencies = ApplicationContainer()
    assert not hasattr(dependencies, "onboarding_store")
    assert not hasattr(dependencies, "playback_store")
    assert not hasattr(dependencies, "playback_queue")
    assert dependencies.playback.state is not None
    assert dependencies.playback.queue is not None


def test_alexa_entry_graph_does_not_import_resolver_implementation():
    root = Path(__file__).resolve().parents[1]
    alexa_modules = [
        root / "main.py",
        root / "src" / "application.py",
        root / "src" / "registry.py",
        root / "src" / "middleware" / "resolver.py",
        root / "src" / "controllers" / "can_fulfill.py",
        root / "src" / "controllers" / "play.py",
        root / "src" / "models" / "search.py",
        root / "src" / "models" / "onboarding.py",
        root / "src" / "models" / "browse.py",
    ]
    combined = "\n".join((path.read_text(encoding="utf-8") for path in alexa_modules))
    assert "from src.resolver" not in combined
    assert "import src.resolver" not in combined
    assert "import spacy" not in combined


def test_template_has_no_dedicated_resolver_configuration():
    template = (Path(__file__).resolve().parents[1] / "template.yaml").read_text(encoding="utf-8")
    assert "RESOLVER_" not in template
    assert "ResolverApiKey" not in template
    assert "ResolverFunction:" not in template
    assert "WebhookFunction:" not in template
    assert "Taxonomy" not in template


def test_template_owns_and_wires_durable_persistence_table():
    template = (Path(__file__).resolve().parents[1] / "template.yaml").read_text(encoding="utf-8")
    assert "HearListenerStateTable:" in template
    assert "Type: AWS::DynamoDB::Table" in template
    assert "DeletionPolicy: Retain" in template
    assert "UpdateReplacePolicy: Retain" in template
    assert "BillingMode: PAY_PER_REQUEST" in template
    assert "PointInTimeRecoveryEnabled: true" in template
    assert "AttributeName: expiresAt" in template
    assert "HEAR_DDB_TABLE: !Ref HearListenerStateTable" in template
    assert "HEAR_DDB_SORT_KEY: scope" in template
    assert "DynamoDBCrudPolicy: { TableName: !Ref HearListenerStateTable }" in template
    assert "HearPersistenceTable:" not in template
    assert "HEAR_DDB_LEGACY_TABLE" not in template
    assert "HEAR_DDB_TABLE: hear-service" not in template


def test_backend_contract_schemas_match_v2_ownership():
    root = Path(__file__).resolve().parents[1]
    listener_sync = json.loads((root / "schemas/listener-sync.schema.json").read_text())
    backend_event = json.loads((root / "schemas/backend-event.schema.json").read_text())

    sync_fields = listener_sync["properties"]
    assert "listenerId" in sync_fields
    assert "recentPlays" not in sync_fields
    assert "followedCreatorIds" not in sync_fields
    assert "feedbackHistory" not in sync_fields
    assert backend_event["properties"]["schemaVersion"]["const"] == 2
    assert {"eventId", "schemaVersion", "data"}.issubset(backend_event["required"])


def test_template_has_scaling_guards_and_operational_alarms():
    template = (Path(__file__).resolve().parents[1] / "template.yaml").read_text(encoding="utf-8")
    assert "HasReservedConcurrency: !Not" in template
    assert "ReservedConcurrentExecutions: !If" in template
    assert "ProvisionedConcurrencyConfig: !If" in template
    assert "HasProactiveReservedConcurrency: !Not" in template
    assert "ProactiveReservedConcurrency:" in template
    assert "ReservedConcurrentExecutions: 5" not in template
    assert "HearSkillErrorAlarm:" in template
    assert "HearSkillThrottleAlarm:" in template
    assert "HearSkillDurationAlarm:" in template
    assert "HearPersistenceLoadFailureAlarm:" in template
    assert "HearPersistenceSaveFailureAlarm:" in template
    assert "OutboundQueueAgeAlarm:" in template
    assert "OutboundDeadLetterAlarm:" in template


def test_template_owns_outbound_event_delivery_pipeline():
    template = (Path(__file__).resolve().parents[1] / "template.yaml").read_text(encoding="utf-8")
    assert "OutboundQueue:" in template
    assert "OutboundDeadLetterQueue:" in template
    assert "OutboundConsumerFunction:" in template
    assert "SQS_OUT_QUEUE_URL: !Ref OutboundQueue" in template
    assert "SQSSendMessagePolicy: { QueueName: !GetAtt OutboundQueue.QueueName }" in template
    assert "SQSPollerPolicy: { QueueName: !GetAtt OutboundQueue.QueueName }" in template
    assert "FunctionResponseTypes: [ReportBatchItemFailures]" in template


def test_template_owns_backend_written_notification_inbox_and_delivery_worker():
    root = Path(__file__).resolve().parents[1]
    template = (root / "template.yaml").read_text(encoding="utf-8")
    schema = json.loads(
        (root / "schemas" / "notification-inbox-item.schema.json").read_text()
    )
    assert "HearNotificationInboxTable:" in template
    assert "IndexName: ActiveByListener" in template
    assert "StreamViewType: NEW_AND_OLD_IMAGES" in template
    assert "ProactiveNotificationFunction:" in template
    assert 'Command: ["main.notification_handler"]' in template
    assert "ALEXA_PROACTIVE_CLIENT_ID" in template
    assert "ALEXA_PROACTIVE_CLIENT_SECRET" in template
    assert "AMAZON.MediaContent.Available" not in template
    assert schema["properties"]["schemaVersion"]["const"] == 1
    assert {"content", "publication"} == set(
        schema["properties"]["notificationType"]["enum"]
    )


def test_deployment_role_can_manage_table_recovery_configuration():
    policy_path = Path(__file__).resolve().parents[1] / "deploy" / "oidc-permissions-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    actions = {
        action
        for statement in policy["Statement"]
        for action in (
            statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        )
    }
    assert "dynamodb:UpdateContinuousBackups" in actions
    assert "dynamodb:DescribeContinuousBackups" in actions
    assert "cloudwatch:PutMetricAlarm" in actions
    assert "cloudwatch:DeleteAlarms" in actions
    assert "sqs:CreateQueue" in actions
    assert "sqs:SetQueueAttributes" in actions


def test_runtime_and_container_do_not_install_or_import_spacy():
    root = Path(__file__).resolve().parents[1]
    runtime_sources = [
        root / "requirements.txt",
        root / "Dockerfile",
        *sorted((root / ".github" / "workflows").glob("*.yml")),
        *sorted((root / "src").rglob("*.py")),
    ]
    combined = "\n".join((path.read_text(encoding="utf-8").lower() for path in runtime_sources))
    assert "spacy" not in combined
    assert "en_core_web" not in combined


def test_stateful_services_have_explicit_owners():
    assert isinstance(HearApiClient(), HearApiClient)
    assert isinstance(ErrorReporter(), ErrorReporter)
    assert isinstance(Playback(AlexaClient()), Playback)
    assert isinstance(FeedbackService(), FeedbackService)
    assert isinstance(
        ResolverClient(ResolverOptions(host="https://resolver.test", api_key="test")),
        ResolverClient,
    )


@pytest.mark.asyncio
async def test_onboarding_yes_returns_permission_card(monkeypatch):
    from src.clients.alexa_settings import AlexaSettingsClient

    monkeypatch.setattr(
        AlexaSettingsClient,
        "get_device_address",
        AsyncMock(return_value={"_status": "permission_denied"}),
    )
    skill = Application.build_skill(MemoryPersistenceAdapter(), deps=ApplicationContainer())
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
    directive = response["response"]["directives"][0]
    assert directive["type"] == "Connections.StartConnection"
    assert directive["token"] == "onboarding_location"
    assert [
        scope["permissionScope"] for scope in directive["input"]["permissionScopes"]
    ] == list(OnboardingConstants.LOCATION_VOICE_PERMISSIONS)
    assert "shouldEndSession" not in response["response"]


def test_feedback_service_owns_pending_feedback_policy():
    envelope = AttrDict(
        {
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
        }
    )
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {"awaitingFeedback": True, "feedbackContentTitle": "Example"},
        "_dirty": False,
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())
    service = FeedbackService()
    assert service.should_block(handler_input)
    from src.alexa.feedback import AlexaFeedback

    response = AlexaFeedback.present_pending_feedback(
        handler_input, attributes.request_attributes["_store"]
    )
    assert response["shouldEndSession"] is False
