from __future__ import annotations

import logging
import json
import os
import time
import uuid

from config import settings
from src.resolver.correction import command_corrector
from src.resolver.alexa import alexa_resolver, resolve_ambiguity_follow_up
from src.resolver.location import resolve_location_phrase
from src.resolver.normalization import is_generic_organization_request
from src.resolver.taxonomy import taxonomy_manager
from src.resolver.taxonomy import TaxonomySyncUnavailable, taxonomy_sync_client
from src.utils.speech import resolved_search_request_label

logger = logging.getLogger(__name__)


class LambdaResolverHandler:
    CONTRACT_VERSION = 1

    @staticmethod
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

    @staticmethod
    def _serialize_entities(plan) -> list[dict]:
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

    @staticmethod
    def _build_confirmation_label(slots: dict) -> str:
        source = (
            slots.get("organizationName")
            or slots.get("creatorName")
            or slots.get("publicationName")
        )
        return resolved_search_request_label(slots, source)

    @staticmethod
    def _resolve_search(event: dict, *, organization_follow_up: bool = False, taxonomy_view=None) -> dict:
        original = str(event.get("utterance") or "").strip()
        correction = command_corrector.correct(original, snapshot=taxonomy_view)
        corrected = correction.utterance
        corrections = list(correction.corrections)
        resolve = (
            alexa_resolver.resolve_organization_follow_up
            if organization_follow_up
            else alexa_resolver.resolve
        )
        resolve_args = (
            corrected,
            str(event.get("alexaUserId") or ""),
            str(event.get("timezone") or "Europe/London"),
        )
        result = (
            resolve(*resolve_args, taxonomy_view=taxonomy_view)
            if organization_follow_up
            else resolve(
                *resolve_args,
                alexa_intent=str(event.get("alexaIntent") or ""),
                taxonomy_view=taxonomy_view,
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
            "version": LambdaResolverHandler.CONTRACT_VERSION,
            "requestId": str(event.get("requestId") or uuid.uuid4()),
            "status": status,
            "originalUtterance": original,
            "normalizedUtterance": getattr(plan, "normalized_text", corrected),
            "corrections": corrections,
            "intent": result.get("intent") or "general",
            "confidence": float(getattr(plan, "confidence", 0.0) or 0.0),
            "entities": LambdaResolverHandler._serialize_entities(plan) if plan is not None else [],
            "slots": slots,
            "confirmationLabel": LambdaResolverHandler._build_confirmation_label(slots),
            "searchPayload": dict(slots.get("searchPlan") or {}),
            "alternatives": list(result.get("alternatives") or []),
            "ambiguities": ambiguities,
            "unresolvedReferences": unresolved,
            "taxonomyRevision": getattr(plan, "taxonomy_revision", taxonomy_manager.snapshot.revision),
            "timingMs": dict(getattr(plan, "timing_ms", {}) or {}),
        }

    @staticmethod
    def handler(event: dict, context=None) -> dict:
        started = time.perf_counter()
        request = event if isinstance(event, dict) else {}
        operation = str(request.get("operation") or "resolve_search")
        if int(request.get("version") or 0) != LambdaResolverHandler.CONTRACT_VERSION:
            return {"version": LambdaResolverHandler.CONTRACT_VERSION, "status": "error", "error": "unsupported_version"}
        try:
            requested_revision = int(request.get("taxonomyRevision") or 0)
            taxonomy_view = taxonomy_sync_client.ensure_current(requested_revision)
            if operation == "health":
                loaded_revision = int(taxonomy_view.revision) if str(taxonomy_view.revision).isdigit() else 0
                expected_revision = int(settings.HEAR_TAXONOMY_ACTIVE_REVISION or 0)
                ready = not expected_revision or loaded_revision == expected_revision
                response = {
                    "version": LambdaResolverHandler.CONTRACT_VERSION,
                    "status": "ready" if ready else "degraded",
                    "schemaVersion": int(getattr(taxonomy_view, "schema_version", 0)),
                    "taxonomyRevision": taxonomy_view.revision,
                    "recordCount": int(getattr(taxonomy_view, "record_count", len(taxonomy_view.records))),
                    "manifestArtifactCount": int(getattr(taxonomy_view, "artifact_count", 0)),
                    "validatedArtifactCount": int(getattr(taxonomy_view, "artifact_count", 0)),
                    "routingArtifactCount": int(getattr(taxonomy_view, "routing_artifact_count", 0)),
                    "shardArtifactCount": int(getattr(taxonomy_view, "shard_artifact_count", 0)),
                }
            elif operation == "resolve_location":
                resolution = resolve_location_phrase(
                    str(request.get("utterance") or ""),
                    taxonomy_view=taxonomy_view,
                )
                response = {
                    "version": LambdaResolverHandler.CONTRACT_VERSION,
                    "requestId": str(request.get("requestId") or uuid.uuid4()),
                    "status": "resolved" if resolution.get("match") else "ambiguous" if resolution.get("candidates") else "unresolved",
                    "resolution": resolution,
                    "taxonomyRevision": taxonomy_manager.snapshot.revision,
                }
            elif operation == "resolve_ambiguity_follow_up":
                response = {
                    "version": LambdaResolverHandler.CONTRACT_VERSION,
                    "requestId": str(request.get("requestId") or uuid.uuid4()),
                    **resolve_ambiguity_follow_up(
                        str(request.get("utterance") or ""),
                        dict(request.get("context") or {}),
                    ),
                    "taxonomyRevision": taxonomy_manager.snapshot.revision,
                }
            elif operation in {"resolve_search", "resolve_organization_follow_up"}:
                response = LambdaResolverHandler._resolve_search(
                    request,
                    organization_follow_up=operation == "resolve_organization_follow_up",
                    taxonomy_view=taxonomy_view,
                )
            else:
                response = {"version": LambdaResolverHandler.CONTRACT_VERSION, "status": "error", "error": "unsupported_operation"}
        except TaxonomySyncUnavailable as exc:
            response = {
                "version": LambdaResolverHandler.CONTRACT_VERSION,
                "status": "error",
                "error": "taxonomy_sync_unavailable",
                "requiredRevision": exc.required,
                "availableRevision": exc.available,
                "retryable": True,
            }
        except Exception:
            logger.exception("Resolver request failed operation=%s", operation)
            response = {"version": LambdaResolverHandler.CONTRACT_VERSION, "status": "error", "error": "resolver_failure"}
        response["resolverDurationMs"] = round((time.perf_counter() - started) * 1000, 3)
        LambdaResolverHandler._emit_metrics(operation, response["resolverDurationMs"], response.get("status") == "error")
        return response


handler = LambdaResolverHandler.handler
