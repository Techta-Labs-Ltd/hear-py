from __future__ import annotations

import logging

import spacy

logger = logging.getLogger(__name__)

_nlp = None
_name_map: dict[str, str] = {}

GENERIC_ENTITY_DENY: set[str] = {
    "new", "test", "creator", "creators", "admin", "user", "account", "flow", "editor",
    "contributor", "demo", "billing", "fresh", "super", "all", "independent", "organisation",
    "organisations", "organization", "organizations", "content", "the", "play", "show",
    "latest", "newest", "trending", "popular", "news",
}


def get_spacy_nlp():
    """Return the spaCy NLP singleton, loading the model if necessary."""
    global _nlp
    if _nlp is not None:
        return _nlp
    try:
        _nlp = spacy.load("en_core_web_sm")
    except OSError:
        logger.warning(
            "spaCy model 'en_core_web_sm' not found. "
            "Run: python -m spacy download en_core_web_sm"
        )
        _nlp = spacy.blank("en")
    return _nlp


def train_entities() -> None:
    """Train or update custom NER entities on the spaCy pipeline."""
    pass


def resolve_name(entity_type: str, partial: str) -> str:
    """Resolve a partial entity name against the canonical name map."""
    key = f"{entity_type}|{partial.lower()}"
    return _name_map.get(key, partial)


def resolve_name_prefix(entity_type: str, partial: str) -> str:
    """Resolve a partial entity name using prefix matching against the name map."""
    if len(partial) < 4:
        return partial
    p_lower = partial.lower()
    type_prefix = f"{entity_type}|"
    matched: str | None = None
    ambiguous = False
    for key, value in _name_map.items():
        if not key.startswith(type_prefix):
            continue
        part = key[len(type_prefix):]
        if part.startswith(p_lower) and part != p_lower:
            if matched is None:
                matched = value
            elif matched != value:
                ambiguous = True
                break
    return matched if (matched is not None and not ambiguous) else partial
