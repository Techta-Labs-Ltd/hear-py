from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from scripts.check_source_infrastructure import SourceInfrastructureGuard


def guard(outputs=()):
    cloudformation = MagicMock()
    cloudformation.describe_stacks.return_value = {"Stacks": [{"Outputs": list(outputs)}]}
    eventbridge = MagicMock()
    return SourceInfrastructureGuard(cloudformation, eventbridge)


def test_existing_skill_deploys_without_eventbridge_access():
    check = guard([{"OutputKey": "SkillFunctionArn", "OutputValue": "existing-skill"}])
    check.eventbridge.describe_event_bus.side_effect = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "DescribeEventBus")
    check.validate("existing-stack", "hear-notifications-prod", provisioned=False, enabled=False)
    check.eventbridge.describe_event_bus.assert_not_called()


def test_existing_source_queues_cannot_be_removed_by_default_flag():
    check = guard([{"OutputKey": "NotificationSourceQueueArn", "OutputValue": "existing-queue"}])
    with pytest.raises(RuntimeError, match="retain provisioning"):
        check.validate("existing-stack", "hear-notifications-prod", provisioned=False, enabled=False)
    check.eventbridge.describe_event_bus.assert_not_called()


def test_source_delivery_cannot_start_without_infrastructure():
    check = guard()
    with pytest.raises(RuntimeError, match="requires source infrastructure"):
        check.validate("existing-stack", "hear-notifications-prod", provisioned=False, enabled=True)
    check.cloudformation.describe_stacks.assert_not_called()


def test_source_resources_can_be_provisioned_while_delivery_stays_paused():
    check = guard()
    check.eventbridge.describe_event_bus.side_effect = ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "missing"}}, "DescribeEventBus")
    check.validate("existing-stack", "hear-notifications-prod", provisioned=True, enabled=False)
    check.eventbridge.describe_event_bus.assert_called_once_with(Name="hear-notifications-prod")


def test_source_provisioning_still_rejects_eventbridge_access_denied():
    check = guard()
    check.eventbridge.describe_event_bus.side_effect = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "DescribeEventBus")
    with pytest.raises(ClientError, match="AccessDeniedException"):
        check.validate("existing-stack", "hear-notifications-prod", provisioned=True, enabled=False)


def test_missing_stack_is_allowed_for_initial_deployment():
    check = guard()
    check.cloudformation.describe_stacks.side_effect = ClientError({"Error": {"Code": "ValidationError", "Message": "Stack existing-stack does not exist"}}, "DescribeStacks")
    check.validate("existing-stack", "hear-notifications-prod", provisioned=False, enabled=False)


def test_cloudformation_access_denied_is_not_treated_as_missing_stack():
    check = guard()
    check.cloudformation.describe_stacks.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "DescribeStacks")
    with pytest.raises(ClientError, match="AccessDenied"):
        check.validate("existing-stack", "hear-notifications-prod", provisioned=False, enabled=False)


@pytest.mark.parametrize("name", ["NOTIFICATION_SOURCE_PROVISIONED", "NOTIFICATION_SOURCE_ENABLED"])
def test_invalid_source_flags_are_rejected(monkeypatch, name):
    monkeypatch.setenv(name, "falsee")
    with pytest.raises(RuntimeError, match="must be true or false"):
        SourceInfrastructureGuard.flag(name)
