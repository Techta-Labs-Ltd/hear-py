from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping


@dataclass(frozen=True, slots=True)
class SuggestionDecision:
    kind: Literal["lost", "action", "feedback", "unknown"]
    action: str | None = None
    intent: str | None = None
    slots: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", MappingProxyType(deepcopy(dict(self.slots))))


class SuggestionPolicy:
    _ACTION_MAP = {
        "creator": ("play_creator", "creator", lambda query: {"creatorQuery": query}),
        "organization": (
            "play_organization",
            "organization",
            lambda query: {"organizationQuery": query},
        ),
        "category": ("play_content", "category", lambda query: {"category": query}),
        "general": ("play_content", "general", lambda query: {"topic": query}),
        "local": ("play_content", "local", lambda _query: {}),
        "publication": (
            "play_content",
            "publication",
            lambda query: {
                "isPublication": True,
                "residualQuery": query,
                "searchPlan": {
                    "query": query,
                    "filter": {"isPublication": True},
                    "sort": "trending",
                },
            },
        ),
        "following": ("play_content", "following", lambda _query: {}),
        "trending": ("browse_trending", None, lambda _query: {}),
        "browse": ("browse_content", None, lambda _query: {}),
        "show_more": ("browse_more", None, lambda _query: {}),
    }

    @classmethod
    def decide(cls, store: dict) -> SuggestionDecision:
        suggestions = store.get("pendingNlpSuggestion") or []
        top = suggestions[0] if isinstance(suggestions, list) and suggestions else None
        if not isinstance(top, dict):
            return SuggestionDecision("lost")
        intent = str(top.get("intent") or "")
        query = str(top.get("query") or "")
        mapped = cls._ACTION_MAP.get(intent)
        if mapped:
            action, target_intent, slot_builder = mapped
            return SuggestionDecision(
                "action", action=action, intent=target_intent, slots=slot_builder(query)
            )
        if store.get("awaitingFeedback") and intent in {
            "feedback_enjoyed",
            "feedback_not_enjoyed",
        }:
            return SuggestionDecision("feedback", action=intent)
        return SuggestionDecision("unknown")
