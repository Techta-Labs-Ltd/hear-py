"""Utterance normalization and command/modifier rules."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process


COMMAND_PATTERNS = (
    r"\bcan you\b", r"\bcould you\b", r"\bplease\b", r"\bfind me\b", r"\bfind\b",
    r"\bplay me\b", r"\bplay\b", r"\bgive me\b", r"\bgive us\b",
    r"\blet me hear\b", r"\bi want to hear\b", r"\bi would like to hear\b",
    r"\bi'd like to hear\b", r"\bsearch for\b", r"\bput on\b",
    r"\brecommend(?: me)?\b",
)
LATEST_PATTERNS = (r"\bmost recent\b", r"\blatest\b", r"\bnewest\b", r"\brecent\b")
RECOMMENDED_PATTERNS = (
    r"\brecommend(?:ed)?\b", r"\bfor me\b", r"\bsomething i (?:would|might) like\b",
    r"\bbased on what i listen to\b",
)
LOCAL_PATTERNS = (
    r"\bnear me\b", r"\bnearby\b", r"\blocal\b", r"\bmy area\b",
    r"\baround me\b", r"\bmy city\b", r"\bmy town\b",
)
CONTENT_NOUNS = {
    "a", "an", "the", "some", "something",
    "article", "articles", "audio", "content", "episode", "episodes",
    "item", "items", "podcast", "podcasts", "record", "recording", "recordings",
    "sound", "story", "stories", "track", "tracks",
}
_FUZZY_CONTENT_NOUNS = tuple(
    value for value in CONTENT_NOUNS if len(value) >= 5
)
GENERIC_ORGANIZATION_REQUEST = re.compile(
    r"^(?:(?:play|find|hear|listen)(?:\s+me)?(?:\s+something)?\s+)?"
    r"(?:from\s+)?(?:a\s+|an\s+|the\s+)?"
    r"(?:talking\s+news\s*paper|talking\s+news|news\s*paper)"
    r"(?:\s+(?:recording|content|audio))?$",
    re.I,
)


@dataclass(frozen=True)
class CommandState:
    claimed: tuple[tuple[int, int], ...]
    sort: str
    is_recommended: bool
    is_local: bool


def normalize_utterance(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("’", "'").replace("`", "'").lower()
    text = re.sub(r"(?<=\w)'s\b", "", text)
    text = re.sub(r"[^a-z0-9'\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_reserved_content_noun(value: str) -> bool:
    """Recognize exact and safely misspelled generic playback nouns."""
    token = str(value or "").strip().lower()
    if token in CONTENT_NOUNS:
        return True
    if len(token) < 5:
        return False
    match = process.extractOne(token, _FUZZY_CONTENT_NOUNS, scorer=fuzz.ratio)
    return bool(match and match[1] >= 88)


def is_generic_organization_request(value: str | None) -> bool:
    """Return whether speech asks for an unnamed talking-newspaper source."""
    return bool(GENERIC_ORGANIZATION_REQUEST.fullmatch(
        normalize_utterance(value),
    ))


def _spans(patterns: tuple[str, ...], text: str) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    for pattern in patterns:
        found.extend(match.span() for match in re.finditer(pattern, text, re.I))
    return found


def parse_command_modifiers(text: str) -> CommandState:
    claimed = _spans(COMMAND_PATTERNS, text)
    latest = _spans(LATEST_PATTERNS, text)
    recommended = _spans(RECOMMENDED_PATTERNS, text)
    local = _spans(LOCAL_PATTERNS, text)
    claimed.extend(latest + recommended + local)
    is_recommended = bool(recommended)
    return CommandState(
        claimed=tuple(claimed),
        sort="latest" if latest else "recommended" if is_recommended else "relevance",
        is_recommended=is_recommended,
        is_local=bool(local),
    )
