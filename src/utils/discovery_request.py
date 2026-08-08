from __future__ import annotations

import re


RESERVED_DISCOVERY_PHRASES = frozenset({
    "",
    "anything",
    "anything to listen to",
    "audio",
    "content",
    "give me anything",
    "give me something",
    "give me something new",
    "give me something to listen to",
    "find",
    "find me",
    "find something",
    "hear something",
    "let me listen",
    "listen",
    "play",
    "play anything",
    "play audio",
    "play content",
    "play for me",
    "play me anything",
    "play me something",
    "play recording",
    "play recordings",
    "play something",
    "put something on",
    "read me something",
    "recording",
    "recordings",
    "search",
    "search for something",
    "search something",
    "something",
    "something to listen to",
    "start",
    "start listening",
    "start playing",
    "start something",
    "whatever",
})


def normalize_discovery_phrase(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def is_reserved_discovery_phrase(value: object) -> bool:
    return normalize_discovery_phrase(value) in RESERVED_DISCOVERY_PHRASES
