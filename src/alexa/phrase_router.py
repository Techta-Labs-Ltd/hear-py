from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from src.constants.discovery import DiscoveryConstants
from src.utils.filters import SearchFilterUtils


@dataclass(frozen=True, slots=True)
class PhraseRoute:
    intent_name: str
    slots: tuple[tuple[str, str], ...] = ()

    def slot_map(self) -> dict[str, dict[str, str]]:
        return {
            name: {"name": name, "value": value}
            for name, value in self.slots
            if value
        }


class PhraseRouter:
    """Deterministically classify broad Alexa search phrases before resolution.

    This deliberately uses the standard-library regular-expression engine plus
    the existing creator, organization, and locality classifiers. It is fast,
    testable, and does not require a heavyweight NLP model in Lambda.
    """

    _POLITE_PREFIX = re.compile(r"^(?:please\s+)?(?:(?:can|could)\s+you\s+)?")
    _TRENDING = re.compile(
        r"\b(?:trending|trend|popular|top\s+(?:content|picks?))\b"
    )
    _RECOMMENDATION = re.compile(
        r"\b(?:recommend(?:ation)?s?|recommended|what\s+do\s+you\s+recommend(?:ed)?|surprise\s+me|what(?:'s|\s+is)\s+good|find\s+me\s+something\s+good)\b"
    )
    _TOPIC_SUFFIX = re.compile(r"\b(?:in|on|about)\s+(.+)$")
    _LOCAL_COMMUNITY = re.compile(
        r"\b(?:local\s+(?:content|community|recordings?|audio)|(?:my\s+)?local\s+community|near\s+(?:me|here)|nearby|around\s+(?:me|here)|from\s+my\s+(?:city|town|area)|my\s+(?:city|town|area))\b"
    )
    _RECOMMENDATION_TOPIC = re.compile(
        r"\b(?:recommend|discover|curate)\s+(?:me\s+)?(.+)$"
    )
    _HELP = re.compile(
        r"(?:help|what\s+can\s+(?:i\s+say|you\s+do)|how\s+does\s+this\s+work|instructions|guide\s+me)"
    )
    _HELP_MORE = re.compile(r"(?:more|tell\s+me\s+more|more\s+help|the\s+full\s+guide)")
    _CONTROL_RULES = (
        (re.compile(r"\b(?:speed\s+(?:it\s+)?up|increase(?:\s+(?:the\s+)?)?speed|play\s+faster|faster)\b"), "IncreaseSpeedIntent"),
        (re.compile(r"\b(?:slow\s+(?:it\s+)?down|decrease(?:\s+(?:the\s+)?)?speed|play\s+slower|slower)\b"), "DecreaseSpeedIntent"),
        (re.compile(r"\b(?:feedback(?:\s+check)?|give(?:\s+my)?\s+feedback|leave\s+feedback|rate\s+this(?:\s+(?:content|recording))?)\b"), "RateContentIntent"),
        (re.compile(r"\b(?:check(?:\s+for)?\s+(?:my\s+)?updates|what\s+are\s+my\s+updates|do\s+i\s+have\s+any\s+(?:updates|notifications)|read\s+my\s+notifications)\b"), "HearNotificationsIntent"),
        (re.compile(r"\b(?:enable|turn\s+on)\s+notifications\b|\bnotify\s+me\s+about\s+new\s+content\b"), "EnableNotificationsIntent"),
        (re.compile(r"\b(?:disable|turn\s+off|stop)\s+notifications\b"), "DisableNotificationsIntent"),
        (re.compile(r"\b(?:pause(?:\s+(?:playback|this))?)\b"), "AMAZON.PauseIntent"),
        (re.compile(r"\b(?:resume|continue(?:\s+playing)?)\b"), "AMAZON.ResumeIntent"),
        (re.compile(r"\b(?:next(?:\s+recording)?|skip\s+this\s+recording)\b"), "AMAZON.NextIntent"),
        (re.compile(r"\bprevious(?:\s+recording)?\b"), "AMAZON.PreviousIntent"),
        (re.compile(r"\b(?:repeat|replay|play\s+again)\b"), "AMAZON.RepeatIntent"),
        (re.compile(r"\b(?:start\s+over|restart|from\s+the\s+beginning)\b"), "AMAZON.StartOverIntent"),
        (re.compile(r"\b(?:rewind|skip\s+back|go\s+back\s+a\s+bit)\b"), "RewindIntent"),
        (re.compile(r"\b(?:fast\s+forward|skip\s+ahead|go\s+forward)\b"), "FastForwardIntent"),
        (re.compile(r"\b(?:what(?:'s|\s+is)\s+this\s+about|who\s+is\s+this\s+by)\b"), "WhatsThisAboutIntent"),
        (re.compile(r"\b(?:who\s+(?:made|recorded)\s+this|who\s+is\s+the\s+creator)\b"), "WhoIsCreatorIntent"),
        (re.compile(r"\b(?:follow(?:\s+this\s+creator)?|subscribe)\b"), "FollowCreatorIntent"),
        (re.compile(r"\b(?:unfollow(?:\s+this\s+creator)?|unsubscribe)\b"), "UnfollowCreatorIntent"),
        (re.compile(r"\b(?:report\s+this(?:\s+content)?|flag\s+this)\b"), "ReportContentIntent"),
        (re.compile(r"\breport\s+(?:this|the)\s+creator\b"), "ReportCreatorIntent"),
    )
    _SPEED_VALUES = {
        "normal speed": "normal",
        "regular speed": "normal",
        "reset speed": "normal",
        "half speed": "half",
        "double speed": "double",
    }
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
    INTERRUPT_CONTROL_INTENTS = frozenset(
        {
            "IncreaseSpeedIntent",
            "DecreaseSpeedIntent",
            "RateContentIntent",
            "ReportContentIntent",
        }
    )

    @classmethod
    def normalize(cls, phrase: object) -> str:
        text = str(phrase or "").casefold().replace("’", "'")
        text = re.sub(r"'s\b", " is", text)
        tokens = re.findall(r"[a-z0-9]+", text)
        collapsed: list[str] = []
        for token in tokens:
            if not collapsed or collapsed[-1] != token:
                collapsed.append(token)
        normalized = " ".join(collapsed)
        return cls._POLITE_PREFIX.sub("", normalized).strip()

    @classmethod
    def _topic(cls, phrase: str) -> str:
        match = cls._TOPIC_SUFFIX.search(phrase)
        return match.group(1).strip() if match else ""

    @classmethod
    def _recommendation_topic(cls, phrase: str) -> str:
        match = cls._RECOMMENDATION_TOPIC.search(phrase)
        if not match:
            return ""
        candidate = match.group(1).strip()
        return "" if candidate in {"something", "me something", "something good"} else candidate

    @classmethod
    def is_help_more(cls, phrase: object) -> bool:
        return bool(cls._HELP_MORE.fullmatch(cls.normalize(phrase)))

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
            return PhraseRoute(intent_name)
        return None

    @classmethod
    def control_route(
        cls, phrase: object, *, allowed: frozenset[str] | None = None
    ) -> PhraseRoute | None:
        normalized = cls.normalize(phrase)
        if not normalized:
            return None
        for pattern, intent_name in cls._CONTROL_RULES:
            if (allowed is None or intent_name in allowed) and pattern.fullmatch(normalized):
                return PhraseRoute(intent_name)
        return cls._fuzzy_control_route(normalized, allowed)

    @classmethod
    def classify(cls, phrase: object) -> PhraseRoute | None:
        normalized = cls.normalize(phrase)
        if not normalized:
            return None
        speed = cls._SPEED_VALUES.get(normalized)
        if speed:
            return PhraseRoute("SetPlaybackSpeedIntent", (("speed", speed),))
        if cls._HELP.fullmatch(normalized):
            return PhraseRoute("AMAZON.HelpIntent")
        if cls._LOCAL_COMMUNITY.search(normalized):
            return PhraseRoute("PlayLocalIntent", (("localQuery", normalized),))
        if normalized in DiscoveryConstants.TRENDING_HINTS or cls._TRENDING.search(normalized):
            topic = cls._topic(normalized)
            return PhraseRoute("WhatsTrendingIntent", (("topic", topic),) if topic else ())
        if cls._RECOMMENDATION.search(normalized):
            topic = cls._recommendation_topic(normalized)
            return PhraseRoute(
                "PlayRecommendationIntent",
                (("recommendationQuery", topic),) if topic else (),
            )
        if SearchFilterUtils.organization_request_kind(
            normalized, organization_intent=True
        ) == "generic" and re.search(r"\b(?:talking|audio|spoken)\b", normalized):
            return PhraseRoute(
                "ChooseSourceKindIntent", (("sourceKind", "talking newspaper"),)
            )
        if SearchFilterUtils.is_generic_creator_request(normalized):
            return PhraseRoute("ChooseSourceKindIntent", (("sourceKind", "creator"),))
        return cls.control_route(normalized)
