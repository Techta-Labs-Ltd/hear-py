"""Read-only AWS inventory for the approved Go/EventBridge setup. No secrets."""
from __future__ import annotations

import json
import os
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def main():
    environment = os.environ["SETUP_ENVIRONMENT"]
    region = os.environ["AWS_REGION"]
    stage = os.environ["SHORT_STAGE"]
    stack = os.environ["STACK_NAME"]
    session = boto3.Session(region_name=region)
    cfg = Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 1})
    report = {"environment": environment, "region": region, "stage": stage, "stack": stack, "errors": []}

    def read(service, operation, **kwargs):
        try:
            return getattr(session.client(service, config=cfg), operation)(**kwargs)
        except ClientError as exc:
            report["errors"].append({"service": service, "operation": operation, "code": exc.response["Error"]["Code"]})
            return {}

    identity = read("sts", "get_caller_identity")
    report["account"] = identity.get("Account")
    report["principal"] = identity.get("Arn")
    stacks = read("cloudformation", "describe_stacks", StackName=stack).get("Stacks", [])
    if stacks:
        report["stack_status"] = stacks[0]["StackStatus"]
        allowed = {"SkillFunctionArn", "ProactiveNotificationQueueUrl", "ProactiveNotificationQueueArn", "NotificationEventBusArn", "NotificationSourceRuleName", "NotificationSourceQueueArn", "GoSourceEventBridgePolicyArn", "PersistenceTableName"}
        report["outputs"] = {x["OutputKey"]: x["OutputValue"] for x in stacks[0].get("Outputs", []) if x["OutputKey"] in allowed}
    report["functions"] = []
    for name in (f"Hear-Python-{stage}", f"Hear-Outbound-Python-{stage}", f"Hear-Proactive-Python-{stage}", f"Hear-Notification-Source-{stage}"):
        fn = read("lambda", "get_function_configuration", FunctionName=name)
        if not fn:
            continue
        env = fn.get("Environment", {}).get("Variables", {})
        report["functions"].append({"name": name, "state": fn.get("State"), "last_update": fn.get("LastUpdateStatus"), "role": fn.get("Role"), "timeout": fn.get("Timeout"), "memory": fn.get("MemorySize"), "api_url": env.get("HEAR_API_URL"), "webhook_url": env.get("WEBHOOK_OUTBOUND_URL"), "credential_presence": {k: bool(env.get(k)) for k in ("HEAR_API_KEY", "WEBHOOK_OUTBOUND_SECRET", "ALEXA_PROACTIVE_CLIENT_ID", "ALEXA_PROACTIVE_CLIENT_SECRET")}})
    report["buses"] = []
    token = None
    for _ in range(10):
        page = read("events", "list_event_buses", **({"NextToken": token} if token else {}))
        for bus in page.get("EventBuses", []):
            if "hear" not in bus["Name"].lower() and bus["Name"] != "default":
                continue
            rules = []
            next_rule = None
            for _ in range(10):
                rp = read("events", "list_rules", EventBusName=bus["Name"], Limit=100, **({"NextToken": next_rule} if next_rule else {}))
                for rule in rp.get("Rules", []):
                    if not any(term in (rule.get("Name", "") + rule.get("EventPattern", "")).lower() for term in ("hear", "alexa", "notification")):
                        continue
                    tp = read("events", "list_targets_by_rule", Rule=rule["Name"], EventBusName=bus["Name"])
                    rules.append({"name": rule["Name"], "arn": rule.get("Arn"), "state": rule["State"], "pattern": rule.get("EventPattern"), "schedule": rule.get("ScheduleExpression"), "targets": [{"id": t["Id"], "arn": t["Arn"], "has_transformer": bool(t.get("InputTransformer")), "input_path": t.get("InputPath"), "dlq": t.get("DeadLetterConfig")} for t in tp.get("Targets", [])]})
                next_rule = rp.get("NextToken")
                if not next_rule:
                    break
            report["buses"].append({"name": bus["Name"], "arn": bus["Arn"], "rules": rules})
        token = page.get("NextToken")
        if not token:
            break
    # Check explicitly scoped resources as well: missing inventory permission
    # does not by itself prove that scoped deployment operations are denied.
    exact_bus_name = f"hear-notifications-{stage}"
    bus_result = read("events", "describe_event_bus", Name=exact_bus_name)
    report["exact_bus"] = {"name": exact_bus_name, "verified_arn": bus_result.get("Arn")}
    deployment_role = "github-actions-hear-deploy"
    inline_names = read("iam", "list_role_policies", RoleName=deployment_role).get("PolicyNames", [])
    policies = []
    for name in inline_names:
        value = read("iam", "get_role_policy", RoleName=deployment_role, PolicyName=name)
        document = value.get("PolicyDocument", {})
        statements = document.get("Statement", []) if isinstance(document, dict) else []
        policies.append({"name": name, "statements": statements})
    attached = read("iam", "list_attached_role_policies", RoleName=deployment_role).get("AttachedPolicies", [])
    for policy in attached:
        value = read("iam", "get_policy", PolicyArn=policy["PolicyArn"]).get("Policy", {})
        if value.get("DefaultVersionId"):
            document = read("iam", "get_policy_version", PolicyArn=policy["PolicyArn"], VersionId=value["DefaultVersionId"]).get("PolicyVersion", {}).get("Document", {})
            policies.append({"name": policy["PolicyName"], "statements": document.get("Statement", []) if isinstance(document, dict) else []})
    report["deployment_policies"] = policies
    report["roles_anywhere_anchors"] = [{"name": x.get("name"), "arn": x.get("trustAnchorArn"), "enabled": x.get("enabled")} for x in read("rolesanywhere", "list_trust_anchors").get("trustAnchors", [])]
    Path("aws-setup-report").mkdir(exist_ok=True)
    Path(f"aws-setup-report/{environment}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
