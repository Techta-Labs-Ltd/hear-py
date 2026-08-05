"""IAM-authenticated client for the dedicated Hear resolver Lambda."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

import boto3
from botocore.config import Config

from config import settings

logger = logging.getLogger(__name__)
_client = None


class ResolverUnavailable(RuntimeError):
    pass


def _lambda_client():
    global _client
    if _client is None:
        timeout = max(0.5, settings.HEAR_RESOLVER_TIMEOUT_MS / 1000)
        _client = boto3.client(
            "lambda",
            region_name=settings.AWS_REGION or settings.HEAR_DDB_REGION,
            config=Config(
                connect_timeout=min(timeout, 0.5),
                read_timeout=timeout,
                retries={"max_attempts": 0},
            ),
        )
    return _client


def _invoke(payload: dict) -> dict:
    if not settings.HEAR_RESOLVER_FUNCTION_ARN:
        raise ResolverUnavailable("resolver function is not configured")
    response = _lambda_client().invoke(
        FunctionName=settings.HEAR_RESOLVER_FUNCTION_ARN,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )
    if response.get("FunctionError"):
        raise ResolverUnavailable("resolver function returned an error")
    body = json.loads(response["Payload"].read())
    if not isinstance(body, dict) or body.get("version") != 1:
        raise ResolverUnavailable("resolver response contract is invalid")
    if body.get("status") == "error":
        raise ResolverUnavailable(str(body.get("error") or "resolver error"))
    return body


async def resolve_utterance(
    operation: str,
    utterance: str,
    *,
    alexa_intent: str = "",
    alexa_user_id: str | None = None,
    timezone: str = "Europe/London",
    request_id: str = "",
    context: dict | None = None,
    taxonomy_revision: int | None = None,
) -> dict:
    payload = {
        "version": 1,
        "requestId": request_id or str(uuid.uuid4()),
        "operation": operation,
        "utterance": utterance,
        "alexaIntent": alexa_intent,
        "timezone": timezone,
    }
    if alexa_user_id:
        payload["alexaUserId"] = alexa_user_id
    if context:
        payload["context"] = context
    if taxonomy_revision is not None:
        payload["taxonomyRevision"] = int(taxonomy_revision)
    try:
        return await asyncio.to_thread(_invoke, payload)
    except ResolverUnavailable:
        raise
    except Exception as exc:
        logger.warning("Resolver invocation failed error=%s", type(exc).__name__)
        raise ResolverUnavailable("resolver invocation failed") from exc


def reset_resolver_client_for_tests() -> None:
    global _client
    _client = None
