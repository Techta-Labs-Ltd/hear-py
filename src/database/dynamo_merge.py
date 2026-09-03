from __future__ import annotations

import json
from copy import deepcopy

from config import settings
from src.constants.state import StateSchema


class DynamoConflictMerge:
    COUNTER_FIELDS = frozenset(
        {
            "launchCount",
            "playCount",
            "onboardingRetries",
            "onboardingTownAttempts",
            "onboardingTownResolverFailures",
        }
    )

    @staticmethod
    def collection_key(field: str, item) -> str:
        if field == "answeredFeedbackKeys":
            return str(item)
        if not isinstance(item, dict):
            return json.dumps(item, sort_keys=True, default=str)
        if field == "playHistory":
            return str(item.get("subjectId") or item.get("id") or "")
        if field == "followedCreators":
            return f"{item.get('type', 'creator')}:{item.get('id')}"
        return str(item.get("feedbackKey") or json.dumps(item, sort_keys=True, default=str))

    @staticmethod
    def collection(field: str, current, incoming, previous) -> list:
        current_items = list(current) if isinstance(current, list) else []
        incoming_items = list(incoming) if isinstance(incoming, list) else []
        previous_items = list(previous) if isinstance(previous, list) else []
        previous_keys = {
            DynamoConflictMerge.collection_key(field, item) for item in previous_items
        }
        incoming_keys = {
            DynamoConflictMerge.collection_key(field, item) for item in incoming_items
        }
        removed = previous_keys - incoming_keys
        limits = {
            "answeredFeedbackKeys": 50,
            "feedbackCandidates": 5,
            "followedCreators": 50,
            "playHistory": min(settings.max_history, 20),
        }
        limit = limits.get(field, 20)
        if field == "playHistory":
            incoming_new = [
                deepcopy(item)
                for item in incoming_items
                if DynamoConflictMerge.collection_key(field, item) not in previous_keys
            ]
            current_new = [
                deepcopy(item)
                for item in current_items
                if DynamoConflictMerge.collection_key(field, item) not in previous_keys
            ]
            remaining = [
                deepcopy(item)
                for item in incoming_items + current_items
                if DynamoConflictMerge.collection_key(field, item) not in removed
            ]
            deduplicated = []
            seen = set()
            for item in incoming_new + current_new + remaining:
                key = DynamoConflictMerge.collection_key(field, item)
                if key in seen:
                    continue
                seen.add(key)
                deduplicated.append(item)
            return deduplicated[:limit]
        merged = [
            deepcopy(item)
            for item in current_items
            if DynamoConflictMerge.collection_key(field, item) not in removed
        ]
        positions = {
            DynamoConflictMerge.collection_key(field, item): index
            for index, item in enumerate(merged)
        }
        for item in incoming_items:
            key = DynamoConflictMerge.collection_key(field, item)
            if key in positions:
                merged[positions[key]] = deepcopy(item)
            else:
                positions[key] = len(merged)
                merged.append(deepcopy(item))
        return merged[-limit:]

    @staticmethod
    def resolve(
        latest: dict, requested: dict, original: dict, changed_fields: list[str]
    ) -> dict:
        merged = deepcopy(latest)
        active_incoming = requested.get("activePlayback")
        active_latest = latest.get("activePlayback")
        incoming_playback_is_newer = (
            not isinstance(active_latest, dict)
            or not isinstance(active_incoming, dict)
            or int(active_incoming.get("eventTimestamp") or active_incoming.get("updatedAt") or 0)
            >= int(active_latest.get("eventTimestamp") or active_latest.get("updatedAt") or 0)
        )
        for field in changed_fields:
            incoming = deepcopy(requested.get(field, StateSchema.default_for(field)))
            previous = original.get(field, StateSchema.default_for(field))
            current = latest.get(field, StateSchema.default_for(field))
            if (
                field in DynamoConflictMerge.COUNTER_FIELDS
                and isinstance(incoming, int)
                and not isinstance(incoming, bool)
                and isinstance(previous, int)
                and not isinstance(previous, bool)
            ):
                value = max(0, int(current or 0) + incoming - previous)
            elif field in {
                "answeredFeedbackKeys",
                "feedbackCandidates",
                "followedCreators",
                "playHistory",
            }:
                value = DynamoConflictMerge.collection(field, current, incoming, previous)
            elif field == "activePlayback" and not incoming_playback_is_newer:
                continue
            else:
                value = incoming
            if value == StateSchema.default_for(field):
                merged.pop(field, None)
            else:
                merged[field] = value
        return merged
