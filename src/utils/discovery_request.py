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

PUBLICATION_SOURCE_PLACEHOLDERS = frozenset({
    "publication", "publications", "a publication", "the publication",
    "play publication", "play publications", "play a publication",
    "play the publication", "play something from a publication",
    "find publication", "find a publication", "latest publication",
    "the latest publication", "something from a publication",
})

CREATOR_SOURCE_PLACEHOLDERS = frozenset({
    "creator", "a creator", "the creator", "from a creator",
    "play creator", "play a creator", "play from a creator",
    "play something from a creator", "play me something from a creator",
})

ORGANIZATION_SOURCE_PLACEHOLDERS = frozenset({
    "talking newspaper", "talking news paper", "a talking newspaper",
    "a talking news paper", "the talking newspaper", "the talking news paper",
    "from a talking newspaper", "from a talking news paper",
    "play from a talking newspaper", "play from a talking news paper",
    "play something from a talking newspaper",
    "play something from a talking news paper",
    "play me a talking newspaper", "play me a talking news paper",
})


def normalize_discovery_phrase(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def is_reserved_discovery_phrase(value: object) -> bool:
    return normalize_discovery_phrase(value) in RESERVED_DISCOVERY_PHRASES


def is_meaningful_publication_source(value: object) -> bool:
    normalized = normalize_discovery_phrase(value)
    return bool(
        normalized
        and normalized not in RESERVED_DISCOVERY_PHRASES
        and normalized not in PUBLICATION_SOURCE_PLACEHOLDERS
    )


def is_meaningful_creator_source(value: object) -> bool:
    normalized = normalize_discovery_phrase(value)
    return bool(
        normalized
        and normalized not in RESERVED_DISCOVERY_PHRASES
        and normalized not in CREATOR_SOURCE_PLACEHOLDERS
    )


def is_meaningful_organization_source(value: object) -> bool:
    normalized = normalize_discovery_phrase(value)
    return bool(
        normalized
        and normalized not in RESERVED_DISCOVERY_PHRASES
        and normalized not in ORGANIZATION_SOURCE_PLACEHOLDERS
    )


def is_generic_organization_request(value: object) -> bool:
    return normalize_discovery_phrase(value) in ORGANIZATION_SOURCE_PLACEHOLDERS
