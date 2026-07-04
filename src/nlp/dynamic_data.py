from __future__ import annotations

from src.nlp.wink_instance import train_entities

_categories: dict = {"names": set(), "synonyms": {}, "stems": {}}
_creators: dict = {"names": set(), "synonyms": {}}
_organizations: dict = {"names": set(), "synonyms": {}}
_locations: dict = {"cities": set()}
_loaded = False


def get_categories() -> dict:
    """Return the cached category entity data."""
    return _categories


def get_creators() -> dict:
    """Return the cached creator entity data."""
    return _creators


def get_organizations() -> dict:
    """Return the cached organization entity data."""
    return _organizations


def get_locations() -> dict:
    """Return the cached location entity data."""
    return _locations


def is_loaded() -> bool:
    """Check whether dynamic entity data has been loaded."""
    return _loaded


async def load() -> None:
    """Load dynamic entity data for NLP classification."""
    global _loaded
    _loaded = True
    train_entities()
