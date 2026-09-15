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


def test_application_log_has_one_production_owner():
    src = Path(__file__).resolve().parents[1] / "src"
    logging_owner = src / "services" / "logging_control.py"
    for path in src.rglob("*.py"):
        if path == logging_owner:
            continue
        source = path.read_text(encoding="utf-8")
        assert "logging.getLogger" not in source
        assert "logger = ApplicationLog" not in source


def test_playback_event_handlers_use_explicit_collaborators():
    root = Path(__file__).resolve().parents[1] / "src"
    for relative_path in (
        "controllers/playback_events.py",
        "models/playback_events.py",
    ):
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "deps:" not in source
        assert "self._deps" not in source


def test_availability_gate_uses_its_explicit_action():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "controllers" / "availability.py"
    ).read_text(encoding="utf-8")
    assert "deps:" not in source
    assert "self._deps" not in source


def test_can_fulfill_handler_uses_an_explicit_resolver():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "controllers" / "can_fulfill.py"
    ).read_text(encoding="utf-8")
    assert "deps:" not in source
    assert "self._deps" not in source


def test_intent_dispatch_gate_uses_an_explicit_dispatcher():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "controllers"
        / "intent_dispatch.py"
    ).read_text(encoding="utf-8")
    assert "deps:" not in source


def test_error_and_basic_system_handlers_use_explicit_collaborators():
    root = Path(__file__).resolve().parents[1] / "src" / "controllers"
    assert "self._deps" not in (root / "error.py").read_text(encoding="utf-8")
    source = (root / "system.py").read_text(encoding="utf-8")
    for handler_name in (
        "CancelIntentHandler",
        "NavigateHomeHandler",
        "SessionEndedHandler",
    ):
        class_source = source.split(f"class {handler_name}", 1)[1].split(
            "\nclass ", 1
        )[0]
        assert "deps:" not in class_source
        assert "self._deps" not in class_source


def test_confirmation_handlers_use_explicit_actions():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "controllers" / "confirmation.py"
    ).read_text(encoding="utf-8")
    assert "deps:" not in source


def test_permission_model_uses_explicit_collaborators():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "models" / "permission.py"
    ).read_text(encoding="utf-8")
    assert "self._deps" not in source
    assert "def __init__(self, *, deps:" not in source


def test_github_workflows_do_not_reference_removed_agent_skills():
    root = Path(__file__).resolve().parents[1]
    workflows = [
        root / ".github" / "workflows" / "deploy-develop.yml",
        root / ".github" / "workflows" / "deploy-main.yml",
    ]
    for workflow in workflows:
        source = workflow.read_text(encoding="utf-8")
        assert "hear-architecture-refactor" not in source
        assert ".agents/" not in source
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


def test_backend_contract_schemas_match_v3_ownership():
    root = Path(__file__).resolve().parents[1]
    listener_sync = json.loads((root / "schemas/listener-sync.schema.json").read_text())
    backend_event = json.loads((root / "schemas/backend-event.schema.json").read_text())

    sync_fields = listener_sync["properties"]
    assert set(sync_fields) == {
        "action",
        "alexaUserId",
        "listenerId",
        "listenerName",
        "email",
        "city",
        "longitude",
        "latitude",
    }
    assert backend_event["properties"]["schemaVersion"]["const"] == 3
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


def test_deployments_disable_proactive_reservations_and_report_early_validation():
    root = Path(__file__).resolve().parents[1]
    for workflow_name in ("deploy-develop.yml", "deploy-main.yml"):
        workflow = (root / ".github" / "workflows" / workflow_name).read_text(
            encoding="utf-8"
        )
        assert "PROACTIVE_RESERVED_CONCURRENCY: '0'" in workflow
        assert "aws cloudformation describe-events" in workflow
        assert "EventType=='VALIDATION_ERROR'" in workflow


def test_template_owns_outbound_event_delivery_pipeline():
    template = (Path(__file__).resolve().parents[1] / "template.yaml").read_text(encoding="utf-8")
    assert "OutboundQueue:" in template
    assert "OutboundDeadLetterQueue:" in template
    assert "OutboundConsumerFunction:" in template
    assert "SQS_OUT_QUEUE_URL: !Ref OutboundQueue" in template
    assert "SQSSendMessagePolicy: { QueueName: !GetAtt OutboundQueue.QueueName }" in template
    assert "SQSPollerPolicy: { QueueName: !GetAtt OutboundQueue.QueueName }" in template
    assert "FunctionResponseTypes: [ReportBatchItemFailures]" in template


def test_template_owns_sqs_notification_delivery_worker_without_notification_dynamodb():
    root = Path(__file__).resolve().parents[1]
    template = (root / "template.yaml").read_text(encoding="utf-8")
    schema = json.loads(
        (root / "schemas" / "notification-item.schema.json").read_text()
    )
    message_schema = json.loads(
        (root / "schemas" / "notification-delivery-message.schema.json").read_text()
    )
    assert "HearNotificationInboxTable:" not in template
    assert "ActiveByListener" not in template
    assert "DynamoDBStreamReadPolicy" not in template
    assert "ProactiveNotificationQueue:" in template
    assert "ProactiveNotificationDeadLetterQueue:" in template
    assert "ProactiveNotificationFunction:" in template
    assert 'Command: ["main.notification_handler"]' in template
    assert "SQSPollerPolicy: { QueueName: !GetAtt ProactiveNotificationQueue.QueueName }" in template
    assert "Queue: !GetAtt ProactiveNotificationQueue.Arn" in template
    assert "FunctionResponseTypes: [ReportBatchItemFailures]" in template
    assert "ALEXA_PROACTIVE_CLIENT_ID" in template
    assert "ALEXA_PROACTIVE_CLIENT_SECRET" in template
    assert "AMAZON.MediaContent.Available" not in template
    assert schema["properties"]["schemaVersion"]["const"] == 1
    assert {"creator_update", "organization_update"} == set(
        schema["properties"]["notificationType"]["enum"]
    )
    assert "contentId" not in schema["properties"]
    assert "publicationId" not in schema["properties"]
    assert set(message_schema["required"]) == {
        "schemaVersion",
        "notificationId",
        "listenerId",
    }
    assert set(message_schema["properties"]) == set(message_schema["required"])


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


def test_container_allows_search_to_be_replaced_explicitly():
    from src.models.search import Search

    search = Search()
    assert ApplicationContainer(search=search).search is search


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
