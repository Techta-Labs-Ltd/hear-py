"""Validate optional source infrastructure without changing AWS resources."""
from __future__ import annotations

import os

import boto3
from botocore.exceptions import ClientError


class SourceInfrastructureGuard:
    def __init__(self, cloudformation, eventbridge):
        self.cloudformation = cloudformation
        self.eventbridge = eventbridge

    def validate(self, stack_name: str, bus_name: str, *, provisioned: bool, enabled: bool) -> None:
        if enabled and not provisioned:
            raise RuntimeError("Source delivery requires source infrastructure provisioning")
        try:
            stacks = self.cloudformation.describe_stacks(StackName=stack_name)["Stacks"]
        except ClientError as error:
            if error.response["Error"]["Code"] != "ValidationError" or "does not exist" not in error.response["Error"]["Message"]:
                raise
            stacks = []
        if not provisioned:
            if any(output["OutputKey"] == "NotificationSourceQueueArn" for stack in stacks for output in stack.get("Outputs", [])):
                raise RuntimeError("Source infrastructure already exists; retain provisioning and disable only source delivery")
            print("Source infrastructure is unprovisioned; existing Lambda deployment does not require EventBridge access")
            return
        try:
            self.eventbridge.describe_event_bus(Name=bus_name)
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
        print("Source infrastructure provisioning requires EventBridge access; source delivery activation remains separate")

    @staticmethod
    def flag(name: str) -> bool:
        value = os.getenv(name, "false")
        if value not in {"true", "false"}:
            raise RuntimeError(f"{name} must be true or false")
        return value == "true"


def main() -> None:
    provisioned = SourceInfrastructureGuard.flag("NOTIFICATION_SOURCE_PROVISIONED")
    enabled = SourceInfrastructureGuard.flag("NOTIFICATION_SOURCE_ENABLED")
    session = boto3.Session(region_name=os.environ["AWS_REGION"])
    guard = SourceInfrastructureGuard(session.client("cloudformation"), session.client("events") if provisioned else None)
    guard.validate(
        os.environ["STACK_NAME"],
        os.getenv("NOTIFICATION_EVENT_BUS_NAME") or f"hear-notifications-{os.environ['SHORT_STAGE']}",
        provisioned=provisioned,
        enabled=enabled,
    )


if __name__ == "__main__":
    main()
