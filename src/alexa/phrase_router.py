from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import cache
from pathlib import Path

from src.alexa.direct_intents import DirectIntentPolicy
from src.constants.intent_routes import INTENT_ROUTE_RULES, INTERRUPT_ROUTE_INTENTS
from src.utils.filters import SearchFilterUtils
from src.utils.playback import PlaybackUtils


@dataclass(frozen=True, slots=True)
class PhraseRoute:
    intent_name: str
    slots: tuple[tuple[str, str], ...] = ()
    family: str = ""
    rule_name: str = ""

    def slot_map(self) -> dict[str, dict[str, str]]:
        return {name: {"name": name, "value": value} for name, value in self.slots if value}


class PhraseRouter:
    _POLITE_PREFIX = re.compile(r"^(?:please\s+)?(?:(?:can|could)\s+you\s+)?")
    _TOPIC_SUFFIX = re.compile(r"\b(?:in|on|about|for)\s+(?P<topic>.+)$")
    _RECOMMENDATION_TOPIC = re.compile(
        r"\b(?:recommend|suggest|discover|curate)(?:\s+me)?\s+(?P<topic>.+)$"
    )
    _SLOT_MARKER = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")
    _MODEL_PATH = Path(__file__).resolve().parents[2] / "en-GB.json"
    DECLARED_LOCKED_INTENTS = DirectIntentPolicy.BYPASS_RESOLVER_INTENTS | {"PlayLocalIntent"}
    FUZZY_COMMAND_INTENTS = frozenset(
        {
            "SearchLocationIntent",
            "PlayRecommendationIntent",
            "WhatsThisAboutIntent",
            "WhatsTrendingIntent",
            "SetPlaybackSpeedIntent",
            "IncreaseSpeedIntent",
            "DecreaseSpeedIntent",
            "HearNotificationsIntent",
            "EnableNotificationsIntent",
            "DisableNotificationsIntent",
            "RateContentIntent",
            "SkipFeedbackIntent",
            "WhoIsCreatorIntent",
            "FollowCreatorIntent",
            "UnfollowCreatorIntent",
            "ReportContentIntent",
            "ReportCreatorIntent",
            "SetUpAccountIntent",
        }
    )
    _FUZZY_COMMAND_MIN_SCORE = 0.83
    _FUZZY_COMMAND_SINGLE_TOKEN_MIN_SCORE = 0.90
    _FUZZY_COMMAND_MIN_MARGIN = 0.04
    _FUZZY_CONTROL_LEXICON = (
        (
            "IncreaseSpeedIntent",
            (
                ("increase", "speed"),
                ("increment", "speed"),
                ("speed", "up"),
                ("faster",),
            ),
        ),
        (
            "DecreaseSpeedIntent",
            (
                ("decrease", "speed"),
                ("reduce", "speed"),
                ("slow", "down"),
                ("slower",),
            ),
        ),
        (
            "RateContentIntent",
            (
                ("feedback",),
                ("rate", "content"),
                ("rate", "recording"),
                ("give", "feedback"),
            ),
        ),
        (
            "ReportContentIntent",
            (
                ("report", "content"),
                ("report", "recording"),
                ("report", "this"),
                ("flag", "content"),
            ),
        ),
    )
    INTERRUPT_CONTROL_INTENTS = INTERRUPT_ROUTE_INTENTS

    @classmethod
    def normalize(cls, phrase: object) -> str:
        text = str(phrase or "").casefold().replace("’", "'")
        text = re.sub(r"'s\b", " is", text)
        tokens = re.findall(r"[a-z0-9]+", text)
        collapsed: list[str] = []
        for token in tokens:
            if not collapsed or collapsed[-1] != token:
                collapsed.append(token)
        return cls._POLITE_PREFIX.sub("", " ".join(collapsed)).strip()

    @classmethod
    def _topic(cls, phrase: str) -> str:
        match = cls._TOPIC_SUFFIX.search(phrase)
        return match.group("topic").strip() if match else ""

    @classmethod
    def _recommendation_topic(cls, phrase: str) -> str:
        suffix = cls._topic(phrase)
        if suffix and suffix not in {"me", "something", "something good"}:
            return suffix
        match = cls._RECOMMENDATION_TOPIC.search(phrase)
        if not match:
            return ""
        candidate = re.sub(r"^(?:me\s+)?", "", match.group("topic").strip())
        return (
            ""
            if candidate
            in {"something", "something good", "something for me", "something good for me"}
            else candidate
        )

    @classmethod
    def _declared_pattern(
        cls, sample: str
    ) -> tuple[re.Pattern[str], tuple[tuple[str, str], ...]] | None:
        parts: list[str] = []
        captures: list[tuple[str, str]] = []
        literal_seen = False
        position = 0
        slot_counts: dict[str, int] = {}
        for match in cls._SLOT_MARKER.finditer(sample):
            literal = cls.normalize(sample[position : match.start()])
            if literal:
                parts.append(re.escape(literal).replace(r"\ ", r"\s+"))
                literal_seen = True
            slot_name = match.group(1)
            slot_counts[slot_name] = slot_counts.get(slot_name, 0) + 1
            capture_name = f"{slot_name}_{slot_counts[slot_name]}"
            parts.append(f"(?P<{capture_name}>.+?)")
            captures.append((slot_name, capture_name))
            position = match.end()
        literal = cls.normalize(sample[position:])
        if literal:
            parts.append(re.escape(literal).replace(r"\ ", r"\s+"))
            literal_seen = True
        if not literal_seen:
            return None
        return re.compile(r"^" + r"\s+".join(parts) + r"$"), tuple(captures)

    @classmethod
    @cache
    def _declared_locked_routes(
        cls,
    ) -> tuple[tuple[str, re.Pattern[str], tuple[tuple[str, str], ...], bool], ...]:
        model = json.loads(cls._MODEL_PATH.read_text(encoding="utf-8"))
        routes = []
        for intent in model["interactionModel"]["languageModel"]["intents"]:
            intent_name = str(intent.get("name") or "")
            if intent_name not in cls.DECLARED_LOCKED_INTENTS:
                continue
            for sample in intent.get("samples") or ():
                pattern = cls._declared_pattern(str(sample))
                if pattern:
                    expression, captures = pattern
                    routes.append((intent_name, expression, captures, bool(captures)))
        return tuple(routes)

    @classmethod
    @cache
    def _declared_fuzzy_command_routes(
        cls,
    ) -> tuple[tuple[str, str | None, str, str, str], ...]:
        model = json.loads(cls._MODEL_PATH.read_text(encoding="utf-8"))
        routes: list[tuple[str, str | None, str, str, str]] = []
        for intent in model["interactionModel"]["languageModel"]["intents"]:
            intent_name = str(intent.get("name") or "")
            if intent_name not in cls.FUZZY_COMMAND_INTENTS:
                continue
            for sample in intent.get("samples") or ():
                value = str(sample)
                markers = list(cls._SLOT_MARKER.finditer(value))
                if not markers:
                    normalized = cls.normalize(value)
                    if normalized:
                        routes.append((intent_name, None, normalized, "", ""))
                    continue
                if len(markers) != 1:
                    continue
                marker = markers[0]
                prefix = cls.normalize(value[: marker.start()])
                suffix = cls.normalize(value[marker.end() :])
                if not prefix and not suffix:
                    continue
                routes.append(
                    (
                        intent_name,
                        marker.group(1),
                        "",
                        prefix,
                        suffix,
                    )
                )
        return tuple(routes)

    @staticmethod
    def _phrase_similarity(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        spaced = SequenceMatcher(None, left, right).ratio()
        compact = SequenceMatcher(
            None,
            left.replace(" ", ""),
            right.replace(" ", ""),
        ).ratio()
        return max(spaced, compact)

    @classmethod
    def _fuzzy_template_match(
        cls,
        normalized: str,
        slot_name: str | None,
        literal: str,
        prefix: str,
        suffix: str,
    ) -> tuple[float, tuple[tuple[str, str], ...]] | None:
        if slot_name is None:
            score = cls._phrase_similarity(normalized, literal)
            return score, ()
        tokens = normalized.split()
        if len(tokens) < 2:
            return None
        best_score = 0.0
        best_value = ""
        if prefix and not suffix:
            for split in range(1, len(tokens)):
                carrier = " ".join(tokens[:split])
                value = " ".join(tokens[split:]).strip()
                score = cls._phrase_similarity(carrier, prefix)
                if value and score > best_score:
                    best_score, best_value = score, value
        elif suffix and not prefix:
            for split in range(1, len(tokens)):
                value = " ".join(tokens[:split]).strip()
                carrier = " ".join(tokens[split:])
                score = cls._phrase_similarity(carrier, suffix)
                if value and score > best_score:
                    best_score, best_value = score, value
        else:
            for left in range(1, len(tokens) - 1):
                for right in range(left + 1, len(tokens)):
                    left_phrase = " ".join(tokens[:left])
                    value = " ".join(tokens[left:right]).strip()
                    right_phrase = " ".join(tokens[right:])
                    prefix_score = cls._phrase_similarity(left_phrase, prefix)
                    suffix_score = cls._phrase_similarity(right_phrase, suffix)
                    score = (
                        prefix_score * max(len(prefix), 1)
                        + suffix_score * max(len(suffix), 1)
                    ) / (max(len(prefix), 1) + max(len(suffix), 1))
                    if value and min(prefix_score, suffix_score) >= 0.72 and score > best_score:
                        best_score, best_value = score, value
        if not best_value:
            return None
        if slot_name == "speed" and PlaybackUtils.normalise_speed(best_value) is None:
            return None
        return best_score, ((slot_name, best_value),)

    @classmethod
    def _fuzzy_command_route(
        cls, normalized: str, allowed: frozenset[str] | None = None
    ) -> PhraseRoute | None:
        best_by_intent: dict[str, tuple[float, tuple[tuple[str, str], ...]]] = {}
        for intent_name, slot_name, literal, prefix, suffix in cls._declared_fuzzy_command_routes():
            if allowed is not None and intent_name not in allowed:
                continue
            matched = cls._fuzzy_template_match(
                normalized,
                slot_name,
                literal,
                prefix,
                suffix,
            )
            if not matched:
                continue
            score, slots = matched
            current = best_by_intent.get(intent_name)
            if current is None or score > current[0]:
                best_by_intent[intent_name] = (score, slots)
        if not best_by_intent:
            return None
        ranked = sorted(
            (
                (score, intent_name, slots)
                for intent_name, (score, slots) in best_by_intent.items()
            ),
            reverse=True,
        )
        best_score, intent_name, slots = ranked[0]
        next_score = ranked[1][0] if len(ranked) > 1 else 0.0
        single_token = len(normalized.split()) == 1
        minimum = (
            cls._FUZZY_COMMAND_SINGLE_TOKEN_MIN_SCORE
            if single_token
            else cls._FUZZY_COMMAND_MIN_SCORE
        )
        if best_score < minimum or best_score - next_score < cls._FUZZY_COMMAND_MIN_MARGIN:
            return None
        family = next(
            (
                rule.family
                for rule in INTENT_ROUTE_RULES
                if rule.intent_name == intent_name
            ),
            "fuzzy_command",
        )
        return PhraseRoute(intent_name, slots, family, "fuzzy_model")

    @classmethod
    def _declared_locked_route(cls, normalized: str, *, templates: bool) -> PhraseRoute | None:
        for intent_name, expression, captures, is_template in cls._declared_locked_routes():
            if is_template != templates:
                continue
            match = expression.fullmatch(normalized)
            if not match:
                continue
            slots = tuple(
                (slot_name, value.strip())
                for slot_name, capture_name in captures
                if (value := match.group(capture_name)) and value.strip()
            )
            if intent_name == "SetPlaybackSpeedIntent" and any(
                slot_name == "speed" and PlaybackUtils.normalise_speed(value) is None
                for slot_name, value in slots
            ):
                continue
            return PhraseRoute(intent_name, slots, "declared_sample", "model_sample")
        return None

    @staticmethod
    def _alias_score(tokens: list[str], alias: tuple[str, ...]) -> float:
        if len(tokens) < len(alias):
            return 0.0
        available = set(range(len(tokens)))
        scores: list[float] = []
        for expected in alias:
            index, score = max(
                (
                    (index, SequenceMatcher(None, tokens[index], expected).ratio())
                    for index in available
                ),
                key=lambda item: item[1],
            )
            available.remove(index)
            scores.append(score)
        if min(scores) < 0.72:
            return 0.0
        if len(alias) == 1 and len(tokens) > 1 and scores[0] < 0.90:
            return 0.0
        return sum(scores) / len(scores)

    @classmethod
    def _fuzzy_control_route(
        cls, normalized: str, allowed: frozenset[str] | None = None
    ) -> PhraseRoute | None:
        tokens = normalized.split()
        if not tokens:
            return None
        scores: list[tuple[float, str]] = []
        for intent_name, aliases in cls._FUZZY_CONTROL_LEXICON:
            if allowed is not None and intent_name not in allowed:
                continue
            score = max(cls._alias_score(tokens, alias) for alias in aliases)
            if score:
                scores.append((score, intent_name))
        if not scores:
            return None
        scores.sort(reverse=True)
        best_score, intent_name = scores[0]
        next_score = scores[1][0] if len(scores) > 1 else 0.0
        if best_score >= 0.78 and best_score - next_score >= 0.10:
            return PhraseRoute(intent_name, family="fuzzy_control", rule_name="fuzzy")
        return None

    @classmethod
    def _semantic_route(
        cls, normalized: str, allowed: frozenset[str] | None = None
    ) -> PhraseRoute | None:
        for rule in INTENT_ROUTE_RULES:
            if allowed is not None and rule.intent_name not in allowed:
                continue
            slots = rule.match(normalized)
            if slots is None:
                continue
            if rule.family == "trending":
                topic = cls._topic(normalized)
                slots = (("topic", topic),) if topic else ()
            elif rule.family == "recommendation":
                topic = cls._recommendation_topic(normalized)
                slots = (("recommendationQuery", topic),) if topic else ()
            elif rule.family == "local_discovery":
                slots = (("localQuery", normalized),)
            return PhraseRoute(rule.intent_name, slots, rule.family, rule.rule_name)
        return None

    @classmethod
    def _generic_discovery_route(cls, normalized: str) -> PhraseRoute | None:
        if SearchFilterUtils.organization_request_kind(
            normalized, organization_intent=True
        ) == "generic" and re.search(r"\b(?:talking|audio|spoken)\b", normalized):
            return PhraseRoute(
                "ChooseSourceKindIntent",
                (("sourceKind", "talking newspaper"),),
                "generic_discovery",
                "talking_newspaper",
            )
        if SearchFilterUtils.is_generic_creator_request(normalized):
            return PhraseRoute(
                "ChooseSourceKindIntent",
                (("sourceKind", "creator"),),
                "generic_discovery",
                "creator",
            )
        return None

    @classmethod
    def control_route(
        cls, phrase: object, *, allowed: frozenset[str] | None = None
    ) -> PhraseRoute | None:
        normalized = cls.normalize(phrase)
        if not normalized:
            return None
        return (
            cls._semantic_route(normalized, allowed)
            or cls._fuzzy_command_route(normalized, allowed)
            or cls._fuzzy_control_route(normalized, allowed)
        )

    @classmethod
    def route_phrases(
        cls,
        phrases: tuple[str, ...],
        *,
        allowed_controls: frozenset[str] | None = None,
    ) -> PhraseRoute | None:
        normalized = tuple(
            dict.fromkeys(phrase for value in phrases if (phrase := cls.normalize(value)))
        )
        for phrase in normalized:
            route = (
                cls.control_route(phrase, allowed=allowed_controls)
                if allowed_controls is not None
                else cls.classify(phrase)
            )
            if route:
                return route
        return None

    @classmethod
    def classify(cls, phrase: object) -> PhraseRoute | None:
        normalized = cls.normalize(phrase)
        if not normalized:
            return None
        semantic_route = cls._semantic_route(normalized)
        if semantic_route:
            return semantic_route
        generic_route = cls._generic_discovery_route(normalized)
        if generic_route:
            return generic_route
        for templates in (False, True):
            if route := cls._declared_locked_route(normalized, templates=templates):
                return route
        return cls._fuzzy_command_route(normalized) or cls._fuzzy_control_route(normalized)
