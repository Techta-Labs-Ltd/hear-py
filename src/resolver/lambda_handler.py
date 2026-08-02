from __future__ import annotations

import logging
import json
import os
import time
import uuid

from src.resolver.correction import command_corrector
from src.resolver.ambiguity import resolve_ambiguity_follow_up
from src.resolver.integration import resolve_for_alexa, resolve_organization_follow_up
from src.resolver.location import resolve_location_phrase
from src.resolver.normalize import is_generic_organization_request
from src.resolver.taxonomy import taxonomy_manager
from src.services.semantic_routing import semantic_intent_router
from src.utils.speech import resolved_search_request_label

logger = logging.getLogger(__name__)
CONTRACT_VERSION = 1


def _emit_metrics(operation: str, duration_ms: float, failed: bool) -> None:
    function_name = os.getenv("AWS_LAMBDA_FUNCTION_NAME", "Hear-Resolver-Python")
    print(json.dumps({
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "Hear/Resolver",
                "Dimensions": [["FunctionName", "Operation"]],
                "Metrics": [
                    {"Name": "Latency", "Unit": "Milliseconds"},
                    {"Name": "Errors", "Unit": "Count"},
                ],
            }],
        },
        "FunctionName": function_name,
        "Operation": operation,
        "Latency": duration_ms,
        "Errors": 1 if failed else 0,
    }, separators=(",", ":")))

def _entities(plan) -> list[dict]:
    return [
        {
            "type": entity.entity_type,
            "id": entity.entity_id,
            "canonicalValue": entity.canonical_value,
            "originalText": entity.original_text,
            "confidence": entity.confidence,
            "method": entity.method,
            "start": entity.start,
            "end": entity.end,
            "metadata": entity.metadata,
        }
        for entity in plan.entities
    ]


def _confirmation_label(slots: dict) -> str:
    source = (
        slots.get("organizationName")
        or slots.get("creatorName")
        or slots.get("publicationName")
    )
    return resolved_search_request_label(slots, source)


def _resolve_search(event: dict, *, organization_follow_up: bool = False) -> dict:
    original = str(event.get("utterance") or "").strip()
    correction = command_corrector.correct(original)
    corrected = correction.utterance
    corrections = list(correction.corrections)
    resolve = resolve_organization_follow_up if organization_follow_up else resolve_for_alexa
    resolve_args = (
        corrected,
        str(event.get("alexaUserId") or ""),
        str(event.get("timezone") or "Europe/London"),
    )
    result = (
        resolve(*resolve_args)
        if organization_follow_up
        else resolve(
            *resolve_args,
            alexa_intent=str(event.get("alexaIntent") or ""),
        )
    )
    slots = dict(result.get("slots") or {})
    if is_generic_organization_request(corrected):
        slots["genericOrganizationRequest"] = True
    plan = result.get("searchPlan")
    ambiguities = list(slots.get("ambiguousReferences") or [])
    unresolved = list(slots.get("unresolvedReferences") or [])
    status = "ambiguous" if ambiguities else "unresolved" if unresolved else "resolved"
    return {
        "version": CONTRACT_VERSION,
        "requestId": str(event.get("requestId") or uuid.uuid4()),
        "status": status,
        "originalUtterance": original,
        "normalizedUtterance": getattr(plan, "normalized_text", corrected),
        "corrections": corrections,
        "intent": result.get("intent") or "general",
        "confidence": float(getattr(plan, "confidence", 0.0) or 0.0),
        "entities": _entities(plan) if plan is not None else [],
        "slots": slots,
        "confirmationLabel": _confirmation_label(slots),
        "searchPayload": dict(slots.get("searchPlan") or {}),
        "alternatives": list(result.get("alternatives") or []),
        "ambiguities": ambiguities,
        "unresolvedReferences": unresolved,
        "taxonomyRevision": getattr(plan, "taxonomy_revision", taxonomy_manager.snapshot.revision),
        "timingMs": dict(getattr(plan, "timing_ms", {}) or {}),
    }

def handler(event: dict, context=None) -> dict:
    started = time.perf_counter()
    request = event if isinstance(event, dict) else {}
    operation = str(request.get("operation") or "resolve_search")
    if int(request.get("version") or 0) != CONTRACT_VERSION:
        return {"version": CONTRACT_VERSION, "status": "error", "error": "unsupported_version"}
    try:
        if operation == "resolve_location":
            resolution = resolve_location_phrase(str(request.get("utterance") or ""))
            response = {
                "version": CONTRACT_VERSION,
                "requestId": str(request.get("requestId") or uuid.uuid4()),
                "status": "resolved" if resolution.get("match") else "ambiguous" if resolution.get("candidates") else "unresolved",
                "resolution": resolution,
                "taxonomyRevision": taxonomy_manager.snapshot.revision,
            }
        elif operation == "resolve_ambiguity_follow_up":
            response = {
                "version": CONTRACT_VERSION,
                "requestId": str(request.get("requestId") or uuid.uuid4()),
                **resolve_ambiguity_follow_up(
                    str(request.get("utterance") or ""),
                    dict(request.get("context") or {}),
                ),
                "taxonomyRevision": taxonomy_manager.snapshot.revision,
            }
        elif operation in {"resolve_search", "resolve_organization_follow_up"}:
            response = _resolve_search(
                request,
                organization_follow_up=operation == "resolve_organization_follow_up",
            )
        else:
            response = {"version": CONTRACT_VERSION, "status": "error", "error": "unsupported_operation"}
    except Exception:
        logger.exception("Resolver request failed operation=%s", operation)
        response = {"version": CONTRACT_VERSION, "status": "error", "error": "resolver_failure"}
    response["resolverDurationMs"] = round((time.perf_counter() - started) * 1000, 3)
    _emit_metrics(operation, response["resolverDurationMs"], response.get("status") == "error")
    return response
